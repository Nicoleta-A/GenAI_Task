"""Rule selection and multi-charge calculation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from tariff_agent.domain.exceptions import AmbiguousRules, ExpressionSecurityError, UnknownFact
from tariff_agent.domain.results import CalculationReport, ChargeResult
from tariff_agent.domain.rules import ChargeRule, Rulebook
from tariff_agent.domain.vessel import FACT_DESCRIPTIONS
from tariff_agent.engine.calculator import calculate_rule
from tariff_agent.engine.expressions import referenced_names, safe_eval
from tariff_agent.engine.money import money
from tariff_agent.engine.normalize import clauses, is_residual, normalize_rule


def _port_key(name: str) -> str:
    """Fold 'X' and 'X Bay' onto one port. The tariff uses both spellings."""
    key = name.casefold().strip()
    suffix = " bay"
    if key.endswith(suffix):
        key = key[: -len(suffix)].strip()
    return key


def _port_matches(rule_ports: Sequence[str], port: str) -> tuple[bool, bool]:
    """Return (matches, is_exact)."""
    port_key = _port_key(port)
    exact = False
    wildcard = False
    for entry in rule_ports:
        if entry == "*":
            wildcard = True
        elif _port_key(entry) == port_key:
            exact = True
    return (exact or wildcard), exact


def _clause_state(clause: str, facts: Mapping[str, Any]) -> str:
    """Return yes, no, open, missing, or invalid."""
    try:
        names = referenced_names(clause)
    except ExpressionSecurityError:
        return "invalid"
    unknown = names - set(FACT_DESCRIPTIONS)
    missing = (names - unknown) - set(facts)
    if missing:
        return "missing"
    if unknown:
        return "open"
    try:
        return "yes" if bool(safe_eval(clause, facts)) else "no"
    except (UnknownFact, ExpressionSecurityError):
        return "invalid"


def _classify(rule: ChargeRule, facts: Mapping[str, Any]) -> str:
    """firm, open, no, or skip."""
    states = [_clause_state(clause, facts) for clause in clauses(rule.applies_when)]
    if any(state == "no" for state in states):
        return "no"
    if any(state in {"missing", "invalid"} for state in states):
        return "skip"
    if any(state == "open" for state in states):
        return "open"
    return "firm"


def _pick(
    candidates: Sequence[tuple[ChargeRule, bool]],
) -> tuple[ChargeRule | None, AmbiguousRules | None]:
    if not candidates:
        return None, None
    chosen = list(candidates)
    if any(exact for _, exact in chosen):
        chosen = [(rule, exact) for rule, exact in chosen if exact]
    if len(chosen) > 1:
        ids = [rule.id for rule, _ in chosen]
        return None, AmbiguousRules(chosen[0][0].charge_type, ids)
    return chosen[0][0], None


def select_rule(
    rules: Sequence[ChargeRule],
    port: str,
    facts: Mapping[str, Any],
) -> tuple[ChargeRule | None, list[str], AmbiguousRules | None]:
    """Select a single applicable rule for a charge type.

    Returns (rule, assumptions, ambiguity_error).
    """
    assumptions: list[str] = []
    firm: list[tuple[ChargeRule, bool]] = []
    open_rules: list[tuple[ChargeRule, bool]] = []
    for rule in rules:
        matches, exact = _port_matches(rule.ports, port)
        if not matches:
            continue
        kind = _classify(rule, facts)
        if kind == "no":
            continue
        if kind == "skip":
            try:
                needed = referenced_names(rule.applies_when)
            except ExpressionSecurityError as exc:
                assumptions.append(f"Skipped rule '{rule.id}': {exc}")
                continue
            missing = (needed & set(FACT_DESCRIPTIONS)) - set(facts)
            assumptions.append(
                f"Skipped rule '{rule.id}': unknown fact in applies_when {sorted(missing) or ['invalid expression']}"
            )
            continue
        if kind == "open":
            open_rules.append((rule, exact))
            continue
        firm.append((rule, exact))

    if firm:
        selected, ambiguous = _pick(firm)
        return selected, assumptions, ambiguous

    residual = [(rule, exact) for rule, exact in open_rules if is_residual(rule)]
    pool = residual or (open_rules if len(open_rules) == 1 else [])
    if pool:
        assumptions.append(
            "Applied the ordinary/other row; conditions named facts outside the vessel vocabulary"
        )
    selected, ambiguous = _pick(pool)
    return selected, assumptions, ambiguous


def calculate_all(
    rulebook: Rulebook,
    port: str,
    facts: Mapping[str, Any],
    vat_rate: float = 0.0,
    charge_types: Sequence[str] | None = None,
) -> CalculationReport:
    """Select and calculate all charges for a port."""
    if charge_types is None:
        charge_types = sorted({r.charge_type for r in rulebook.rules})

    items: list[ChargeResult] = []
    report_assumptions: list[str] = []
    warnings: list[str] = []

    for charge_type in charge_types:
        rules = [normalize_rule(rule) for rule in rulebook.by_charge_type(charge_type)]
        selected, assumptions, ambiguous = select_rule(rules, port, facts)
        report_assumptions.extend(assumptions)
        if ambiguous is not None:
            items.append(
                ChargeResult(
                    charge_type=charge_type,
                    status="error",
                    assumptions=assumptions,
                    error=str(ambiguous),
                )
            )
            continue
        if selected is None:
            items.append(
                ChargeResult(
                    charge_type=charge_type,
                    status="not_found",
                    assumptions=assumptions,
                    amount=None,
                )
            )
            continue
        result = calculate_rule(selected, facts)
        result.assumptions = list(dict.fromkeys([*assumptions, *result.assumptions]))
        if result.status == "ok" and result.amount is not None and vat_rate:
            vat_amount = money(result.amount * vat_rate)
            result.vat_amount = vat_amount
            result.amount_incl_vat = money(result.amount + vat_amount)
        items.append(result)

    ok_amounts = [i.amount for i in items if i.status == "ok" and i.amount is not None]
    total = money(sum(ok_amounts)) if ok_amounts else None
    total_incl = None
    if total is not None and vat_rate:
        total_incl = money(
            sum(i.amount_incl_vat or i.amount or 0.0 for i in items if i.status == "ok")
        )

    currency = next((r.currency for r in rulebook.rules), "ZAR")
    return CalculationReport(
        port=port,
        currency=currency,
        items=items,
        total=total,
        total_incl_vat=total_incl,
        vat_rate=vat_rate,
        assumptions=report_assumptions,
        warnings=warnings,
    )
