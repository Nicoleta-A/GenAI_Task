"""Rulebook persistence keyed by PDF hash."""

from __future__ import annotations

from pathlib import Path

from tariff_agent.domain.rules import Rulebook
from tariff_agent.ingestion.pdf_pages import pdf_sha256


class RulebookStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, pdf_path: Path) -> Path:
        return self.root / f"{pdf_sha256(pdf_path)}.json"

    def load(self, pdf_path: Path) -> Rulebook | None:
        path = self.path_for(pdf_path)
        if not path.exists():
            return None
        return Rulebook.model_validate_json(path.read_text(encoding="utf-8"))

    def load_id(self, rulebook_id: str) -> Rulebook | None:
        path = self.root / f"{rulebook_id}.json"
        if not path.exists():
            return None
        return Rulebook.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, pdf_path: Path, rulebook: Rulebook) -> str:
        path = self.path_for(pdf_path)
        path.write_text(rulebook.model_dump_json(indent=2), encoding="utf-8")
        return path.stem

    def save_id(self, rulebook_id: str, rulebook: Rulebook) -> Path:
        path = self.root / f"{rulebook_id}.json"
        path.write_text(rulebook.model_dump_json(indent=2), encoding="utf-8")
        return path
