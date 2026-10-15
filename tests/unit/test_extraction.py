"""Extractor validators and compare tests."""

from __future__ import annotations

import json
from pathlib import Path

from tariff_agent.domain.rules import ChargeRule, Rulebook
from tariff_agent.extraction.compare import compare_rulebooks
from tariff_agent.extraction.extractor import _pack_sections, extract_rules
from tariff_agent.extraction.validators import rate_in_page, validate_rule
from tariff_agent.ingestion.pdf_pages import Page
from tariff_agent.llm.client import FakeLLM, LLMResponse

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_rate_normalization() -> None:
    assert rate_in_page(18608.61, "Basic Fee 18 608.61 Per 100 tons")


def test_validate_quote_and_rate() -> None:
    rule = ChargeRule.model_validate(
        {
            "id": "x",
            "charge_type": "light_dues",
            "ports": ["*"],
            "bands": [
                {
                    "when": "True",
                    "components": [
                        {"label": "a", "rate": 10.5, "per": "gt", "unit_size": 100, "times": "1"}
                    ],
                }
            ],
            "source_page": 1,
            "source_quote": "Per 100 tons 10.5",
        }
    )
    issues = validate_rule(
        rule,
        "Per 100 tons 10.5 applies here",
        {"gt": 100, "num_operations": 1, "days_alongside": 1},
    )
    assert not any(i.code == "rate_grounding" for i in issues)


def test_compare_gold_to_self() -> None:
    gold = Rulebook.model_validate(
        json.loads((FIXTURES / "durban_gold_rulebook.json").read_text(encoding="utf-8"))
    )
    result = compare_rulebooks(gold, gold)
    assert result.ok
    assert result.field_accuracy == 1.0


def test_compare_detects_missing() -> None:
    gold = Rulebook.model_validate(
        json.loads((FIXTURES / "durban_gold_rulebook.json").read_text(encoding="utf-8"))
    )
    extracted = Rulebook(document=gold.document, rules=gold.rules[:1])
    result = compare_rulebooks(gold, extracted)
    assert result.missing_ids
    assert not result.ok


def test_pack_sections_splits_before_char_budget() -> None:
    sections = [("a", "x" * 8), ("b", "y" * 8), ("c", "z" * 3)]
    batches = _pack_sections(sections, max_chars=10)
    assert batches == [[("a", "x" * 8)], [("b", "y" * 8)], [("c", "z" * 3)]]


def test_extract_with_fake_llm_and_repair() -> None:
    gold = Rulebook.model_validate(
        json.loads((FIXTURES / "durban_gold_rulebook.json").read_text(encoding="utf-8"))
    )
    light = next(r for r in gold.rules if r.charge_type == "light_dues")
    page = Page(
        index=0,
        printed_number=light.source_page,
        text=light.source_quote + " extra context",
        pdf_bytes=b"%PDF",
    )
    # First response empty → repair returns gold rule
    payload = {"rules": [light.model_dump()]}
    fake = FakeLLM(
        [
            LLMResponse(text="{}", parsed={"rules": []}),
            LLMResponse(text=json.dumps(payload), parsed=payload),
        ]
    )
    result = extract_rules(fake, "light_dues", [page], max_repairs=2)
    assert len(result.rules) == 1
    assert result.rules[0].id == light.id


def test_hand_built_extracted_matches_gold() -> None:
    gold = Rulebook.model_validate(
        json.loads((FIXTURES / "durban_gold_rulebook.json").read_text(encoding="utf-8"))
    )
    # Simulate a successful extraction equal to gold (offline / cassette stand-in).
    extracted = Rulebook.model_validate(gold.model_dump())
    cmp = compare_rulebooks(gold, extracted)
    assert cmp.ok
