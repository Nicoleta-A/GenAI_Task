"""Page locator: BM25 over seed queries. No LLM calls."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from tariff_agent.ingestion.index import Retriever


@dataclass
class LocateResult:
    charge_type: str
    pages: list[int]
    reason: str
    warnings: list[str] = field(default_factory=list)
    steps: int = 0


def locate_charge_pages(
    retriever: Retriever,
    charge_type: str,
    seed_queries: Sequence[str],
    *,
    k: int = 5,
) -> LocateResult:
    """Return up to ``k`` printed page numbers from BM25 over the seed queries."""
    queries = [q for q in seed_queries if q.strip()] or [charge_type.replace("_", " ")]
    scores: dict[int, float] = {}
    for query in queries:
        for rank, page in enumerate(retriever.search(query, k=k)):
            number = page.printed_number
            scores[number] = scores.get(number, 0.0) + float(k - rank)
    ordered = sorted(scores, key=lambda number: scores[number], reverse=True)
    return LocateResult(charge_type=charge_type, pages=ordered[:k], reason="bm25")
