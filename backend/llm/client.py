"""Structured-output LLM client for Groq-hosted models with local Ollama fallback."""
from __future__ import annotations

import asyncio
import json
from typing import TypeVar

import httpx
from pydantic import BaseModel

from backend.config import settings


SchemaT = TypeVar("SchemaT", bound=BaseModel)

GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_PRIMARY_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
OLLAMA_FALLBACK_MODEL = "llama3.1:8b"


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
        try:
            return await self._complete_with_endpoint(
                self._select_endpoint(model),
                model=model,
                messages=messages,
                schema=schema,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                use_json_schema=use_json_schema,
                reasoning_effort=reasoning_effort,
                reasoning_format=reasoning_format,
            )
        except (httpx.HTTPError, TimeoutError):
            if model == fallback_model:
                raise
            return await self._complete_with_endpoint(
                self.ollama_chat_completions_url,
                model=fallback_model,
                messages=messages,
                schema=schema,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                use_json_schema=False,
                reasoning_effort=None,
                reasoning_format=None,
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
    ) -> SchemaT:
        headers = {"Content-Type": "application/json"}
        if endpoint == GROQ_CHAT_COMPLETIONS_URL:
            if not self.groq_api_key:
                raise ValueError("GROQ_API_KEY is required for Groq completions")
            headers["Authorization"] = f"Bearer {self.groq_api_key}"

        response_format = {"type": "json_object"}
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

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await asyncio.wait_for(
                client.post(endpoint, headers=headers, json=payload),
                timeout=timeout,
            )
            response.raise_for_status()

        body = response.json()
        content = body["choices"][0]["message"]["content"]
        return schema.model_validate(json.loads(content))
