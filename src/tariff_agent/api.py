"""FastAPI HTTP API."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from tariff_agent.domain.exceptions import LLMOutputError, MissingFacts
from tariff_agent.domain.results import CalculationReport
from tariff_agent.domain.vessel import VesselProfile
from tariff_agent.llm.client import build_llm_client
from tariff_agent.service import TariffService
from tariff_agent.store import RulebookStore

load_dotenv()


class CalculateRequest(BaseModel):
    rulebook_id: str
    port: str
    vessel: dict[str, Any] | None = None
    query: str | None = None
    vat_rate: float = 0.0


def _default_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_service() -> TariffService:
    """Production service wired like ``cli._service`` (cache, store, charges, pages)."""
    root = _default_root()
    cache = root / "data" / "llm_cache"
    store = RulebookStore(root / "data" / "rulebooks")
    llm = build_llm_client(cache_dir=cache)
    return TariffService(
        llm=llm,
        store=store,
        charges_config=root / "config" / "charges.yaml",
        page_cache_dir=root / "data" / "page_cache",
    )


router = APIRouter()


def get_service(request: Request) -> Any:
    svc = getattr(request.app.state, "service", None)
    if svc is None:
        raise HTTPException(status_code=500, detail="Service not configured")
    return svc


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/rulebooks")
async def upload_rulebook(
    pdf: UploadFile = File(...),
    svc: TariffService = Depends(get_service),
) -> dict[str, Any]:
    suffix = Path(pdf.filename or "tariff.pdf").suffix or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await pdf.read())
        tmp_path = Path(tmp.name)
    try:
        rulebook_id, rulebook, warnings = svc.build_rulebook(tmp_path, force=True)
        return {
            "rulebook_id": rulebook_id,
            "n_rules": len(rulebook.rules),
            "warnings": warnings,
        }
    except LLMOutputError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)


@router.post("/calculate", response_model=CalculationReport)
def calculate(
    body: CalculateRequest,
    svc: TariffService = Depends(get_service),
) -> CalculationReport:
    rulebook = svc.store.load_id(body.rulebook_id)
    if rulebook is None:
        raise HTTPException(status_code=404, detail=f"Unknown rulebook_id {body.rulebook_id}")
    try:
        if body.vessel is not None:
            vessel: VesselProfile | str | dict[str, Any] = body.vessel
        elif body.query is not None:
            vessel = body.query
        else:
            raise HTTPException(status_code=422, detail="Provide vessel or query")
        return svc.calculate_with_rulebook(rulebook, body.port, vessel, vat_rate=body.vat_rate)
    except MissingFacts as exc:
        raise HTTPException(status_code=422, detail={"missing": exc.names}) from exc
    except LLMOutputError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def create_app(service: TariffService | None = None) -> FastAPI:
    app = FastAPI(title="Port Tariff Agent", version="0.1.0")
    app.state.service = service
    app.include_router(router)
    return app


app = create_app(_default_service())
