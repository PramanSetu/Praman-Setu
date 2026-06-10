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
from backend.tools.sandbox.pool import SandboxPool, sandbox_pool


class SmartInputHandler:
    def __init__(self, sandbox: SandboxPool = sandbox_pool) -> None:
        self._sandbox = sandbox

    async def handle(self, request: RawInput) -> ProcessedInput:
        detection = detect_python_language(request.code, request.filename)
        line_count = len(request.code.splitlines()) or 1

        execution: SandboxExecution | None = None
        raw_error = _blank_to_none(request.error_message) or ""
        status = "ready"

        if not raw_error:
            sandbox_result = await self._sandbox.execute(detection.language, request.code)
            execution = SandboxExecution.model_validate(sandbox_result.model_dump())
            if sandbox_result.timed_out:
                status = "execution_timeout"
                raw_error = sandbox_result.stderr or "sandbox: timed out"
            elif sandbox_result.exit_code == 0:
                status = "execution_clean"
            else:
                status = "execution_failed"
                raw_error = sandbox_result.stderr or sandbox_result.stdout

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
        )


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


smart_input_handler = SmartInputHandler()
