"""Vessel profile and fact vocabulary for expression evaluation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

FACT_DESCRIPTIONS: dict[str, str] = {
    "gt": "Gross tonnage (GT).",
    "nt": "Net tonnage (NT).",
    "dwt": "Deadweight tonnage.",
    "loa": "Length overall in metres.",
    "beam": "Beam in metres.",
    "moulded_depth": "Moulded depth in metres.",
    "lbp": "Length between perpendiculars in metres.",
    "draft": "Maximum draft in metres (summer/winter/tropical max).",
    "suez_gt": "Suez Canal gross tonnage, if known.",
    "suez_nt": "Suez Canal net tonnage, if known.",
    "vessel_type": "Vessel type string (e.g. Bulk Carrier).",
    "flag": "Flag / registry string.",
    "built_year": "Year built.",
    "cargo_mt": "Cargo quantity in metric tonnes.",
    "activity": "Operational activity description.",
    "num_holds": "Number of holds.",
    "num_operations": "Port service count (typically entering + leaving = 2).",
    "days_alongside": "Fractional days used for per-24h time-based dues.",
    "arrival_time": "Arrival datetime ISO string, if known.",
    "departure_time": "Departure datetime ISO string, if known.",
    "name": "Vessel name.",
}


class VesselProfile(BaseModel):
    """Normalized vessel facts used by the calculator and prompts."""

    name: str | None = None
    gt: float
    nt: float | None = None
    dwt: float | None = None
    loa: float | None = None
    beam: float | None = None
    moulded_depth: float | None = None
    lbp: float | None = None
    draft: float | None = None
    suez_gt: float | None = None
    suez_nt: float | None = None
    vessel_type: str | None = None
    flag: str | None = None
    built_year: int | None = None
    cargo_mt: float | None = None
    activity: str | None = None
    num_holds: int | None = None
    num_operations: int = Field(default=2, ge=0)
    days_alongside: float = Field(ge=0)
    arrival_time: datetime | None = None
    departure_time: datetime | None = None

    @field_validator("gt")
    @classmethod
    def _gt_non_negative(cls, value: float) -> float:
        if value < 0:
            msg = "gt must be non-negative"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _require_core_facts(self) -> VesselProfile:
        if self.gt is None:  # pragma: no cover - pydantic required field
            msg = "gt is required"
            raise ValueError(msg)
        return self

    def facts(self) -> dict[str, Any]:
        """Return evaluator variables (None values omitted)."""
        data: dict[str, Any] = {
            "gt": self.gt,
            "num_operations": self.num_operations,
            "days_alongside": self.days_alongside,
        }
        optional: dict[str, Any] = {
            "nt": self.nt,
            "dwt": self.dwt,
            "loa": self.loa,
            "beam": self.beam,
            "moulded_depth": self.moulded_depth,
            "lbp": self.lbp,
            "draft": self.draft,
            "suez_gt": self.suez_gt,
            "suez_nt": self.suez_nt,
            "vessel_type": self.vessel_type,
            "flag": self.flag,
            "built_year": self.built_year,
            "cargo_mt": self.cargo_mt,
            "activity": self.activity,
            "num_holds": self.num_holds,
            "name": self.name,
        }
        for key, value in optional.items():
            if value is not None:
                data[key] = value
        if self.arrival_time is not None:
            data["arrival_time"] = self.arrival_time.isoformat()
        if self.departure_time is not None:
            data["departure_time"] = self.departure_time.isoformat()
        return data

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> VesselProfile:
        """Map the assessment nested JSON schema to a VesselProfile."""
        meta = payload.get("vessel_metadata") or {}
        specs = payload.get("technical_specs") or {}
        ops = payload.get("operational_data") or {}

        # Flat schema fallback (already normalized).
        if "gross_tonnage" not in specs and "gt" in payload:
            return cls.model_validate(payload)

        draft_list = specs.get("draft_sw_s_w_t") or []
        draft = max(draft_list) if draft_list else None

        return cls(
            name=meta.get("name"),
            built_year=meta.get("built_year"),
            flag=meta.get("flag"),
            vessel_type=specs.get("type"),
            dwt=_as_float(specs.get("dwt")),
            gt=float(specs["gross_tonnage"]),
            nt=_as_float(specs.get("net_tonnage")),
            loa=_as_float(specs.get("loa_meters")),
            beam=_as_float(specs.get("beam_meters")),
            moulded_depth=_as_float(specs.get("moulded_depth_meters")),
            lbp=_as_float(specs.get("lbp_meters")),
            draft=_as_float(draft),
            suez_gt=_as_float(specs.get("suez_gt")),
            suez_nt=_as_float(specs.get("suez_nt")),
            cargo_mt=_as_float(ops.get("cargo_quantity_mt")),
            days_alongside=float(ops["days_alongside"]),
            arrival_time=ops.get("arrival_time"),
            departure_time=ops.get("departure_time"),
            activity=ops.get("activity"),
            num_operations=int(ops.get("num_operations", 2)),
            num_holds=_as_int(ops.get("num_holds")),
        )


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)
