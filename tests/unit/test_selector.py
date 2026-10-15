"""Rule selection and calculate_all tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tariff_agent.domain.rules import ChargeRule, Rulebook
from tariff_agent.domain.vessel import VesselProfile
from tariff_agent.engine.selector import calculate_all

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _sudestada_facts() -> dict[str, Any]:
    payload = json.loads((FIXTURES / "vessel_sudestada.json").read_text(encoding="utf-8"))
    return VesselProfile.from_json(payload).facts()


def _gold() -> Rulebook:
    return Rulebook.model_validate(
        json.loads((FIXTURES / "durban_gold_rulebook.json").read_text(encoding="utf-8"))
    )


def test_bay_suffix_matches_the_same_port() -> None:
    rule = ChargeRule.model_validate(
        {
            "id": "vts_specific",
            "charge_type": "vts",
            "ports": ["Saldanha Bay"],
            "bands": [
                {
                    "when": "True",
                    "components": [
                        {"label": "VTS", "rate": 0.65, "per": "gt", "unit_size": 1, "rounding": "none"}
                    ],
                }
            ],
            "source_page": 1,
            "source_quote": "q",
        }
    )
    other = ChargeRule.model_validate(
        {
            "id": "vts_other",
            "charge_type": "vts",
            "ports": ["*"],
            "bands": [
                {
                    "when": "True",
                    "components": [
                        {"label": "VTS", "rate": 0.54, "per": "gt", "unit_size": 1, "rounding": "none"}
                    ],
                }
            ],
            "source_page": 1,
            "source_quote": "q",
        }
    )
    book = Rulebook(document="t", rules=[rule, other])
    facts = {"gt": 100, "num_operations": 1, "days_alongside": 1}
    short = calculate_all(book, "Saldanha", facts)
    long = calculate_all(book, "Saldanha Bay", facts)
    assert short.by_type()["vts"].rule_id == "vts_specific"
    assert long.by_type()["vts"].rule_id == "vts_specific"
    assert short.by_type()["vts"].amount == 65.0


def test_exact_port_beats_wildcard_vts() -> None:
    facts = _sudestada_facts()
    gold = _gold()
    durban = calculate_all(gold, "Durban", facts)
    other = calculate_all(gold, "SomeUnknownPort", facts)
    assert durban.by_type()["vts"].amount == 33345.00
    assert other.by_type()["vts"].amount == 27702.00


def test_wildcard_fallback_berthing() -> None:
    report = calculate_all(_gold(), "Durban", _sudestada_facts())
    assert report.by_type()["berthing_services"].status == "ok"
    assert report.by_type()["running_of_lines"].status == "ok"


def test_applies_when_false_excludes() -> None:
    book = Rulebook(
        document="t",
        rules=[
            ChargeRule.model_validate(
                {
                    "id": "a",
                    "charge_type": "light_dues",
                    "ports": ["*"],
                    "applies_when": "gt > 999999",
                    "bands": [
                        {"when": "True", "components": [{"label": "x", "rate": 1.0, "per": None}]}
                    ],
                    "source_page": 1,
                    "source_quote": "q",
                }
            )
        ],
    )
    report = calculate_all(book, "X", {"gt": 100, "num_operations": 1, "days_alongside": 1})
    assert report.by_type()["light_dues"].status == "not_found"


def test_ambiguous_rules_error() -> None:
    rule_raw = {
        "id": "a",
        "charge_type": "light_dues",
        "ports": ["PortA"],
        "bands": [{"when": "True", "components": [{"label": "x", "rate": 1.0, "per": None}]}],
        "source_page": 1,
        "source_quote": "q",
    }
    r1 = ChargeRule.model_validate({**rule_raw, "id": "a"})
    r2 = ChargeRule.model_validate({**rule_raw, "id": "b"})
    book = Rulebook(document="t", rules=[r1, r2])
    report = calculate_all(book, "PortA", {"gt": 1, "num_operations": 1, "days_alongside": 1})
    assert report.by_type()["light_dues"].status == "error"


def test_unknown_modifier_fact_skipped() -> None:
    report = calculate_all(_gold(), "Durban", _sudestada_facts())
    pilotage = report.by_type()["pilotage"]
    assert pilotage.status == "ok"
    assert any("outside_ordinary_hours" in a or "Skipped modifier" in a for a in pilotage.assumptions)


def test_lowercase_true_and_js_and_still_calculate() -> None:
    book = Rulebook(
        document="t",
        rules=[
            ChargeRule.model_validate(
                {
                    "id": "light_dues_licensed",
                    "charge_type": "light_dues",
                    "ports": ["*"],
                    "applies_when": "licensed_by_authority",
                    "bands": [
                        {
                            "when": "true",
                            "components": [
                                {"label": "x", "rate": 1.0, "per": "gt", "unit_size": 100}
                            ],
                        }
                    ],
                    "source_page": 1,
                    "source_quote": "licensed",
                }
            ),
            ChargeRule.model_validate(
                {
                    "id": "light_dues_other_vessels",
                    "charge_type": "light_dues",
                    "ports": ["*"],
                    "applies_when": "all_other_vessels",
                    "bands": [
                        {
                            "when": "true",
                            "components": [
                                {"label": "x", "rate": 10.0, "per": "gt", "unit_size": 100}
                            ],
                        }
                    ],
                    "source_page": 1,
                    "source_quote": "Per 100 tons",
                }
            ),
            ChargeRule.model_validate(
                {
                    "id": "running_of_lines_other_ports_ordinary_hours",
                    "charge_type": "running_of_lines",
                    "ports": ["*"],
                    "applies_when": "ordinary_working_hours",
                    "bands": [
                        {
                            "when": "true",
                            "components": [{"label": "per service", "rate": 5.0, "per": None}],
                        }
                    ],
                    "source_page": 1,
                    "source_quote": "per service during ordinary working hours",
                }
            ),
            ChargeRule.model_validate(
                {
                    "id": "running_of_lines_other_ports_outside_hours",
                    "charge_type": "running_of_lines",
                    "ports": ["*"],
                    "applies_when": "outside_ordinary_working_hours",
                    "bands": [
                        {
                            "when": "true",
                            "components": [{"label": "per service", "rate": 9.0, "per": None}],
                        }
                    ],
                    "source_page": 1,
                    "source_quote": "outside ordinary working hours",
                }
            ),
        ],
    )
    report = calculate_all(
        book,
        "X",
        {"gt": 250, "num_operations": 2, "days_alongside": 1},
    )
    light = report.by_type()["light_dues"]
    lines = report.by_type()["running_of_lines"]
    assert light.status == "ok"
    assert light.amount == 30.0
    assert lines.status == "ok"
    assert lines.amount == 10.0


def test_missing_charge_not_found_not_zero() -> None:
    book = Rulebook(document="t", rules=[])
    report = calculate_all(
        book,
        "X",
        {"gt": 1, "num_operations": 1, "days_alongside": 1},
        charge_types=["light_dues"],
    )
    item = report.by_type()["light_dues"]
    assert item.status == "not_found"
    assert item.amount is None


def test_vat_rate_applied() -> None:
    report = calculate_all(_gold(), "Durban", _sudestada_facts(), vat_rate=0.15)
    light = report.by_type()["light_dues"]
    assert light.amount is not None
    assert light.vat_amount is not None
    assert abs(light.vat_amount - light.amount * 0.15) < 0.02
    default = calculate_all(_gold(), "Durban", _sudestada_facts())
    assert default.by_type()["light_dues"].vat_amount is None


def test_full_golden_durban_report() -> None:
    expected = json.loads((FIXTURES / "expected_durban.json").read_text(encoding="utf-8"))
    report = calculate_all(_gold(), "Durban", _sudestada_facts())
    by_type = report.by_type()

    for key, spec in expected["charges"].items():
        if key == "running_lines_reference":
            charge_type = spec["maps_to"]
            exp = float(spec["expected"])
            tol_abs = spec.get("abs_tol")
            item = by_type[charge_type]
        else:
            charge_type = key
            exp = float(spec["expected"])
            tol_abs = spec.get("abs_tol")
            item = by_type[charge_type]
        assert item.status == "ok", (charge_type, item.error)
        assert item.amount is not None
        if tol_abs is not None:
            assert abs(item.amount - exp) <= tol_abs, (charge_type, item.amount, exp)
        else:
            rel = abs(item.amount - exp) / exp
            assert rel <= spec["rel_tol"], (charge_type, item.amount, exp, rel)

    info = expected["informational"]["running_of_lines"]
    assert by_type["running_of_lines"].amount is not None
    assert abs(by_type["running_of_lines"].amount - info) <= 0.01
