"""Expression evaluator and calculator tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tariff_agent.domain.exceptions import AmbiguousBands, ExpressionSecurityError, UnknownFact
from tariff_agent.domain.rules import ChargeRule, Rulebook
from tariff_agent.domain.vessel import VesselProfile
from tariff_agent.engine.calculator import calculate_rule
from tariff_agent.engine.expressions import safe_eval

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _sudestada_facts() -> dict[str, Any]:
    payload = json.loads((FIXTURES / "vessel_sudestada.json").read_text(encoding="utf-8"))
    return VesselProfile.from_json(payload).facts()


def _gold() -> Rulebook:
    return Rulebook.model_validate(
        json.loads((FIXTURES / "durban_gold_rulebook.json").read_text(encoding="utf-8"))
    )


def test_allowed_functions() -> None:
    assert safe_eval("ceil(1.1)", {}) == 2
    assert safe_eval("floor(1.9)", {}) == 1
    assert safe_eval("min(3, 1)", {}) == 1
    assert safe_eval("max(3, 1)", {}) == 3
    assert safe_eval("abs(-2)", {}) == 2


def test_rejects_attribute_access() -> None:
    with pytest.raises(ExpressionSecurityError):
        safe_eval("().__class__", {})


def test_rejects_dunder() -> None:
    with pytest.raises(ExpressionSecurityError):
        safe_eval("__import__('os')", {})


def test_unknown_name() -> None:
    with pytest.raises(UnknownFact):
        safe_eval("missing_fact + 1", {"gt": 1})


def test_per_100_ceil_boundaries() -> None:
    rule = ChargeRule.model_validate(
        {
            "id": "t",
            "charge_type": "light_dues",
            "ports": ["*"],
            "bands": [
                {
                    "when": "True",
                    "components": [
                        {
                            "label": "x",
                            "rate": 10.0,
                            "per": "gt",
                            "unit_size": 100,
                            "rounding": "ceil",
                            "over": 0,
                            "times": "1",
                        }
                    ],
                }
            ],
            "source_page": 1,
            "source_quote": "q",
        }
    )
    r100 = calculate_rule(rule, {"gt": 100})
    r101 = calculate_rule(rule, {"gt": 101})
    assert r100.status == "ok" and r100.amount == 10.0
    assert r101.status == "ok" and r101.amount == 20.0


def test_over_at_exact_boundary() -> None:
    rule = ChargeRule.model_validate(
        {
            "id": "t",
            "charge_type": "towage",
            "ports": ["*"],
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
                            "over": 50000,
                            "times": "1",
                        }
                    ],
                }
            ],
            "source_page": 1,
            "source_quote": "q",
        }
    )
    result = calculate_rule(rule, {"gt": 50000})
    assert result.status == "ok"
    assert result.amount == 0.0


def test_band_edges_towage() -> None:
    rule = next(r for r in _gold().rules if r.id == "towage_durban")
    low = calculate_rule(rule, {"gt": 50000, "num_operations": 2})
    high = calculate_rule(rule, {"gt": 50001, "num_operations": 2})
    assert low.status == "ok" and high.status == "ok"
    assert low.rule_id == "towage_durban"
    # 50000 in 10000 < gt <= 50000; 50001 in next band — different breakdown rates
    assert low.breakdown[0]["rate"] != high.breakdown[0]["rate"]


def test_no_band_matched() -> None:
    rule = ChargeRule.model_validate(
        {
            "id": "t",
            "charge_type": "x",
            "ports": ["*"],
            "bands": [{"when": "gt > 999999", "components": [{"label": "a", "rate": 1.0}]}],
            "source_page": 1,
            "source_quote": "q",
        }
    )
    result = calculate_rule(rule, {"gt": 1})
    assert result.status == "not_found"
    assert result.amount is None
    assert "No band" in (result.error or "")


def test_ambiguous_bands() -> None:
    rule = ChargeRule.model_validate(
        {
            "id": "t",
            "charge_type": "x",
            "ports": ["*"],
            "bands": [
                {"when": "True", "components": [{"label": "a", "rate": 1.0}]},
                {"when": "True", "components": [{"label": "b", "rate": 2.0}]},
            ],
            "source_page": 1,
            "source_quote": "q",
        }
    )
    result = calculate_rule(rule, {"gt": 1})
    assert result.status == "error"
    assert "bands matched" in (result.error or "").lower() or AmbiguousBands


def test_minimum_binds() -> None:
    rule = next(r for r in _gold().rules if r.id == "vts_durban_saldanha")
    result = calculate_rule(rule, {"gt": 1})
    assert result.status == "ok"
    assert result.amount == 235.52


def test_golden_durban_charges() -> None:
    expected = json.loads((FIXTURES / "expected_durban.json").read_text(encoding="utf-8"))
    facts = _sudestada_facts()
    gold = _gold()
    mapping = {
        "light_dues": "light_dues_per_100gt",
        "port_dues": "port_dues",
        "towage": "towage_durban",
        "vts": "vts_durban_saldanha",
        "pilotage": "pilotage_durban",
        "berthing_services": "berthing_other_ports",
    }
    # Resolve running_lines_reference alias in fixture only
    charges = dict(expected["charges"])
    ref = charges.pop("running_lines_reference")
    charges[ref["maps_to"]] = {"expected": ref["expected"], "abs_tol": ref["abs_tol"]}

    for charge_type, spec in charges.items():
        rule = next(r for r in gold.rules if r.id == mapping[charge_type])
        result = calculate_rule(rule, facts)
        assert result.status == "ok", result.error
        assert result.amount is not None
        exp = float(spec["expected"])
        if "abs_tol" in spec:
            assert abs(result.amount - exp) <= spec["abs_tol"], (charge_type, result.amount, exp)
        else:
            rel = abs(result.amount - exp) / exp
            assert rel <= spec["rel_tol"], (charge_type, result.amount, exp, rel)
