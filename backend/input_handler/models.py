"""Pydantic contracts for the Smart Input Handler."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from backend.orchestrator.state import (
    DetectionMethod,
    LanguageDetection,
    ProcessedInput,
    SandboxExecution,
)


class RawInput(BaseModel):
    code: str = Field(min_length=1)
    filename: str | None = None
    error_message: str | None = None

    @field_validator("code")
    @classmethod
    def code_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("code must not be blank")
        return value


__all__ = [
    "DetectionMethod",
    "LanguageDetection",
    "ProcessedInput",
    "RawInput",
    "SandboxExecution",
]
