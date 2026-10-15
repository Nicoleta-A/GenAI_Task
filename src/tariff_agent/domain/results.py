"""Calculation result types."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Citation(BaseModel):
    page: int
    quote: str


class ChargeResult(BaseModel):
    charge_type: str
    status: Literal["ok", "not_found", "error"]
    amount: float | None = None
    currency: str | None = None
    breakdown: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    citation: Citation | None = None
    rule_id: str | None = None
    error: str | None = None
    vat_amount: float | None = None
    amount_incl_vat: float | None = None


class CalculationReport(BaseModel):
    port: str
    currency: str = "ZAR"
    items: list[ChargeResult] = Field(default_factory=list)
    total: float | None = None
    total_incl_vat: float | None = None
    vat_rate: float = 0.0
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def by_type(self) -> dict[str, ChargeResult]:
        return {item.charge_type: item for item in self.items}
