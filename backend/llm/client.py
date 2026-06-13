"""Structured-output LLM client for Groq-hosted models with local Ollama fallback."""
from __future__ import annotations

import asyncio
import json
from time import perf_counter
from typing import Any, Protocol, TypeVar

import httpx
from pydantic import BaseModel

from backend.config import settings
from backend.llm.models import model_for, ollama_equivalent
from backend.observability.metrics import LLMCallMetric, record_llm_call

_OLLAMA_TIMEOUT = 180.0  # local inference is far slower than Groq


SchemaT = TypeVar("SchemaT", bound=BaseModel)


class LLMCompleter(Protocol):
    """Structural interface the agents depend on.

    Declared with ``*args/**kwargs: Any`` so both the real ``LLMClient`` and test
    fakes satisfy it without inheritance (mirrors the ``SandboxExecutor`` pattern).
    """

    async def complete(self, *args: Any, **kwargs: Any) -> Any: ...


GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"
# Back-compat aliases sourced from the registry (single source of truth).
GROQ_PRIMARY_MODEL = model_for("diagnoser").primary
OLLAMA_FALLBACK_MODEL = model_for("diagnoser").fallback

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _is_retryable(exc: BaseException) -> bool:
    """Transient errors worth retrying: network failures, timeouts, 429/5xx.

    Auth/client errors (400/401/403/404) are NOT retried — a retry won't help.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS
    if isinstance(exc, httpx.HTTPError):
        # Transport-level: ConnectError, ConnectTimeout, ReadTimeout, ReadError,
        # RemoteProtocolError, PoolTimeout, … — all worth a retry.
        return True
    return isinstance(exc, (TimeoutError, asyncio.TimeoutError))


class LLMClient:
    """Groq-first client wrapper for JSON responses parsed into Pydantic models."""

    def __init__(
        self,
        *,
        groq_api_key: str | None = None,
        ollama_base_url: str | None = None,
        default_provider: str | None = None,
    ) -> None:
        self.default_provider = default_provider or settings.default_llm_provider
        self.groq_api_key = groq_api_key or settings.groq_api_key
        self.ollama_chat_completions_url = (
            ollama_base_url or settings.ollama_base_url
        ).rstrip("/") + "/chat/completions"
        # Persistent client → connection keep-alive across the whole pipeline
        # (Diagnoser -> Patcher -> Reflector) instead of a TLS handshake per call.
        self._http: httpx.AsyncClient | None = None

    def _http_client(self) -> httpx.AsyncClient:
        if self._http is None:
            # HTTP/1.1 with keep-alive — reuses connections across calls without the
            # multiplexing/connection-reuse quirks that can cause ConnectErrors.
            self._http = httpx.AsyncClient(
                limits=httpx.Limits(max_keepalive_connections=5, keepalive_expiry=30.0),
            )
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def complete(
        self,
        model: str,
        messages: list[dict],
        schema: type[SchemaT],
        *,
        temperature: float = 0.2,
        max_tokens: int = 600,
        timeout: float = 10,
        fallback_model: str = OLLAMA_FALLBACK_MODEL,
        use_json_schema: bool = False,
        reasoning_effort: str | None = None,
        reasoning_format: str | None = None,
    ) -> SchemaT:
        """Return a parsed Pydantic object from Groq, falling back to local Ollama.

        The primary call is retried with exponential backoff on transient errors
        (connection failures, timeouts, 429/5xx) so a brief Groq blip doesn't
        dead-end the request. Auth/4xx errors fail fast (retrying won't help).

        When DEFAULT_LLM_PROVIDER=ollama, everything runs locally: the Groq model
        id is translated to its Ollama equivalent and Groq is never contacted.
        """
        if self.default_provider == "ollama":
            result, _usage = await self._call_with_retries(
                self.ollama_chat_completions_url,
                model=ollama_equivalent(model),
                fallback_used=False,
                messages=messages,
                schema=schema,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=max(timeout, _OLLAMA_TIMEOUT),
                use_json_schema=False,
                reasoning_effort=None,
                reasoning_format=None,
            )
            return result

        endpoint = self._select_endpoint(model)
        try:
            result, usage = await self._call_with_retries(
                endpoint,
                model=model,
                fallback_used=False,
                messages=messages,
                schema=schema,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                use_json_schema=use_json_schema,
                reasoning_effort=reasoning_effort,
                reasoning_format=reasoning_format,
            )
            return result
        except (httpx.HTTPError, TimeoutError):
            if model == fallback_model:
                raise
            result, usage = await self._timed_call(
                self.ollama_chat_completions_url,
                model=fallback_model,
                fallback_used=True,
                messages=messages,
                schema=schema,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                use_json_schema=False,
                reasoning_effort=None,
                reasoning_format=None,
            )
            return result

    async def _call_with_retries(
        self,
        endpoint: str,
        *,
        schema: type[SchemaT],
        max_retries: int = 3,
        base_delay: float = 1.0,
        **kwargs: Any,
    ) -> tuple[SchemaT, dict | None]:
        attempt = 0
        while True:
            try:
                return await self._timed_call(endpoint, schema=schema, **kwargs)
            except Exception as exc:
                if attempt >= max_retries or not _is_retryable(exc):
                    raise
                # Drop the (possibly degraded) connection pool so the retry opens a
                # fresh connection — the common cause of repeated ConnectErrors.
                await self.aclose()
                await asyncio.sleep(base_delay * (2**attempt))  # 1s, 2s, 4s
                attempt += 1

    async def _timed_call(
        self,
        endpoint: str,
        *,
        model: str,
        fallback_used: bool,
        schema: type[SchemaT],
        **kwargs: Any,
    ) -> tuple[SchemaT, dict | None]:
        provider = "groq" if endpoint == GROQ_CHAT_COMPLETIONS_URL else "ollama"
        start = perf_counter()
        success = False
        usage: dict | None = None
        try:
            result, usage = await self._complete_with_endpoint(
                endpoint, model=model, schema=schema, **kwargs
            )
            success = True
            return result, usage
        finally:
            record_llm_call(
                LLMCallMetric(
                    provider=provider,
                    model=model,
                    latency_ms=round((perf_counter() - start) * 1000, 1),
                    fallback_used=fallback_used,
                    schema_name=schema.__name__,
                    success=success,
                    prompt_tokens=(usage or {}).get("prompt_tokens"),
                    completion_tokens=(usage or {}).get("completion_tokens"),
                    total_tokens=(usage or {}).get("total_tokens"),
                )
            )

    def _select_endpoint(self, model: str) -> str:
        if model == OLLAMA_FALLBACK_MODEL or self.default_provider == "ollama":
            return self.ollama_chat_completions_url
        return GROQ_CHAT_COMPLETIONS_URL

    async def _complete_with_endpoint(
        self,
        endpoint: str,
        *,
        model: str,
        messages: list[dict],
        schema: type[SchemaT],
        temperature: float,
        max_tokens: int,
        timeout: float,
        use_json_schema: bool,
        reasoning_effort: str | None,
        reasoning_format: str | None,
    ) -> tuple[SchemaT, dict | None]:
        headers = {"Content-Type": "application/json"}
        if endpoint == GROQ_CHAT_COMPLETIONS_URL:
            if not self.groq_api_key:
                raise ValueError("GROQ_API_KEY is required for Groq completions")
            headers["Authorization"] = f"Bearer {self.groq_api_key}"

        response_format: dict[str, Any] = {"type": "json_object"}
        if endpoint == GROQ_CHAT_COMPLETIONS_URL and use_json_schema:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "strict": False,
                    "schema": schema.model_json_schema(),
                },
            }

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": response_format,
        }
        if reasoning_effort is not None:
            payload["reasoning_effort"] = reasoning_effort
        if reasoning_format is not None:
            payload["reasoning_format"] = reasoning_format

        response = await asyncio.wait_for(
            self._http_client().post(endpoint, headers=headers, json=payload, timeout=timeout),
            timeout=timeout,
        )
        response.raise_for_status()

        body = response.json()
        content = body["choices"][0]["message"]["content"]
        return schema.model_validate(json.loads(content)), body.get("usage")


# Process-wide singleton: one warm connection pool reused across all nodes.
llm_client = LLMClient()
