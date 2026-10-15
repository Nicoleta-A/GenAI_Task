"""LLM-backed charge rule extraction with validation/repair."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from tariff_agent.domain.exceptions import LLMOutputError
from tariff_agent.domain.rules import ChargeRule, Rulebook
from tariff_agent.domain.vessel import FACT_DESCRIPTIONS
from tariff_agent.engine.normalize import normalize_rule
from tariff_agent.extraction.validators import ValidationIssue, validate_rules
from tariff_agent.ingestion.pdf_pages import Page
from tariff_agent.llm.client import LLMClient

# Keep each Gemini request small enough that the API does not drop the connection.
PAGE_CHARS = 2000
MAX_BATCH_CHARS = 12_000


class ExtractedRules(BaseModel):
    rules: list[ChargeRule] = Field(default_factory=list)


@dataclass
class ExtractResult:
    rules: list[ChargeRule]
    warnings: list[str] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)


def _load_prompt() -> str:
    path = Path(__file__).resolve().parent / "prompts" / "extractor.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "Extract ChargeRule JSON for all ports on the attached pages."


def _page_block(pages: Sequence[Page], *, limit: int = PAGE_CHARS) -> str:
    return "\n".join(f"--- page {p.printed_number} ---\n{p.text[:limit]}" for p in pages)


def _charge_sections(located: Mapping[str, Sequence[Page]]) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    for charge_type, pages in located.items():
        if not pages:
            continue
        body = _page_block(pages)
        if body:
            sections.append((charge_type, body))
    return sections


def _pack_sections(
    sections: Sequence[tuple[str, str]],
    *,
    max_chars: int = MAX_BATCH_CHARS,
) -> list[list[tuple[str, str]]]:
    """Group charge sections so each batch's page text stays under ``max_chars``."""
    batches: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    size = 0
    for item in sections:
        text_len = len(item[1])
        if current and size + text_len > max_chars:
            batches.append(current)
            current = []
            size = 0
        current.append(item)
        size += text_len
    if current:
        batches.append(current)
    return batches


def _extract_once(
    client: LLMClient,
    prompt: str,
    page_texts: Mapping[int, str],
    *,
    max_repairs: int = 1,
    sample_facts: Mapping[str, Any] | None = None,
) -> ExtractResult:
    """One structured call, plus at most ``max_repairs`` follow-ups if validation fails."""
    warnings: list[str] = []
    response = client.generate(prompt, schema=ExtractedRules)
    rules = _coerce_rules(response.parsed, response.text)
    report = validate_rules(rules, page_texts, sample_facts)
    attempts = 0
    while (not rules or not report.ok) and attempts < max_repairs:
        attempts += 1
        error_blob = json.dumps([i.__dict__ for i in report.issues], indent=2)
        response = client.generate(
            prompt + f"\n\nPrevious extraction failed validation:\n{error_blob}\nFix the rules.",
            schema=ExtractedRules,
        )
        rules = _coerce_rules(response.parsed, response.text)
        report = validate_rules(rules, page_texts, sample_facts)

    if not report.ok:
        for issue in report.issues:
            for rule in rules:
                if rule.id == issue.rule_id and "unverified" not in rule.assumptions:
                    rule.assumptions.append(f"unverified: {issue.code} — {issue.message}")
        warnings.append("Validation issues remain; rules marked unverified where applicable")
    return ExtractResult(rules=rules, warnings=warnings, issues=report.issues)


def extract_rules(
    client: LLMClient,
    charge_type: str,
    pages: Sequence[Page],
    *,
    max_repairs: int = 1,
    sample_facts: Mapping[str, Any] | None = None,
) -> ExtractResult:
    """Extract rules for one charge type. Prefer ``build_rulebook`` (one call for all types)."""
    prompt = "\n\n".join(
        [
            _load_prompt(),
            f"Charge type: {charge_type}",
            f"Fact vocabulary: {json.dumps(FACT_DESCRIPTIONS)}",
            _page_block(pages),
            "Return ExtractedRules JSON.",
        ]
    )
    return _extract_once(
        client,
        prompt,
        {p.printed_number: p.text for p in pages},
        max_repairs=max_repairs,
        sample_facts=sample_facts,
    )


def _coerce_rules(parsed: Any, text: str) -> list[ChargeRule]:
    raw: list[ChargeRule]
    if isinstance(parsed, ExtractedRules):
        raw = list(parsed.rules)
    elif isinstance(parsed, BaseModel):
        raw = ExtractedRules.model_validate(parsed.model_dump()).rules
    elif isinstance(parsed, dict):
        raw = ExtractedRules.model_validate(parsed).rules
    else:
        try:
            raw = ExtractedRules.model_validate_json(text).rules
        except Exception:
            return []
    return [normalize_rule(rule) for rule in raw]


def _prompt_for(batch: Sequence[tuple[str, str]]) -> str:
    names = ", ".join(name for name, _ in batch)
    blocks = [f"## {name}\n{body}" for name, body in batch]
    return "\n\n".join(
        [
            _load_prompt(),
            f"Extract ChargeRules for: {names}.",
            f"Fact vocabulary: {json.dumps(FACT_DESCRIPTIONS)}",
            *blocks,
            "Return ExtractedRules JSON. charge_type must be one of the labels above.",
        ]
    )


def _pages_for(located: Mapping[str, Sequence[Page]], names: Sequence[str]) -> dict[int, str]:
    texts: dict[int, str] = {}
    for name in names:
        for page in located.get(name, ()):
            texts.setdefault(page.printed_number, page.text)
    return texts


def build_rulebook(
    client: LLMClient,
    located: Mapping[str, Sequence[Page]],
    document: str = "",
) -> tuple[Rulebook, list[str]]:
    """Extract in small batches so one request cannot hang the API."""
    warnings: list[str] = []
    for charge_type, pages in located.items():
        if not pages:
            warnings.append(f"{charge_type}: no pages located; skipped extraction")
    sections = _charge_sections(located)
    if not sections:
        return Rulebook(document=document, rules=[]), warnings

    rules: list[ChargeRule] = []
    for batch in _pack_sections(sections):
        names = [name for name, _ in batch]
        try:
            result = _extract_once(client, _prompt_for(batch), _pages_for(located, names))
        except LLMOutputError as exc:
            warnings.append(f"{', '.join(names)}: extraction failed: {exc}")
            continue
        rules.extend(result.rules)
        warnings.extend(result.warnings)
    return Rulebook(document=document, rules=rules), warnings
