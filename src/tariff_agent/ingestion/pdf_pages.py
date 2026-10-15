"""PDF page extraction with printed-number heuristics."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf

_pdf: Any = pymupdf

# Header page numbers in this book are indented (left header ~40 spaces, right header 2).
# Bare lines ("9", "1") are contents entries or table cells, not page headers.
_PRINTED_LINE = re.compile(r"(?m)^[ \t]{2,}(\d{1,3})[ \t]*$")
_SPLIT_VERSION = 2


@dataclass(frozen=True)
class Page:
    index: int
    printed_number: int
    text: str
    pdf_bytes: bytes


def pdf_sha256(path: Path) -> str:
    """
    Calculate the SHA-256 hash of a PDF file.
    """
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _split_spread(index: int, text: str, pdf_bytes: bytes) -> list[Page]:
    """Split a PDF page that may contain two printed pages (common in this book)."""
    matches = list(_PRINTED_LINE.finditer(text))
    # Keep numbers that look like book page numbers (not tiny footnote codes).
    candidates: list[tuple[int, int]] = []
    for match in matches:
        value = int(match.group(1))
        if 1 <= value <= 200:
            candidates.append((match.start(), value))

    # Deduplicate consecutive identical numbers; keep ascending sequences.
    filtered: list[tuple[int, int]] = []
    for start, value in candidates:
        if filtered and filtered[-1][1] == value:
            continue
        # Prefer numbers that increase like 15 then 16 on the same PDF page.
        if filtered and value < filtered[-1][1]:
            # TOC / TOC-like noise — keep only if near start and we have nothing yet.
            if filtered[-1][0] > 200:
                continue
        filtered.append((start, value))

    # Keep at most two ascending printed numbers typical of a spread.
    ascending: list[tuple[int, int]] = []
    for start, value in filtered:
        if not ascending or value == ascending[-1][1] + 1 or (
            len(ascending) == 1 and value > ascending[-1][1]
        ):
            ascending.append((start, value))
        elif not ascending:
            ascending.append((start, value))
    if len(ascending) > 2:
        # Prefer the first two that form n, n+1
        pair = None
        for i in range(len(ascending) - 1):
            if ascending[i + 1][1] == ascending[i][1] + 1:
                pair = [ascending[i], ascending[i + 1]]
                break
        ascending = pair or ascending[:2]

    if not ascending:
        return [Page(index=index, printed_number=index + 1, text=text, pdf_bytes=pdf_bytes)]

    pages: list[Page] = []
    for i, (start, printed) in enumerate(ascending):
        end = ascending[i + 1][0] if i + 1 < len(ascending) else len(text)
        chunk = text[start:end].strip()
        if not chunk:
            chunk = text
        pages.append(
            Page(index=index, printed_number=printed, text=chunk, pdf_bytes=pdf_bytes)
        )
    return pages


def load_pages(pdf_path: Path, cache_dir: Path | None = None) -> list[Page]:
    """Load logical printed pages, optionally caching by PDF hash."""
    pdf_path = Path(pdf_path)
    pdf_hash = pdf_sha256(pdf_path)
    if cache_dir is not None:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        meta_path = cache_dir / f"{pdf_hash}.json"
        pages_dir = cache_dir / pdf_hash
        meta: dict[str, Any] | None = None
        if meta_path.exists() and pages_dir.exists():
            loaded_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if loaded_meta.get("split_version") == _SPLIT_VERSION:
                meta = loaded_meta
        if meta is not None:
            pages: list[Page] = []
            for entry in meta["pages"]:
                pdf_bytes = (pages_dir / f"{entry['index']}.pdf").read_bytes()
                pages.append(
                    Page(
                        index=entry["index"],
                        printed_number=entry["printed_number"],
                        text=entry["text"],
                        pdf_bytes=pdf_bytes,
                    )
                )
            return pages

    doc = _pdf.open(pdf_path)
    loaded: list[Page] = []
    for index in range(len(doc)):
        page = doc[index]
        text = page.get_text()
        single = _pdf.open()
        single.insert_pdf(doc, from_page=index, to_page=index)
        pdf_bytes = single.tobytes()
        single.close()
        loaded.extend(_split_spread(index, text, pdf_bytes))

    if cache_dir is not None:
        pages_dir = Path(cache_dir) / pdf_hash
        pages_dir.mkdir(parents=True, exist_ok=True)
        written: set[int] = set()
        for p in loaded:
            if p.index not in written:
                (pages_dir / f"{p.index}.pdf").write_bytes(p.pdf_bytes)
                written.add(p.index)
        meta = {
            "split_version": _SPLIT_VERSION,
            "pages": [
                {
                    "index": p.index,
                    "printed_number": p.printed_number,
                    "text": p.text,
                }
                for p in loaded
            ]
        }
        meta_path = Path(cache_dir) / f"{pdf_hash}.json"
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

    doc.close()
    return loaded


def pages_by_printed_map(pages: list[Page]) -> dict[int, Page]:
    return {p.printed_number: p for p in pages}
