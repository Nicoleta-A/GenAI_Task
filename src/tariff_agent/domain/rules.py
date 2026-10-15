"""Charge rule schema (port-agnostic rulebook)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Component(BaseModel):
    label: str
    rate: float
    per: str | None = None
    unit_size: float = 1
    rounding: Literal["ceil", "none"] = "ceil"
    over: float = 0
    times: str = "1"


class Band(BaseModel):
    when: str
    components: list[Component]


class Modifier(BaseModel):
    label: str
    when: str
    factor: float


class ChargeRule(BaseModel):
    id: str
    charge_type: str
    ports: list[str]
    applies_when: str = "True"
    bands: list[Band]
    modifiers: list[Modifier] = Field(default_factory=list)
    minimum: float | None = None
    currency: str = "ZAR"
    source_page: int
    source_quote: str
    assumptions: list[str] = Field(default_factory=list)


class Rulebook(BaseModel):
    document: str = ""
    rules: list[ChargeRule] = Field(default_factory=list)

    def by_charge_type(self, charge_type: str) -> list[ChargeRule]:
        return [r for r in self.rules if r.charge_type == charge_type]

    def ports_mentioned(self) -> list[str]:
        found: set[str] = set()
        for rule in self.rules:
            for port in rule.ports:
                if port != "*":
                    found.add(port)
        return sorted(found)
