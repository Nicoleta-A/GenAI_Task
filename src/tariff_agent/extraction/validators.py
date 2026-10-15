"""Validators for extracted charge rules."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from tariff_agent.domain.rules import ChargeRule
from tariff_agent.engine.expressions import referenced_names, safe_eval


@dataclass
class ValidationIssue:
    rule_id: str
    code: str
    message: str


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues


def _norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _norm_number_text(text: str) -> str:
    # Collapse spaces inside numbers like "18 608.61"
    return re.sub(r"(?<=\d)\s+(?=\d)", "", text)


def quote_in_page(quote: str, page_text: str) -> bool:
    return _norm_ws(quote) in _norm_ws(page_text)


def rate_in_page(rate: float, page_text: str) -> bool:
    normalized = _norm_number_text(page_text)
    # Prefer exact string forms used in tariffs.
    candidates = {f"{rate}", f"{rate:.2f}", f"{rate:.0f}" if float(rate).is_integer() else f"{rate}"}
    # Also allow space-grouped forms already normalized away.
    for cand in candidates:
        if cand in normalized.replace(" ", ""):
            return True
    return False


def validate_rule(
    rule: ChargeRule,
    page_text: str,
    sample_facts: Mapping[str, Any],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not rule.ports:
        issues.append(ValidationIssue(rule.id, "ports", "ports must be non-empty"))
    if not quote_in_page(rule.source_quote, page_text):
        # Soft: quote may be paraphrased; still flag.
        issues.append(
            ValidationIssue(rule.id, "quote", "source_quote not found in page text (normalized)")
        )
    _check_expr(rule, rule.applies_when, issues, sample_facts)
    for band in rule.bands:
        for component in band.components:
            if component.rate < 0:
                issues.append(ValidationIssue(rule.id, "rate", "negative rate"))
            if not rate_in_page(component.rate, page_text):
                issues.append(
                    ValidationIssue(
                        rule.id,
                        "rate_grounding",
                        f"rate {component.rate} not found in page text",
                    )
                )
            for expr in filter(None, [component.per, component.times, band.when]):
                _check_expr(rule, expr, issues, sample_facts)
    if rule.minimum is not None and rule.minimum < 0:
        issues.append(ValidationIssue(rule.id, "minimum", "negative minimum"))
    issues.extend(_band_coverage_issues(rule))
    return issues


def _check_expr(
    rule: ChargeRule,
    expr: str,
    issues: list[ValidationIssue],
    sample_facts: Mapping[str, Any] | None = None,
) -> None:
    if not expr:
        return
    try:
        names = referenced_names(expr)
        facts = dict(sample_facts or {})
        for name in names:
            facts.setdefault(name, 1)
        safe_eval(expr, facts)
    except Exception as exc:  # noqa: BLE001
        issues.append(ValidationIssue(rule.id, "expression", f"{expr!r}: {exc}"))


def _band_coverage_issues(rule: ChargeRule) -> list[ValidationIssue]:
    """Detect trivial overlaps when bands are all literal True — skip complex GT algebra."""
    whens = [b.when.strip() for b in rule.bands]
    if len(whens) > 1 and all(w == "True" for w in whens):
        return [ValidationIssue(rule.id, "bands", "multiple bands with when=True overlap")]
    return []


def validate_rules(
    rules: Sequence[ChargeRule],
    page_texts: Mapping[int, str],
    sample_facts: Mapping[str, Any] | None = None,
) -> ValidationReport:
    facts = sample_facts or {
        "gt": 50000,
        "num_operations": 2,
        "days_alongside": 3.0,
    }
    report = ValidationReport()
    for rule in rules:
        text = page_texts.get(rule.source_page, "")
        report.issues.extend(validate_rule(rule, text, facts))
    return report
