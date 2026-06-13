"""Structured-output LLM client for Groq-hosted models with local Ollama fallback."""
from __future__ import annotations

import asyncio
import json
from time import perf_counter
from typing import Any, Protocol, TypeVar

import httpx
from pydantic import BaseModel

from backend.config import settings
from backend.llm.models import model_for
from backend.observability.metrics import LLMCallMetric, record_llm_call


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
# Floor timeout (seconds) for the local Ollama fallback — CPU inference on a
# code model can take minutes, so the Groq budget is far too short here.
OLLAMA_FALLBACK_TIMEOUT = 240.0


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
            self._http = httpx.AsyncClient(http2=True)
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
        """Return a parsed Pydantic object from Groq, falling back to local Ollama."""
        endpoint = self._select_endpoint(model)
        try:
            result, usage = await self._timed_call(
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
            # Local Ollama runs on CPU — a single completion can take minutes,
            # far longer than the Groq budget. Give the fallback its own timeout
            # so it isn't killed before the model has a chance to respond.
            result, usage = await self._timed_call(
                self.ollama_chat_completions_url,
                model=fallback_model,
                fallback_used=True,
                messages=messages,
                schema=schema,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=max(timeout, OLLAMA_FALLBACK_TIMEOUT),
                use_json_schema=False,
                reasoning_effort=None,
                reasoning_format=None,
            )
            return result

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
