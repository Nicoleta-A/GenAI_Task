# AGENTS.md — Port Tariff Agent

Working rules for every coding agent on this repo.

1. **Red, then green, then refactor.** One step per commit when practical. Run new tests and show them failing before implementing (batch within a step is OK if tests still gate the implementation).
2. **No tariff knowledge in `src/`:** no port names, rates, section numbers, or clause text. It lives only in the PDF, rulebooks, `config/`, and `tests/fixtures/`. `tests/unit/test_no_hardcoded_tariff_data.py` enforces this.
3. The LLM never does arithmetic. The `engine/` package is pure and deterministic and imports nothing from `llm/`.
4. All LLM calls go through `LLMClient`. Unit and integration tests use `FakeLLM` or the replay cache. Live calls only under `pytest -m live`.
5. Never edit expected values in `tests/fixtures/expected_*.json` to make a test pass. Report the discrepancy instead.
6. **Unknown is not zero.** A charge with no matching rule is `not_found`, never reported as `0`.
7. Type hints everywhere, small modules, typed exceptions (no bare `except`), `ruff` and `mypy --strict` clean.
8. Default test command: `uv run pytest -m "not live"`.

See `PLAN.md` for architecture and the Step 0–12 outline.
