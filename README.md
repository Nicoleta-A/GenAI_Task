# Port Tariff Agent

Agentic RAG system that reads a port tariff PDF, extracts charge rules with an LLM, and computes vessel port charges with a **deterministic** calculator (the LLM never does arithmetic).

## Setup

```bash
uv sync --extra dev
cp .env.example .env
```

Edit `.env` and set `GEMINI_API_KEY` (never commit `.env`). Optional:

| Var | Default | Notes |
|---|---|---|
| `GEMINI_API_KEY` | _(required for live)_ | Google AI Studio / Gemini API key |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Gemini model id |
| `LLM_MODE` | `live` | `replay` uses `data/llm_cache` only |

Existing process env vars are not overridden by `.env`. Docker: `--env-file .env`.

Copy / place the tariff at `data/Port_Tariff.pdf` (from `Port Tariff.pdf`).

## Tests & lint

```bash
uv run pytest -m "not live"
uv run ruff check src tests
uv run mypy --strict src
uv run pytest -m live    # needs GEMINI_API_KEY
```

## Live demo (needs `GEMINI_API_KEY` in `.env`)

```bash
uv run tariff-agent build-rulebook --pdf data/Port_Tariff.pdf --force
uv run tariff-agent calculate --pdf data/Port_Tariff.pdf --port Durban --vessel tests/fixtures/vessel_sudestada.json
uv run pytest -m live
```

Caches land under `data/llm_cache/` and `data/rulebooks/` (gitignored). Without a key, use the gold rulebook offline path below — do not invent live metrics.

## CLI

```bash
# Build / cache a rulebook for a PDF (needs Gemini unless a rulebook is pre-seeded)
uv run tariff-agent build-rulebook --pdf data/Port_Tariff.pdf

# Calculate (JSON vessel file)
uv run tariff-agent calculate --pdf data/Port_Tariff.pdf --port Durban --vessel tests/fixtures/vessel_sudestada.json

# Calculate from free-text vessel description (LLM parse; file must not start with `{`)
# e.g. a .txt containing: SUDESTADA bulk carrier GT 51300, 2 ops, 3.39 days alongside
uv run tariff-agent calculate --pdf data/Port_Tariff.pdf --port Durban --vessel path/to/vessel.txt
```

Offline demo using the gold rulebook (no LLM):

```python
import json
from pathlib import Path
from tariff_agent.domain.rules import Rulebook
from tariff_agent.domain.vessel import VesselProfile
from tariff_agent.engine.selector import calculate_all

gold = Rulebook.model_validate_json(Path("tests/fixtures/durban_gold_rulebook.json").read_text())
vessel = VesselProfile.from_json(json.loads(Path("tests/fixtures/vessel_sudestada.json").read_text()))
print(calculate_all(gold, "Durban", vessel.facts()).model_dump_json(indent=2))
```

## API

```bash
uv run uvicorn tariff_agent.api:app --reload
```

Health:

```bash
curl -s http://127.0.0.1:8000/health
```

Upload a PDF → build/cache a rulebook (`multipart` field name `pdf`):

```bash
curl -s -X POST http://127.0.0.1:8000/rulebooks \
  -F "pdf=@data/Port_Tariff.pdf" 
# → {"rulebook_id":"<sha>", "n_rules":N, "warnings":[...]}
```

Calculate from structured vessel facts (flat schema) or assessment nested JSON:

```bash
curl -s -X POST http://127.0.0.1:8000/calculate \
  -H "Content-Type: application/json" \
  -d '{
    "rulebook_id": "<sha>",
    "port": "Durban",
    "vessel": {"gt": 51300, "days_alongside": 3.39, "num_operations": 2},
    "vat_rate": 0
  }'
```

Or free-text NL vessel query (LLM parse; needs live/replay):

```bash
curl -s -X POST http://127.0.0.1:8000/calculate \
  -H "Content-Type: application/json" \
  -d '{
    "rulebook_id": "<sha>",
    "port": "Durban",
    "query": "Bulk carrier SUDESTADA, GT 51300, NT 31192, 2 ops, 3.39 days alongside"
  }'
```

Docker:

```bash
docker build -t tariff-agent .
docker run -p 8000:8000 --env-file .env tariff-agent
```

## Architecture

```
PDF → pages + BM25 (no LLM) → Gemini extract in small batches → rulebook.json
    → validators/repair → rulebook.json (by PDF hash)
    → VesselProfile → select rules → deterministic calculator → report
```

Packages under `src/tariff_agent/`: `domain/`, `engine/` (pure), `ingestion/`, `llm/`, `extraction/`, `parsing/`, plus `service.py`, `store.py`, `cli.py`, `api.py`.

**No tariff ports/rates/clauses in `src/`** — enforced by `tests/unit/test_no_hardcoded_tariff_data.py`.

## Eval snapshot

See `evals/report.md` (from `tests/evals/test_evals.py`). Offline gold-rulebook path matches Durban reference charges within stated tolerances; Richards Bay port-swap uses hand-verified fixture rates. Live Gemini metrics land there after `uv run pytest -m live`.

## Known limitations

1. **“Running Lines” vs berthing:** the assessment reference value equals **Berthing services**, not clause “Running of vessel lines”. The system reports both `berthing_services` and `running_of_lines`. Tests map the reference alias only in fixtures.
2. **`days_alongside`:** port dues time component uses vessel `days_alongside`, not entrance-to-departure duration.
3. **VTS delta:** reference VTS implies a slightly different GT; we use stated GT with `rel_tol` 0.5%.
4. **Out of scope (v1):** SAMSA levy, cargo dues, berth dues (non-working vessels). VAT is optional via `vat_rate` (default `0`, never hardcoded to 15%).
5. **Live extraction** needs `GEMINI_API_KEY`; without it, use the gold rulebook / replay cache.
6. **LLM calls:** page finding is BM25 only. Extraction is split into small batches (about 12k characters of page text each, 2k per page) so a single request does not get dropped. A free-text vessel query is one extra call.

## Next steps

- Record live Gemini cassettes for locator/extractor on each charge type.
- Tighten band-coverage validation for GT intervals.
- Optional embedding retriever behind the same `Retriever` protocol.
- Deploy API (Cloud Run / Fly) with persisted rulebook store.
