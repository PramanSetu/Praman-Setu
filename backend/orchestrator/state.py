"""Typed contracts shared across the Phase 1 pipeline."""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# Single source of truth for the handler's pipeline status values.
ProcessedStatus = Literal["ready", "execution_clean", "execution_failed", "execution_timeout"]


class DetectionMethod(str, Enum):
    EXTENSION = "extension"
    SHEBANG = "shebang"
    AST_PARSE = "ast_parse"


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
    status: ProcessedStatus
    # Execution-tracer evidence (Context Builder Subtask A). Empty when the user
    # supplied the error and we did not execute, or for tier-degraded runs.
    captured_variables: bool = False
    crash_locals: dict[str, str] | None = None
    trace_snapshots: list[dict[str, Any]] = Field(default_factory=list)


class ContextPackage(BaseModel):
    error_node: str
    function_signature: str
    imports: list[str]
    runtime_trace: dict[str, Any]
    language: Literal["python"]


class Hypothesis(BaseModel):
    id: str
    theory: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    fix_direction: str = Field(min_length=1)


class DiagnoserOutput(BaseModel):
    root_cause: str = Field(min_length=1)
    hypotheses: list[Hypothesis] = Field(min_length=3, max_length=3)
    generated_test: str = Field(min_length=1)


class PatcherOutput(BaseModel):
    unified_diff: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    approach: str = Field(min_length=1)
