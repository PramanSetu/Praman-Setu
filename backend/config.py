"""Application settings, loaded from environment / .env."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- LLM providers ---
    groq_api_key: str = ""
    # NOTE: from inside a container, host Ollama is reachable at
    # http://host.docker.internal:11434/v1 (not localhost).
    ollama_base_url: str = "http://localhost:11434/v1"
    default_llm_provider: str = "groq"

    # --- Sandbox ---
    sandbox_timeout: int = 10


settings = Settings()
