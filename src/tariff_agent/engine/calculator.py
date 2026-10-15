"""Deterministic charge calculator (no LLM)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tariff_agent.domain.exceptions import (
    AmbiguousBands,
    ExpressionSecurityError,
    NoBandMatched,
    UnknownFact,
)
from tariff_agent.domain.results import ChargeResult, Citation
from tariff_agent.domain.rules import Band, ChargeRule, Component
from tariff_agent.engine.expressions import referenced_names, safe_eval
from tariff_agent.engine.money import money


def _units(component: Component, per_value: float) -> float:
    raw = max(per_value - component.over, 0.0) / component.unit_size
    if component.rounding == "ceil":
        return float(math_ceil_safe(raw))
    return raw


def math_ceil_safe(x: float) -> int:
    import math

    return int(math.ceil(round(x, 9)))


def _component_amount(
    component: Component, facts: Mapping[str, Any]
) -> tuple[float, dict[str, Any]]:
    times_value = float(safe_eval(component.times, facts))
    if component.per is None:
        amount = component.rate * times_value
        detail = {
            "label": component.label,
            "rate": component.rate,
            "units": None,
            "times": times_value,
            "amount": amount,
        }
        return amount, detail

    if _looks_like_expr(component.per):
        per_names = referenced_names(component.per)
    else:
        per_names = {component.per}
    for name in per_names:
        if name not in facts:
            raise UnknownFact(name)
    if _looks_like_expr(component.per):
        per_value = float(safe_eval(component.per, facts))
    else:
        per_value = float(facts[component.per])
    units = _units(component, per_value)
    amount = component.rate * units * times_value
    detail = {
        "label": component.label,
        "rate": component.rate,
        "per": component.per,
        "units": units,
        "times": times_value,
        "amount": amount,
    }
    return amount, detail


def _looks_like_expr(text: str) -> bool:
    return any(ch in text for ch in " +-*/<>()!=%")


def _select_band(rule: ChargeRule, facts: Mapping[str, Any]) -> Band:
    matched: list[Band] = []
    for band in rule.bands:
        needed = referenced_names(band.when)
        missing = needed - set(facts.keys())
        if missing:
            raise UnknownFact(sorted(missing)[0])
        if bool(safe_eval(band.when, facts)):
            matched.append(band)
    if not matched:
        raise NoBandMatched(rule.id)
    if len(matched) > 1:
        raise AmbiguousBands(rule.id, len(matched))
    return matched[0]


def calculate_rule(rule: ChargeRule, facts: Mapping[str, Any]) -> ChargeResult:
    """Apply one ChargeRule to vessel facts."""
    assumptions = list(rule.assumptions)
    try:
        band = _select_band(rule, facts)
        total = 0.0
        breakdown: list[dict[str, Any]] = []
        for component in band.components:
            amount, detail = _component_amount(component, facts)
            total += amount
            breakdown.append(detail)

        for modifier in rule.modifiers:
            needed = referenced_names(modifier.when)
            if needed - set(facts.keys()):
                assumptions.append(
                    f"Skipped modifier '{modifier.label}': unknown fact "
                    f"{sorted(needed - set(facts.keys()))}"
                )
                continue
            if bool(safe_eval(modifier.when, facts)):
                total *= modifier.factor
                breakdown.append(
                    {
                        "label": modifier.label,
                        "factor": modifier.factor,
                        "amount": total,
                    }
                )

        if rule.minimum is not None and total < rule.minimum:
            breakdown.append({"label": "minimum applied", "minimum": rule.minimum, "before": total})
            total = rule.minimum

        amount = money(total)
        return ChargeResult(
            charge_type=rule.charge_type,
            status="ok",
            amount=amount,
            currency=rule.currency,
            breakdown=breakdown,
            assumptions=assumptions,
            citation=Citation(page=rule.source_page, quote=rule.source_quote),
            rule_id=rule.id,
        )
    except NoBandMatched as exc:
        # A published n/a cell is an absent rate, not a failed calculation.
        assumptions.append(str(exc))
        return ChargeResult(
            charge_type=rule.charge_type,
            status="not_found",
            amount=None,
            assumptions=assumptions,
            citation=Citation(page=rule.source_page, quote=rule.source_quote),
            rule_id=rule.id,
            error=str(exc),
        )
    except (UnknownFact, AmbiguousBands, ExpressionSecurityError) as exc:
        return ChargeResult(
            charge_type=rule.charge_type,
            status="error",
            assumptions=assumptions,
            citation=Citation(page=rule.source_page, quote=rule.source_quote),
            rule_id=rule.id,
            error=str(exc),
        )
