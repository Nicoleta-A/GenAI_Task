"""Money rounding helpers."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def money(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
