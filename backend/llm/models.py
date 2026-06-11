"""Explicit per-role model routing.

Single registry so the 8B/32B right-sizing is a config change here, not scattered
constants across agents. Model IDs are provisional and will be switched later.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    primary: str        # Groq-hosted
    fallback: str       # local Ollama (base_url swap)


MODEL_REGISTRY: dict[str, ModelSpec] = {
    # Classification / reasoning — intended to be an 8B model eventually.
    "diagnoser": ModelSpec(primary="meta-llama/llama-4-scout-17b-16e-instruct", fallback="llama3.1:8b"),
    # Code generation — intended to be a 32B code model.
    "patcher": ModelSpec(primary="qwen/qwen3-32b", fallback="qwen2.5-coder:14b"),
    # Strategic retry decision — small/fast.
    "reflector": ModelSpec(primary="meta-llama/llama-4-scout-17b-16e-instruct", fallback="llama3.1:8b"),
}


def model_for(role: str) -> ModelSpec:
    return MODEL_REGISTRY[role]
