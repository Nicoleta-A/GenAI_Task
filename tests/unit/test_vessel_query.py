"""Vessel query parsing tests (JSON fast-path, FakeLLM free-text, CachingClient replay)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tariff_agent.domain.exceptions import MissingFacts
from tariff_agent.llm.client import (
    CachingClient,
    FakeLLM,
    GeminiClient,
    LLMResponse,
)
from tariff_agent.parsing.vessel_query import _ParsedVessel, parse_vessel_query

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

SUDESTADA_NL = (
    "SUDESTADA, bulk carrier, GT 51,300, LOA 229.2 m, 3.39 days alongside, 2 operations"
)

SUDESTADA_PARSED = _ParsedVessel(
    name="SUDESTADA",
    gt=51300,
    vessel_type="Bulk Carrier",
    loa=229.2,
    days_alongside=3.39,
    num_operations=2,
)


def test_json_fast_path_no_llm() -> None:
    text = (FIXTURES / "vessel_sudestada.json").read_text(encoding="utf-8")
    fake = FakeLLM()  # would fail if called
    profile = parse_vessel_query(text, client=fake)
    assert profile.gt == 51300
    assert fake.calls == []


def test_free_text_fake_llm() -> None:
    fake = FakeLLM(
        [
            LLMResponse(
                text=SUDESTADA_PARSED.model_dump_json(),
                parsed=SUDESTADA_PARSED,
            )
        ]
    )
    profile = parse_vessel_query(SUDESTADA_NL, client=fake)
    assert profile.gt == 51300
    assert profile.days_alongside == 3.39
    assert profile.num_operations == 2
    assert profile.name == "SUDESTADA"
    assert len(fake.calls) == 1
    assert fake.calls[0]["schema"] is _ParsedVessel


def test_free_text_caching_replay(tmp_path: Path) -> None:
    """Record once via FakeLLM inner, then replay from disk with no inner calls."""
    inner = FakeLLM(
        [
            LLMResponse(
                text=SUDESTADA_PARSED.model_dump_json(),
                parsed=SUDESTADA_PARSED,
            )
        ]
    )
    live = CachingClient(inner, cache_dir=tmp_path, model_name="vessel-test", mode="live")
    first = parse_vessel_query(SUDESTADA_NL, client=live)
    assert first.gt == 51300
    assert live.network_calls == 1
    assert len(list(tmp_path.glob("*.json"))) == 1

    # Empty the inner queue; replay must not call it.
    assert inner._responses == []  # noqa: SLF001 — intentional: prove cache hit
    replay = CachingClient(inner, cache_dir=tmp_path, model_name="vessel-test", mode="replay")
    second = parse_vessel_query(SUDESTADA_NL, client=replay)
    assert second.gt == first.gt
    assert second.days_alongside == first.days_alongside
    assert replay.network_calls == 0


def test_missing_facts() -> None:
    fake = FakeLLM(
        [
            LLMResponse(
                text="{}",
                parsed=_ParsedVessel(name="X", gt=None, days_alongside=None, num_operations=None),
            )
        ]
    )
    with pytest.raises(MissingFacts) as exc:
        parse_vessel_query("a vessel with no numbers", client=fake)
    assert "gt" in exc.value.names


@pytest.mark.live
def test_live_free_text_vessel_parse() -> None:
    if not (os.environ.get("GEMINI_API_KEY") or "").strip():
        pytest.skip("GEMINI_API_KEY not set")
    client = GeminiClient()
    profile = parse_vessel_query(SUDESTADA_NL, client=client)
    assert profile.gt == 51300
    assert profile.num_operations == 2
    assert profile.days_alongside is not None
    assert abs(float(profile.days_alongside) - 3.39) < 0.05
