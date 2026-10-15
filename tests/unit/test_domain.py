"""Unit tests for domain models."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from tariff_agent.domain.rules import ChargeRule, Rulebook
from tariff_agent.domain.vessel import VesselProfile

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_sudestada_gt() -> None:
    payload = json.loads((FIXTURES / "vessel_sudestada.json").read_text(encoding="utf-8"))
    vessel = VesselProfile.from_json(payload)
    assert vessel.facts()["gt"] == 51300
    assert vessel.facts()["num_operations"] == 2
    assert vessel.facts()["days_alongside"] == 3.39


def test_negative_gt_rejected() -> None:
    with pytest.raises(ValidationError):
        VesselProfile(gt=-1, days_alongside=1.0)


def test_charge_rule_round_trip() -> None:
    raw = {
        "id": "demo",
        "charge_type": "light_dues",
        "ports": ["*"],
        "applies_when": "True",
        "bands": [
            {
                "when": "True",
                "components": [
                    {
                        "label": "x",
                        "rate": 1.0,
                        "per": "gt",
                        "unit_size": 100,
                        "rounding": "ceil",
                        "over": 0,
                        "times": "1",
                    }
                ],
            }
        ],
        "modifiers": [],
        "minimum": None,
        "currency": "ZAR",
        "source_page": 1,
        "source_quote": "demo",
        "assumptions": [],
    }
    rule = ChargeRule.model_validate(raw)
    assert ChargeRule.model_validate(rule.model_dump()) == rule


def test_gold_rulebook_validates() -> None:
    payload = json.loads((FIXTURES / "durban_gold_rulebook.json").read_text(encoding="utf-8"))
    book = Rulebook.model_validate(payload)
    assert len(book.rules) >= 8
