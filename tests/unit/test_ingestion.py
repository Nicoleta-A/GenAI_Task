"""Ingestion / BM25 recall tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tariff_agent.ingestion.index import BM25Retriever
from tariff_agent.ingestion.pdf_pages import _split_spread, load_pages

ROOT = Path(__file__).resolve().parents[2]
PDF = ROOT / "data" / "Port_Tariff.pdf"
CONFIG = ROOT / "config" / "charges.yaml"

# Printed page numbers from the assessment gold mapping (tests only).
GOLD_PAGES = {
    "light_dues": 9,
    "vts": 11,
    "pilotage": 13,
    "towage": 15,
    "berthing_services": 18,
    "running_of_lines": 19,
    "port_dues": 21,
}


@pytest.fixture(scope="module")
def pages(tmp_path_factory: pytest.TempPathFactory) -> list:
    if not PDF.exists():
        pytest.skip("tariff PDF missing")
    cache = tmp_path_factory.mktemp("pages")
    return load_pages(PDF, cache_dir=cache)


def test_pages_have_text_and_bytes(pages: list) -> None:
    assert len(pages) > 0
    printed = [page.printed_number for page in pages]
    assert len(printed) == len(set(printed))
    for page in pages:
        assert page.text
        assert len(page.text) > 20
        assert page.pdf_bytes.startswith(b"%PDF")


def test_split_ignores_unindented_contents_numbers() -> None:
    """Contents and table cells are bare numbers. Headers are indented."""
    text = "\n".join(
        [
            "contents",
            "9",
            "10",
            "11",
            "                                          15",
            "real left page body with enough words to keep",
            "  16",
            "real right page body",
        ]
    )
    pages = _split_spread(0, text, b"%PDF-1.4")
    numbers = [page.printed_number for page in pages]
    assert numbers == [15, 16]
    assert all(len(page.text) > 5 for page in pages)


def test_recall_at_5(pages: list) -> None:
    retriever = BM25Retriever(pages)
    charge_types = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["charge_types"]
    misses: list[str] = []
    for charge_type, seeds in charge_types.items():
        gold = GOLD_PAGES[charge_type]
        hit = False
        for query in seeds:
            top = retriever.search(query, k=5)
            printed = [p.printed_number for p in top]
            if gold in printed:
                hit = True
                break
        # Also try charge_type tokens
        if not hit:
            top = retriever.search(charge_type.replace("_", " "), k=5)
            if gold in [p.printed_number for p in top]:
                hit = True
        if not hit:
            misses.append(f"{charge_type} expected printed={gold}")
    assert not misses, f"recall@5 failures: {misses}"
