"""Orchestrator: locate → extract → validate → calculate."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from tariff_agent.domain.exceptions import LLMOutputError
from tariff_agent.domain.results import CalculationReport
from tariff_agent.domain.rules import Rulebook
from tariff_agent.domain.vessel import VesselProfile
from tariff_agent.engine.selector import calculate_all
from tariff_agent.extraction.extractor import build_rulebook
from tariff_agent.extraction.locator import locate_charge_pages
from tariff_agent.ingestion.index import BM25Retriever
from tariff_agent.ingestion.pdf_pages import load_pages, pages_by_printed_map
from tariff_agent.llm.client import LLMClient
from tariff_agent.parsing.vessel_query import parse_vessel_query
from tariff_agent.store import RulebookStore


def load_charge_config(path: Path) -> dict[str, list[str]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw = data.get("charge_types", {})
    return {str(k): [str(x) for x in v] for k, v in raw.items()}


class TariffService:
    def __init__(
        self,
        llm: LLMClient,
        store: RulebookStore,
        charges_config: Path,
        page_cache_dir: Path | None = None,
    ) -> None:
        self.llm = llm
        self.store = store
        self.charges_config = Path(charges_config)
        self.page_cache_dir = page_cache_dir

    def build_rulebook(self, pdf_path: Path, *, force: bool = False) -> tuple[str, Rulebook, list[str]]:
        pdf_path = Path(pdf_path)
        cached = self.store.load(pdf_path)
        if not force and cached is not None:
            return self.store.path_for(pdf_path).stem, cached, ["loaded from cache"]

        pages = load_pages(pdf_path, cache_dir=self.page_cache_dir)
        retriever = BM25Retriever(pages)
        by_printed = pages_by_printed_map(pages)
        charge_types = load_charge_config(self.charges_config)
        located: dict[str, list[Any]] = {}
        warnings: list[str] = []
        for charge_type, seeds in charge_types.items():
            result = locate_charge_pages(retriever, charge_type, seeds)
            warnings.extend(result.warnings)
            located[charge_type] = [by_printed[p] for p in result.pages if p in by_printed]
            if not located[charge_type] and result.pages:
                warnings.append(f"{charge_type}: located pages not in index: {result.pages}")

        rulebook, extract_warnings = build_rulebook(self.llm, located, document=pdf_path.name)
        warnings.extend(extract_warnings)
        if not rulebook.rules:
            if cached is not None:
                warnings.append("extraction produced no rules; kept cached rulebook")
                return self.store.path_for(pdf_path).stem, cached, warnings
            detail = "; ".join(warnings) or "extraction produced no rules"
            raise LLMOutputError(detail)
        rulebook_id = self.store.save(pdf_path, rulebook)
        return rulebook_id, rulebook, warnings

    def calculate(
        self,
        pdf_path: Path,
        port: str,
        vessel: VesselProfile | str | dict[str, Any],
        vat_rate: float = 0.0,
        *,
        force_rebuild: bool = False,
    ) -> CalculationReport:
        _, rulebook, warnings = self.build_rulebook(pdf_path, force=force_rebuild)
        profile = self._coerce_vessel(vessel)
        report = calculate_all(rulebook, port, profile.facts(), vat_rate=vat_rate)
        report.warnings = list(dict.fromkeys([*report.warnings, *warnings]))
        known_ports = rulebook.ports_mentioned()
        if port not in known_ports and not any(
            p.casefold() == port.casefold() for p in known_ports
        ):
            # Still may match "*" rules; note available ports for the caller.
            report.warnings.append(
                f"Port {port!r} not named in rulebook; available: {known_ports or ['(wildcard only)']}"
            )
        return report

    def calculate_with_rulebook(
        self,
        rulebook: Rulebook,
        port: str,
        vessel: VesselProfile | str | dict[str, Any],
        vat_rate: float = 0.0,
    ) -> CalculationReport:
        profile = self._coerce_vessel(vessel)
        return calculate_all(rulebook, port, profile.facts(), vat_rate=vat_rate)

    def _coerce_vessel(self, vessel: VesselProfile | str | dict[str, Any]) -> VesselProfile:
        if isinstance(vessel, VesselProfile):
            return vessel
        if isinstance(vessel, dict):
            if "technical_specs" in vessel:
                return VesselProfile.from_json(vessel)
            return VesselProfile.model_validate(vessel)
        return parse_vessel_query(vessel, client=self.llm)
