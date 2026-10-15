"""Rewrite extracted formulas into expressions the calculator can run."""

from __future__ import annotations

import re

from tariff_agent.domain.rules import ChargeRule

_AND = re.compile(r"\s*&&\s*")
_OR = re.compile(r"\s*\|\|\s*")
_TRUE = re.compile(r"\btrue\b")
_FALSE = re.compile(r"\bfalse\b")
_AND_SPLIT = re.compile(r"\band\b")

# Residual rows the extractor labels when it cannot express "everyone else".
_RESIDUAL = ("other", "general", "commercial", "ordinary")
_SPECIAL = ("outside", "delay", "surcharge")


def normalize_expr(expr: str) -> str:
    """Turn JS-ish booleans into Python. ``true`` is not a vessel fact."""
    text = (expr or "").strip() or "True"
    text = _AND.sub(" and ", text)
    text = _OR.sub(" or ", text)
    text = _TRUE.sub("True", text)
    text = _FALSE.sub("False", text)
    return text


def clauses(expr: str) -> list[str]:
    return [part.strip() for part in _AND_SPLIT.split(normalize_expr(expr)) if part.strip()]


def is_residual(rule: ChargeRule) -> bool:
    """True for the ordinary/other/general row, not a surcharge or delay row."""
    text = f"{rule.id} {rule.applies_when}".casefold()
    if any(word in text for word in _SPECIAL):
        return False
    return any(word in text for word in _RESIDUAL)


def normalize_rule(rule: ChargeRule) -> ChargeRule:
    """Fix operators, boolean literals, and per-service multipliers."""
    data = rule.model_dump()
    data["applies_when"] = normalize_expr(rule.applies_when)
    for band in data["bands"]:
        band["when"] = normalize_expr(str(band["when"]))
        for component in band["components"]:
            times = normalize_expr(str(component.get("times") or "1"))
            label = str(component.get("label") or "")
            if times in {"1", "1.0"} and _charged_per_service(rule, label):
                times = "num_operations"
            component["times"] = times
    for modifier in data["modifiers"]:
        modifier["when"] = normalize_expr(str(modifier["when"]))
    return ChargeRule.model_validate(data)


def _charged_per_service(rule: ChargeRule, label: str) -> bool:
    blob = " ".join([rule.source_quote, label, *rule.assumptions]).casefold()
    return "per service" in blob
