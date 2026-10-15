"""Guard: no tariff-specific knowledge may live under src/."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"

# Port names from the assessment tariff (must not appear in source).
FORBIDDEN_PORTS: tuple[str, ...] = (
    "Durban",
    "Richards Bay",
    "Cape Town",
    "Saldanha",
    "Ngqura",
    "East London",
    "Mossel Bay",
    "Port Elizabeth",
)

# Distinctive rate literals from tests/fixtures/durban_gold_rulebook.json
# (and related gold values). Kept only in tests — never in src/.
FORBIDDEN_RATES: tuple[str, ...] = (
    "117.08",
    "192.73",
    "57.79",
    "0.65",
    "235.52",
    "0.54",
    "18608.61",
    "9.72",
    "8140.00",
    "12633.99",
    "268.99",
    "38494.51",
    "84.95",
    "73118.07",
    "32.24",
    "93548.13",
    "23.65",
    "2801.91",
    "13.68",
    "1654.56",
    "30960.46",
    "10.93",
    "79999.76",
    "30.11",
    "3175.89",
    "13.46",
)

FORBIDDEN_ORGS: tuple[str, ...] = ("Transnet",)

_TEXT_SUFFIXES = {".py", ".md", ".txt", ".yaml", ".yml", ".json", ".toml"}


def _iter_src_files() -> list[Path]:
    if not SRC_ROOT.exists():
        return []
    files: list[Path] = []
    for path in SRC_ROOT.rglob("*"):
        if path.is_file() and path.suffix.lower() in _TEXT_SUFFIXES:
            files.append(path)
    return files


@pytest.mark.parametrize("needle", FORBIDDEN_PORTS + FORBIDDEN_ORGS)
def test_no_forbidden_names_in_src(needle: str) -> None:
    pattern = re.compile(re.escape(needle), re.IGNORECASE)
    hits: list[str] = []
    for path in _iter_src_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        if pattern.search(text):
            hits.append(str(path.relative_to(SRC_ROOT.parent)))
    assert not hits, f"{needle!r} found in: {hits}"


@pytest.mark.parametrize("rate", FORBIDDEN_RATES)
def test_no_forbidden_rates_in_src(rate: str) -> None:
    # Match as a numeric token so we do not false-positive on substrings of other numbers.
    pattern = re.compile(rf"(?<![\d.]){re.escape(rate)}(?![\d])")
    hits: list[str] = []
    for path in _iter_src_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        if pattern.search(text):
            hits.append(str(path.relative_to(SRC_ROOT.parent)))
    assert not hits, f"rate {rate!r} found in: {hits}"
