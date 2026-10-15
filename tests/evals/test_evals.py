"""Live evals (skipped without GEMINI_API_KEY). Offline metrics still recorded."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

from tariff_agent.domain.rules import Rulebook
from tariff_agent.domain.vessel import VesselProfile
from tariff_agent.engine.selector import calculate_all
from tariff_agent.extraction.compare import compare_rulebooks
from tariff_agent.extraction.locator import locate_charge_pages
from tariff_agent.ingestion.index import BM25Retriever
from tariff_agent.ingestion.pdf_pages import load_pages
from tariff_agent.llm.client import GeminiClient, build_llm_client
from tariff_agent.service import TariffService
from tariff_agent.store import RulebookStore

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "evals" / "report.md"
PDF = ROOT / "data" / "Port_Tariff.pdf"
CHARGES_CONFIG = ROOT / "config" / "charges.yaml"

# Printed page numbers from assessment gold mapping (tests only — not in src/).
GOLD_PAGES: dict[str, int] = {
    "light_dues": 9,
    "vts": 11,
    "pilotage": 13,
    "towage": 15,
    "berthing_services": 18,
    "running_of_lines": 19,
    "port_dues": 21,
}


def _api_key() -> str:
    return (os.environ.get("GEMINI_API_KEY") or "").strip()


def _require_live_key() -> str:
    key = _api_key()
    if not key:
        pytest.skip("GEMINI_API_KEY not set — live path blocked")
    return key


def _within_tol(actual: float, expected: float, spec: dict[str, float]) -> bool:
    if "abs_tol" in spec:
        return abs(actual - expected) <= float(spec["abs_tol"])
    rel_tol = float(spec.get("rel_tol", 0.0))
    if expected == 0:
        return actual == 0
    return abs(actual - expected) / expected <= rel_tol


def test_offline_metrics_written() -> None:
    """Always write offline eval slice (+ live blocker status) into evals/report.md."""
    expected = json.loads((FIXTURES / "expected_durban.json").read_text(encoding="utf-8"))
    gold = Rulebook.model_validate(
        json.loads((FIXTURES / "durban_gold_rulebook.json").read_text(encoding="utf-8"))
    )
    vessel = VesselProfile.from_json(
        json.loads((FIXTURES / "vessel_sudestada.json").read_text(encoding="utf-8"))
    )
    report = calculate_all(gold, "Durban", vessel.facts())
    key_present = bool(_api_key())
    lines = [
        "# Port Tariff Agent — Eval Report",
        "",
        "## Mode",
        f"- Live Gemini: {'yes' if key_present else 'no (offline fixture metrics only)'}",
        f"- `GEMINI_API_KEY` present: {'yes' if key_present else '**no — live-rulebook + live evals blocked**'}",
        "",
        "## Live path status",
        "",
    ]
    if key_present:
        lines.extend(
            [
                "- Key available. Run `uv run pytest -m live` to populate locate/extract/e2e sections below,",
                "  and `uv run tariff-agent build-rulebook --pdf data/Port_Tariff.pdf --force` for `data/rulebooks/`.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "- **BLOCKED:** `.env` has empty/`missing` `GEMINI_API_KEY`.",
                "- Did **not** invent live locate/extract/calculate results.",
                "- `data/llm_cache/` and `data/rulebooks/` remain unpopulated until a real key is set.",
                "- Live test scaffolding in this module skips without a key (`pytest -m live`).",
                "- To unblock: `cp .env.example .env`, paste an Gemini key, then:",
                "  1. `uv run tariff-agent build-rulebook --pdf data/Port_Tariff.pdf --force`",
                "  2. `uv run tariff-agent calculate --pdf data/Port_Tariff.pdf --port Durban "
                "--vessel tests/fixtures/vessel_sudestada.json`",
                "  3. `uv run pytest -m live`",
                "",
            ]
        )

    lines.extend(
        [
            "## 1. Golden end-to-end (gold rulebook, offline)",
            "",
            "| Charge | Expected | Actual | Rel error |",
            "|---|---:|---:|---:|",
        ]
    )
    by_type = report.by_type()
    for key, spec in expected["charges"].items():
        if key == "running_lines_reference":
            ctype = spec["maps_to"]
            exp = float(spec["expected"])
        else:
            ctype = key
            exp = float(spec["expected"])
        actual = by_type[ctype].amount or 0.0
        rel = abs(actual - exp) / exp if exp else 0.0
        lines.append(f"| {ctype} | {exp:.2f} | {actual:.2f} | {rel:.4%} |")

    cmp = compare_rulebooks(gold, gold)
    lines.extend(
        [
            "",
            "## 2. Extraction accuracy",
            f"- Offline self-compare of gold: field accuracy {cmp.field_accuracy:.1%}",
            "- Live extract vs gold: see §6 (requires key + `pytest -m live`).",
            "",
            "## 3. Retrieval recall@k (BM25, offline)",
            "- Covered by `tests/unit/test_ingestion.py` (recall@5 on seed queries).",
            "- Live locator recall: see §6.",
            "",
            "## 4. Port-swap (Richards Bay, gold rulebook offline)",
            "",
        ]
    )
    rb_expected = json.loads((FIXTURES / "expected_richards_bay.json").read_text(encoding="utf-8"))
    rb_report = calculate_all(gold, "Richards Bay", vessel.facts())
    lines.append("| Charge | Expected | Actual | Rel error |")
    lines.append("|---|---:|---:|---:|")
    for key, spec in rb_expected["charges"].items():
        exp = float(spec["expected"])
        actual = rb_report.by_type()[key].amount or 0.0
        rel = abs(actual - exp) / exp if exp else 0.0
        lines.append(f"| {key} | {exp:.2f} | {actual:.2f} | {rel:.4%} |")

    lines.extend(
        [
            "",
            "## 5. Stability / cost",
            "- Not run offline. With a live key, repeat extraction 3× and compare rule ids/rates.",
            "",
            "## 6. Live Gemini metrics",
            "- Populated only when `pytest -m live` runs with a non-empty `GEMINI_API_KEY`.",
            "- Placeholders until then:",
            "  - Locate recall (gold printed page in finish pages / top search): _pending_",
            "  - Extract `compare_rulebooks` field accuracy: _pending_",
            "  - E2E Durban vs `expected_durban.json`: _pending_",
            "",
            "## Notes",
            "- Reference “Running Lines” maps to `berthing_services` in fixtures only.",
            "- Port dues use `days_alongside` (document assumption).",
            "- VTS reference implies a slightly different GT; relative tolerance 0.5%.",
            "- Never edit `tests/fixtures/expected_*.json` to force a pass.",
            "",
        ]
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert REPORT.exists()


def _append_live_section(title: str, body_lines: list[str]) -> None:
    """Append or replace a named live subsection in the eval report."""
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    text = REPORT.read_text(encoding="utf-8") if REPORT.exists() else "# Port Tariff Agent — Eval Report\n\n"
    marker = f"### {title}"
    block = "\n".join([marker, *body_lines, ""])
    if marker in text:
        start = text.index(marker)
        next_heads = [
            idx
            for needle in ("\n### ", "\n## ")
            if (idx := text.find(needle, start + len(marker))) != -1
        ]
        end = min(next_heads) if next_heads else len(text)
        text = text[:start] + block + ("\n" if not text[end:].startswith("\n") else "") + text[end:].lstrip("\n")
        if not text.endswith("\n"):
            text += "\n"
    elif "## 6. Live Gemini metrics" in text:
        text = text.rstrip() + "\n\n" + block + "\n"
    else:
        text = text.rstrip() + "\n\n## 6. Live Gemini metrics\n\n" + block + "\n"
    REPORT.write_text(text, encoding="utf-8")


@pytest.mark.live
def test_live_smoke_requires_key() -> None:
    _require_live_key()
    client = GeminiClient()
    resp = client.generate("Reply with the single word OK.")
    assert resp.text


@pytest.mark.live
def test_live_locate_recall(tariff_pdf: Path, tmp_path: Path) -> None:
    """Gold printed pages should be in the BM25 top-k (no LLM)."""
    pages = load_pages(tariff_pdf, cache_dir=tmp_path / "pages")
    retriever = BM25Retriever(pages)
    charge_types = yaml.safe_load(CHARGES_CONFIG.read_text(encoding="utf-8"))["charge_types"]

    hits: list[str] = []
    misses: list[str] = []
    for charge_type, seeds in charge_types.items():
        gold = GOLD_PAGES[charge_type]
        result = locate_charge_pages(retriever, charge_type, seeds)
        found = gold in result.pages
        line = f"{charge_type}: gold={gold} located={result.pages} hit={found}"
        (hits if found else misses).append(line)

    _append_live_section(
        "Locate recall",
        [
            f"- Hits: {len(hits)}/{len(charge_types)}",
            *[f"  - {h}" for h in hits],
            *([f"  - MISS {m}" for m in misses] if misses else ["  - (no misses)"]),
        ],
    )
    assert not misses, f"live locate misses: {misses}"


@pytest.mark.live
def test_live_extract_compare_rulebooks(tariff_pdf: Path) -> None:
    """Build a live rulebook and compare field accuracy against gold (extras OK)."""
    _require_live_key()
    gold = Rulebook.model_validate(
        json.loads((FIXTURES / "durban_gold_rulebook.json").read_text(encoding="utf-8"))
    )
    store = RulebookStore(ROOT / "data" / "rulebooks")
    llm = build_llm_client(cache_dir=ROOT / "data" / "llm_cache")
    service = TariffService(
        llm=llm,
        store=store,
        charges_config=CHARGES_CONFIG,
        page_cache_dir=ROOT / "data" / "page_cache",
    )
    rulebook_id, extracted, warnings = service.build_rulebook(tariff_pdf, force=True)
    cmp = compare_rulebooks(gold, extracted)

    _append_live_section(
        "Extract compare_rulebooks",
        [
            f"- Rulebook id: `{rulebook_id}` → `data/rulebooks/{rulebook_id}.json`",
            f"- Extracted rules: {len(extracted.rules)} (gold: {len(gold.rules)})",
            f"- Field accuracy: {cmp.field_accuracy:.1%}",
            f"- Missing gold ids: {cmp.missing_ids or 'none'}",
            f"- Extra ids (OK): {cmp.extra_ids or 'none'}",
            f"- Mismatches: {len(cmp.mismatches)}",
            f"- Warnings: {warnings[:8]}{'…' if len(warnings) > 8 else ''}",
        ],
    )
    # Gold rules must be present and match; extras are allowed.
    assert not cmp.missing_ids, f"missing gold rules: {cmp.missing_ids}"
    assert not cmp.mismatches, f"field mismatches: {cmp.mismatches[:5]}"


@pytest.mark.live
def test_live_e2e_durban_vs_expected(tariff_pdf: Path) -> None:
    """End-to-end live rulebook + Durban calculate vs expected_durban.json tolerances."""
    _require_live_key()
    expected = json.loads((FIXTURES / "expected_durban.json").read_text(encoding="utf-8"))
    vessel = VesselProfile.from_json(
        json.loads((FIXTURES / "vessel_sudestada.json").read_text(encoding="utf-8"))
    )
    store = RulebookStore(ROOT / "data" / "rulebooks")
    llm = build_llm_client(cache_dir=ROOT / "data" / "llm_cache")
    service = TariffService(
        llm=llm,
        store=store,
        charges_config=CHARGES_CONFIG,
        page_cache_dir=ROOT / "data" / "page_cache",
    )
    # Prefer cached rulebook from extract test / CLI; force only if missing.
    _, rulebook, warnings = service.build_rulebook(tariff_pdf, force=False)
    calc = service.calculate_with_rulebook(rulebook, "Durban", vessel)
    by_type = calc.by_type()

    rows: list[str] = []
    failures: list[str] = []
    for key, spec in expected["charges"].items():
        if key == "running_lines_reference":
            ctype = str(spec["maps_to"])
        else:
            ctype = key
        exp = float(spec["expected"])
        item = by_type[ctype]
        actual = float(item.amount or 0.0)
        ok = item.status == "ok" and _within_tol(actual, exp, spec)
        rel = abs(actual - exp) / exp if exp else 0.0
        rows.append(f"| {ctype} | {exp:.2f} | {actual:.2f} | {rel:.4%} | {item.status} | {'pass' if ok else 'FAIL'} |")
        if not ok:
            failures.append(f"{ctype}: actual={actual} expected={exp} status={item.status}")

    _append_live_section(
        "E2E Durban vs expected_durban.json",
        [
            f"- Warnings: {warnings[:5]}",
            "",
            "| Charge | Expected | Actual | Rel error | Status | Result |",
            "|---|---:|---:|---:|---|---|",
            *rows,
        ],
    )
    assert not failures, f"e2e Durban failures: {failures}"
