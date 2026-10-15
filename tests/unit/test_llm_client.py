"""LLM client unit tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from tariff_agent.domain.exceptions import LLMOutputError, ReplayCacheMiss
from tariff_agent.llm.client import (
    CachingClient,
    FakeLLM,
    GeminiClient,
    LLMResponse,
    _retry,
    cache_key,
)


class _CountingLLM:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, prompt: str, schema: Any = None) -> LLMResponse:
        self.calls += 1
        return LLMResponse(text='{"ok": true}', parsed={"ok": True})


def test_cache_hit_skips_network(tmp_path: Path) -> None:
    inner = _CountingLLM()
    client = CachingClient(inner, cache_dir=tmp_path, model_name="m", mode="live")
    r1 = client.generate("hello")
    r2 = client.generate("hello")
    assert r1.text == r2.text
    assert inner.calls == 1
    assert client.network_calls == 1


def test_cache_key_stable() -> None:
    a = cache_key("m", "p", None)
    b = cache_key("m", "p", None)
    assert a == b
    c = cache_key("m", "other", None)
    assert a != c


def test_replay_miss_raises(tmp_path: Path) -> None:
    inner = _CountingLLM()
    client = CachingClient(inner, cache_dir=tmp_path, model_name="m", mode="replay")
    with pytest.raises(ReplayCacheMiss):
        client.generate("missing")


def test_fake_llm_queues() -> None:
    fake = FakeLLM([LLMResponse(text="a"), LLMResponse(text="b")])
    assert fake.generate("x").text == "a"
    assert fake.generate("x").text == "b"


class _OkSchema(BaseModel):
    ok: bool


class _FakeGenResponse:
    def __init__(self, *, text: str = "") -> None:
        self.text = text


def _mock_gemini_client(response: _FakeGenResponse) -> MagicMock:
    models = MagicMock()
    models.generate_content.return_value = response
    client = MagicMock()
    client.models = models
    return client


def test_gemini_schema_path() -> None:
    client = GeminiClient(api_key="test-key")
    fake = _mock_gemini_client(_FakeGenResponse(text='{"ok": true}'))
    client._client = fake

    result = client.generate("extract", schema=_OkSchema)

    assert result.parsed is not None
    assert result.parsed.ok is True
    config = fake.models.generate_content.call_args.kwargs["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_schema is _OkSchema


def test_gemini_retries_on_429() -> None:
    client = GeminiClient(api_key="test-key")
    models = MagicMock()
    err = Exception("429 resource exhausted")
    err.status_code = 429  # type: ignore[attr-defined]
    models.generate_content.side_effect = [
        err,
        _FakeGenResponse(text="ok"),
    ]
    fake = MagicMock()
    fake.models = models
    client._client = fake

    sleeps: list[float] = []
    from tariff_agent.llm import client as client_mod

    original = client_mod._retry

    def _retry_no_sleep(fn: Any, **kwargs: Any) -> LLMResponse:
        kwargs["sleeper"] = sleeps.append
        return original(fn, **kwargs)

    client_mod._retry = _retry_no_sleep  # type: ignore[assignment]
    try:
        result = client.generate("hi")
    finally:
        client_mod._retry = original  # type: ignore[assignment]

    assert result.text == "ok"
    assert models.generate_content.call_count == 2
    assert sleeps == [5.0]


def test_gemini_missing_api_key() -> None:
    client = GeminiClient(api_key="")
    with pytest.raises(LLMOutputError, match="GEMINI_API_KEY"):
        client.generate("x")


def test_retry_non_retryable_raises() -> None:
    calls = 0

    def boom() -> LLMResponse:
        nonlocal calls
        calls += 1
        raise ValueError("bad")

    with pytest.raises(ValueError):
        _retry(boom, retries=2, sleeper=lambda _: None)
    assert calls == 1
