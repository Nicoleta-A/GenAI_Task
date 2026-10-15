"""Compare extracted rulebooks against gold."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tariff_agent.domain.rules import ChargeRule, Rulebook


@dataclass
class FieldMismatch:
    rule_id: str
    field: str
    expected: Any
    actual: Any


@dataclass
class CompareResult:
    missing_ids: list[str] = field(default_factory=list)
    mismatches: list[FieldMismatch] = field(default_factory=list)
    extra_ids: list[str] = field(default_factory=list)
    field_accuracy: float = 1.0

    @property
    def ok(self) -> bool:
        return not self.missing_ids and not self.mismatches


_COMPARE_FIELDS = (
    "charge_type",
    "ports",
    "applies_when",
    "minimum",
    "currency",
    "source_page",
)


def _band_signature(rule: ChargeRule) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for band in rule.bands:
        comps = [
            {
                "rate": c.rate,
                "per": c.per,
                "unit_size": c.unit_size,
                "rounding": c.rounding,
                "over": c.over,
                "times": c.times,
            }
            for c in band.components
        ]
        out.append({"when": band.when, "components": comps})
    return out


def compare_rulebooks(gold: Rulebook, extracted: Rulebook) -> CompareResult:
    by_id = {r.id: r for r in extracted.rules}
    gold_ids = {r.id for r in gold.rules}
    extracted_ids = set(by_id)
    result = CompareResult(
        missing_ids=sorted(gold_ids - extracted_ids),
        extra_ids=sorted(extracted_ids - gold_ids),
    )
    checks = 0
    hits = 0
    for grule in gold.rules:
        erule = by_id.get(grule.id)
        if erule is None:
            continue
        for field_name in _COMPARE_FIELDS:
            checks += 1
            ev = getattr(grule, field_name)
            av = getattr(erule, field_name)
            if field_name == "ports":
                ev = sorted(p.casefold() for p in ev)
                av = sorted(p.casefold() for p in av)
            if ev == av:
                hits += 1
            else:
                result.mismatches.append(FieldMismatch(grule.id, field_name, ev, av))
        checks += 1
        if _band_signature(grule) == _band_signature(erule):
            hits += 1
        else:
            result.mismatches.append(
                FieldMismatch(grule.id, "bands", _band_signature(grule), _band_signature(erule))
            )
    result.field_accuracy = (hits / checks) if checks else 1.0
    return result
