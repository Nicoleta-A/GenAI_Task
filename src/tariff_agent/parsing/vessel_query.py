"""Parse vessel queries (JSON fast-path or free text via LLM)."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ValidationError

from tariff_agent.domain.exceptions import MissingFacts
from tariff_agent.domain.vessel import FACT_DESCRIPTIONS, VesselProfile
from tariff_agent.llm.client import LLMClient

REQUIRED_FACTS = ("gt", "num_operations", "days_alongside")


class _ParsedVessel(BaseModel):
    name: str | None = None
    gt: float | None = None
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
    num_operations: int | None = None
    days_alongside: float | None = None
    arrival_time: str | None = None
    departure_time: str | None = None


def _load_prompt() -> str:
    path = Path(__file__).resolve().parents[1] / "extraction" / "prompts" / "vessel_parser.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "Parse vessel facts into the schema. Do not invent required fields."


def parse_vessel_query(text: str, client: LLMClient | None = None) -> VesselProfile:
    """Parse JSON or free-text vessel description into VesselProfile."""
    stripped = text.strip()
    if stripped.startswith("{"):
        payload = json.loads(stripped)
        if "technical_specs" in payload or "vessel_metadata" in payload:
            profile = VesselProfile.from_json(payload)
        else:
            profile = VesselProfile.model_validate(payload)
        _ensure_required(profile)
        return profile

    if client is None:
        raise MissingFacts(list(REQUIRED_FACTS))

    prompt = "\n\n".join(
        [
            _load_prompt(),
            f"Fact vocabulary: {json.dumps(FACT_DESCRIPTIONS)}",
            f"User text:\n{stripped}",
        ]
    )
    response = client.generate(prompt, schema=_ParsedVessel)
    parsed: _ParsedVessel
    if isinstance(response.parsed, _ParsedVessel):
        parsed = response.parsed
    else:
        parsed = _ParsedVessel.model_validate_json(response.text)

    missing = [name for name in REQUIRED_FACTS if getattr(parsed, name) is None]
    if missing:
        raise MissingFacts(missing)

    data = parsed.model_dump(exclude_none=True)
    try:
        profile = VesselProfile.model_validate(data)
    except ValidationError as exc:
        names: list[str] = []
        for err in exc.errors():
            loc = err.get("loc") or ()
            if loc:
                names.append(str(loc[0]))
        raise MissingFacts(names or ["unknown"]) from exc
    _ensure_required(profile)
    return profile


def _ensure_required(profile: VesselProfile) -> None:
    facts = profile.facts()
    missing = [name for name in REQUIRED_FACTS if name not in facts]
    if missing:
        raise MissingFacts(missing)


def load_vessel_file(path: Path) -> VesselProfile:
    return parse_vessel_query(path.read_text(encoding="utf-8"))
