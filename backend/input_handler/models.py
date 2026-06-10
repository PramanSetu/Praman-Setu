"""Pydantic contracts for the Smart Input Handler."""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class DetectionMethod(str, Enum):
    EXTENSION = "extension"
    SHEBANG = "shebang"
    AST_PARSE = "ast_parse"


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


class LanguageDetection(BaseModel):
    language: Literal["python"]
    confidence: float = Field(ge=0, le=1)
    method: DetectionMethod
    reason: str


class SandboxExecution(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_s: float


class ProcessedInput(BaseModel):
    language: Literal["python"]
    detection: LanguageDetection
    filename: str | None
    code: str
    line_count: int
    supplied_error_message: bool
    error_message: str
    error_type: str | None
    error_line: int | None
    raw_stderr: str
    fast_path_eligible: bool
    execution: SandboxExecution | None
    status: Literal["ready", "execution_clean", "execution_failed", "execution_timeout"]
