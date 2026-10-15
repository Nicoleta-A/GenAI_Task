# Port Tariff Agent — Eval Report

## Mode
- Live Gemini: yes
- `GEMINI_API_KEY` present: yes

## Live path status

- Key available. Run `uv run pytest -m live` to populate locate/extract/e2e sections below,
  and `uv run tariff-agent build-rulebook --pdf data/Port_Tariff.pdf --force` for `data/rulebooks/`.

## 1. Golden end-to-end (gold rulebook, offline)

| Charge | Expected | Actual | Rel error |
|---|---:|---:|---:|
| light_dues | 60062.04 | 60062.04 | 0.0000% |
| port_dues | 199549.22 | 199371.35 | 0.0891% |
| towage | 147074.38 | 147074.38 | 0.0000% |
| vts | 33315.75 | 33345.00 | 0.0878% |
| pilotage | 47189.94 | 47189.94 | 0.0000% |
| berthing_services | 19639.50 | 19639.50 | 0.0000% |

## 2. Extraction accuracy
- Offline self-compare of gold: field accuracy 100.0%
- Live extract vs gold: see §6 (requires key + `pytest -m live`).

## 3. Retrieval recall@k (BM25, offline)
- Covered by `tests/unit/test_ingestion.py` (recall@5 on seed queries).
- Live locator recall: see §6.

## 4. Port-swap (Richards Bay, gold rulebook offline)

| Charge | Expected | Actual | Rel error |
|---|---:|---:|---:|
| light_dues | 60062.04 | 60062.04 | 0.0000% |
| vts | 27702.00 | 27702.00 | 0.0000% |
| pilotage | 73135.10 | 73135.10 | 0.0000% |
| towage | 160782.38 | 160782.38 | 0.0000% |
| berthing_services | 20161.74 | 20161.74 | 0.0000% |
| running_of_lines | 3309.12 | 3309.12 | 0.0000% |

## 5. Stability / cost
- Not run offline. With a live key, repeat extraction 3× and compare rule ids/rates.

## 6. Live Gemini metrics
- Populated only when `pytest -m live` runs with a non-empty `GEMINI_API_KEY`.
- Placeholders until then:
  - Locate recall (gold printed page in finish pages / top search): _pending_
  - Extract `compare_rulebooks` field accuracy: _pending_
  - E2E Durban vs `expected_durban.json`: _pending_

## Notes
- Reference “Running Lines” maps to `berthing_services` in fixtures only.
- Port dues use `days_alongside` (document assumption).
- VTS reference implies a slightly different GT; relative tolerance 0.5%.
- Never edit `tests/fixtures/expected_*.json` to force a pass.

