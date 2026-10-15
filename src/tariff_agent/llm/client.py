"""LLM client protocol, Gemini, caching, and FakeLLM."""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from tariff_agent.domain.exceptions import LLMOutputError, ReplayCacheMiss

DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"


@dataclass
class LLMResponse:
    text: str
    parsed: Any | None = None
    raw: Any | None = None


class LLMClient(Protocol):
    def generate(
        self,
        prompt: str,
        schema: type[BaseModel] | None = None,
    ) -> LLMResponse:
        """Generate a model response."""


def cache_key(model: str, prompt: str, schema: type[BaseModel] | None) -> str:
    schema_json = ""
    if schema is not None:
        schema_json = json.dumps(schema.model_json_schema(), sort_keys=True)
    # Trailing [] keeps keys compatible with caches written when tools were unused.
    blob = "|".join([model, prompt, schema_json, "[]"])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class FakeLLM:
    """Scripted responses for unit tests."""

    def __init__(self, responses: list[LLMResponse] | None = None) -> None:
        self._responses = list(responses or [])
        self.calls: list[dict[str, Any]] = []

    def generate(
        self,
        prompt: str,
        schema: type[BaseModel] | None = None,
    ) -> LLMResponse:
        self.calls.append({"prompt": prompt, "schema": schema})
        if not self._responses:
            raise LLMOutputError("FakeLLM has no queued responses")
        return self._responses.pop(0)


class CachingClient:
    """Disk-backed record/replay wrapper."""

    def __init__(
        self,
        inner: LLMClient,
        cache_dir: Path,
        model_name: str = "cached",
        mode: str | None = None,
    ) -> None:
        self._inner = inner
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._model_name = model_name
        self._mode = mode
        self.network_calls = 0

    def _mode_now(self) -> str:
        return (self._mode or os.environ.get("LLM_MODE", "live")).lower()

    def generate(
        self,
        prompt: str,
        schema: type[BaseModel] | None = None,
    ) -> LLMResponse:
        key = cache_key(self._model_name, prompt, schema)
        path = self._cache_dir / f"{key}.json"
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            parsed = payload.get("parsed")
            if schema is not None and parsed is not None:
                parsed = schema.model_validate(parsed)
            return LLMResponse(text=payload.get("text", ""), parsed=parsed)
        if self._mode_now() == "replay":
            raise ReplayCacheMiss(f"No cache entry for key {key}")
        response = self._inner.generate(prompt, schema=schema)
        self.network_calls += 1
        to_store: dict[str, Any] = {"text": response.text, "parsed": None}
        if response.parsed is not None:
            if isinstance(response.parsed, BaseModel):
                to_store["parsed"] = response.parsed.model_dump()
            else:
                to_store["parsed"] = response.parsed
        path.write_text(json.dumps(to_store, indent=2), encoding="utf-8")
        return response


def _retry(
    fn: Callable[[], LLMResponse],
    *,
    retries: int = 5,
    base_delay: float = 0.5,
    sleeper: Callable[[float], None] = time.sleep,
) -> LLMResponse:
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - classify below
            last = exc
            status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
            message = str(exc).lower()
            rate_limited = status == 429 or "429" in message or "rate-limited" in message or "rate limit" in message
            connection = (
                "connection error" in message
                or "disconnected" in message
                or "remoteprotocol" in type(exc).__name__.lower()
                or "connecterror" in type(exc).__name__.lower()
                or "apiconnectionerror" in type(exc).__name__.lower()
                or "10061" in message
            )
            timed_out = "timeout" in message or "timeout" in type(exc).__name__.lower()
            retryable = (
                rate_limited
                or connection
                or timed_out
                or status in {500, 502, 503}
                or "resource exhausted" in message
            )
            if not retryable or attempt >= retries:
                raise
            # Free-tier Gemini often needs a longer cool-down than 0.5s backoff.
            if rate_limited:
                delay = min(60.0, 5.0 * (2**attempt))
            elif connection or timed_out:
                delay = min(30.0, 2.0 * (2**attempt))
            else:
                delay = base_delay * (2**attempt)
            sleeper(delay)
    assert last is not None
    raise last


class GeminiClient:
    """google-genai client (sync)."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self.temperature = temperature
        self._client: Any | None = None

    @property
    def api_key(self) -> str | None:
        if self._api_key is not None:
            return self._api_key
        return os.environ.get("GEMINI_API_KEY")

    @property
    def model(self) -> str:
        if self._model is not None:
            return self._model
        return os.environ.get("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL

    def _ensure_client(self) -> Any:
        if self._client is None:
            if not self.api_key:
                raise LLMOutputError("GEMINI_API_KEY is not set")
            from google import genai

            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def generate(
        self,
        prompt: str,
        schema: type[BaseModel] | None = None,
    ) -> LLMResponse:
        client = self._ensure_client()
        from google.genai import types

        config_kwargs: dict[str, Any] = {
            "temperature": self.temperature,
            "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
        }
        if schema is not None:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_schema"] = schema
        config = types.GenerateContentConfig(**config_kwargs)

        def _call() -> LLMResponse:
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=config,
            )
            text = getattr(response, "text", None) or ""
            parsed: Any | None = None
            if schema is not None:
                if not text.strip():
                    raise LLMOutputError("Empty model response for structured output")
                try:
                    parsed = schema.model_validate_json(text)
                except Exception as exc:
                    raise LLMOutputError(f"Failed to parse structured output: {exc}") from exc
            return LLMResponse(text=text, parsed=parsed, raw=response)

        try:
            return _retry(_call)
        except LLMOutputError:
            raise
        except Exception as exc:
            status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
            if status in {401, 402, 403, 404, 429} or "Error code:" in str(exc):
                raise LLMOutputError(str(exc)) from exc
            if "timeout" in type(exc).__name__.lower() or "connection" in type(exc).__name__.lower():
                raise LLMOutputError(str(exc)) from exc
            raise


def build_llm_client(
    cache_dir: Path | None = None,
    *,
    fake: FakeLLM | None = None,
) -> LLMClient:
    if fake is not None:
        return fake
    gemini = GeminiClient()
    if cache_dir is None:
        return gemini
    return CachingClient(gemini, cache_dir=cache_dir, model_name=gemini.model)
