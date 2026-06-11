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

class GateResult(BaseModel):
    passed: bool
    error: str | None
    duration_s: float

class SafetyFinding(BaseModel):
    rule: str
    severity: str
    line: int | None

class SafetyDiff(BaseModel):
    introduced: list[SafetyFinding]
    fixed: list[SafetyFinding]
    verdict: Literal["improvement", "neutral", "regression", "tradeoff"]

class ValidatorReport(BaseModel):
    overall_passed: bool
    gate_results: dict[str, GateResult]
    safety_diff: SafetyDiff | None
    summary: str
    detailed_failures: list[str]

class ReflectorDecision(BaseModel):
    strategy: Literal["refine_current", "escalate_h2", "escalate_h3", "give_up"]
    failure_root_cause: str
    constraint_for_next_attempt: str
    confidence_in_strategy: float
    abandoning_hypothesis: str | None
    new_hypothesis_to_try: str | None

class PipelineState(BaseModel):
    raw_input: ProcessedInput
    language: str
    context_package: ContextPackage | None = None
    diagnoser_output: DiagnoserOutput | None = None
    patcher_output: PatcherOutput | None = None
    validator_report: ValidatorReport | None = None
    reflector_decision: ReflectorDecision | None = None
    retry_count: int = 0
    failed_hypotheses: list[str] = Field(default_factory=list)
    human_review_flag: bool = False
    hypothesis_used: str = "H1"
