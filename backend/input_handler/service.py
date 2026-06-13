"""Smart Input Handler orchestration."""
from __future__ import annotations

from backend.input_handler.classifier import (
    extract_error_line,
    extract_error_type,
    extract_exception_line,
    is_fast_path_eligible,
)
from backend.input_handler.detector import detect_python_language
from backend.input_handler.models import (
    ProcessedInput,
    RawInput,
    SandboxExecution,
)
from backend.orchestrator.state import ProcessedStatus
from backend.tools.sandbox.pool import sandbox_pool
from backend.tools.tracer import SandboxExecutor, trace_execution


class SmartInputHandler:
    def __init__(self, sandbox: SandboxExecutor = sandbox_pool) -> None:
        self._sandbox = sandbox

    async def handle(self, request: RawInput) -> ProcessedInput:
        detection = detect_python_language(request.code, request.filename, request.error_message)
        line_count = len(request.code.splitlines()) or 1

        execution: SandboxExecution | None = None
        raw_error = _blank_to_none(request.error_message) or ""
        status: ProcessedStatus = "ready"
        captured_variables = False
        crash_locals: dict[str, str] | None = None
        trace_snapshots: list[dict] = []

        # Only execute when the user did NOT supply an error (Mode B). This is the
        # system's single user-code run; the Context Builder consumes its output.
        if not raw_error:
            trace = await trace_execution(detection.language, request.code, self._sandbox)
            execution = SandboxExecution(
                exit_code=trace.exit_code,
                stdout=trace.stdout,
                stderr=trace.raw_stderr,
                timed_out=trace.timed_out,
                duration_s=trace.duration_s,
            )
            captured_variables = trace.captured_variables
            crash_locals = trace.crash_locals
            trace_snapshots = trace.snapshots
            if trace.timed_out:
                status = "execution_timeout"
                raw_error = trace.raw_stderr or "sandbox: timed out"
            elif trace.crashed:
                status = "execution_failed"
                raw_error = trace.raw_stderr
            else:
                status = "execution_clean"

        error_type = extract_error_type(raw_error) if raw_error else None

        return ProcessedInput(
            language=detection.language,
            detection=detection,
            filename=request.filename,
            code=request.code,
            line_count=line_count,
            supplied_error_message=request.error_message is not None,
            error_message=extract_exception_line(raw_error) if raw_error else "",
            error_type=error_type,
            error_line=extract_error_line(raw_error) if raw_error else None,
            raw_stderr=raw_error,
            fast_path_eligible=is_fast_path_eligible(error_type, line_count),
            execution=execution,
            status=status,
            captured_variables=captured_variables,
            crash_locals=crash_locals,
            trace_snapshots=trace_snapshots,
        )


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


smart_input_handler = SmartInputHandler()
