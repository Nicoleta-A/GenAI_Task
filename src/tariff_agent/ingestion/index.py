"""BM25 retriever over tariff pages."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Protocol

from rank_bm25 import BM25Okapi

from tariff_agent.ingestion.pdf_pages import Page

_TOKEN = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


class Retriever(Protocol):
    def search(self, query: str, k: int = 5) -> list[Page]:
        """Return top-k pages for a query."""


class BM25Retriever:
    def __init__(self, pages: Sequence[Page]) -> None:
        self._pages = list(pages)
        corpus = [tokenize(p.text) for p in self._pages]
        self._bm25 = BM25Okapi(corpus) if corpus else None

    def search(self, query: str, k: int = 5) -> list[Page]:
        if not self._pages or self._bm25 is None:
            return []
        scores = self._bm25.get_scores(tokenize(query))
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        top = ranked[: max(k, 0)]
        return [self._pages[i] for i in top]
