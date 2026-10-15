"""BM25 locator tests — no LLM."""

from __future__ import annotations

from tariff_agent.extraction.locator import locate_charge_pages
from tariff_agent.ingestion.index import BM25Retriever
from tariff_agent.ingestion.pdf_pages import Page


def _pages() -> list[Page]:
    texts = {
        9: "Light dues schedule for vessels per 100 tons",
        11: "Vessel traffic services charges",
        15: "Towage dues table by gross tonnage",
    }
    return [
        Page(index=printed, printed_number=printed, text=text, pdf_bytes=b"%PDF-1.4 fake")
        for printed, text in texts.items()
    ]


def test_locator_returns_matching_page() -> None:
    pages = _pages()
    result = locate_charge_pages(BM25Retriever(pages), "light_dues", ["light dues"])
    assert 9 in result.pages
    assert result.reason == "bm25"
    assert result.steps == 0


def test_locator_unions_later_seed_queries() -> None:
    pages = [
        Page(index=0, printed_number=1, text="towage contents index " * 30, pdf_bytes=b"x"),
        Page(index=1, printed_number=15, text="tugs craft assistance dues table", pdf_bytes=b"x"),
    ]
    result = locate_charge_pages(BM25Retriever(pages), "towage", ["towage", "tugs"], k=2)
    assert 15 in result.pages


def test_locator_caps_results() -> None:
    pages = _pages()
    result = locate_charge_pages(BM25Retriever(pages), "dues", ["dues"], k=1)
    assert len(result.pages) == 1
