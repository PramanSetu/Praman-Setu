"""Python-only one-file repair_v2 pipeline.

This is the product path for pasted Python files: build a deterministic bug
ledger, ask one Groq repair agent for exact edits, apply them deterministically,
then validate the whole file. It keeps the old single-bug graph available as a
fallback/diagnostic path without making it the primary repair strategy.
"""
from __future__ import annotations

import ast
from collections.abc import Awaitable, Callable
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from backend.agents.multi_issue_fixer import MultiIssueFixResponse, MultiIssueFixerAgent
from backend.input_handler.models import ProcessedInput, RawInput
from backend.input_handler.service import smart_input_handler
from backend.llm.client import llm_client
from backend.tools.bug_ledger import BugLedger, build_bug_ledger
from backend.tools.diff_regression import scan_code
from backend.tools.patch_applier import ApplyResult, apply_exact_edits
from backend.tools.sandbox.executor import SandboxResult
from backend.tools.sandbox.pool import sandbox_pool


class InputHandler(Protocol):
    async def handle(self, request: RawInput) -> ProcessedInput: ...


class Fixer(Protocol):
    async def fix(
        self,
        code: str,
        ledger: BugLedger,
        *,
        validation_feedback: str = "",
    ) -> MultiIssueFixResponse: ...


SecurityScan = Callable[[str], Awaitable[list[str]]]
TestRunner = Callable[[str, str], Awaitable[SandboxResult]]


class RepairAttempt(BaseModel):
    pass_number: int
    summary: str
    issues_found: list[str] = Field(default_factory=list)
    applied_edits: int
    edit_failures: list[str] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    confidence: float


class RepairV2Result(BaseModel):
    status: Literal["clean", "unresolved", "no_progress", "insecure"]
    passes: int
    original_code: str
    final_code: str
    ledger: BugLedger
    attempts: list[RepairAttempt] = Field(default_factory=list)
    remaining_error: str | None = None


async def _security_scan(code: str) -> list[str]:
    scan = await scan_code(code)
    return [
        f"{finding.rule} ({finding.severity}) at line {finding.line}"
        for finding in scan.findings
        if finding.severity in {"HIGH", "MEDIUM"}
    ]


async def _run_generated_tests(code: str, tests: str) -> SandboxResult:
    test_code = code + "\n\n" + tests
    return await sandbox_pool.execute(
        language="python",
        code=test_code,
        cmd=["pytest", "main.py", "-q", "-p", "no:cacheprovider", "--tb=short"],
        timeout=15,
    )


async def repair_v2(
    code: str,
    filename: str | None = None,
    *,
    max_passes: int = 3,
    handler: InputHandler = smart_input_handler,
    fixer: Fixer | None = None,
    security_scan: SecurityScan | None = None,
    test_runner: TestRunner | None = None,
) -> RepairV2Result:
    agent = fixer or MultiIssueFixerAgent(llm_client)
    scan = security_scan or _security_scan
    run_tests = test_runner or _run_generated_tests
    current = code
    attempts: list[RepairAttempt] = []
    feedback = ""
    latest_processed: ProcessedInput | None = None
    latest_ledger: BugLedger | None = None

    for pass_number in range(1, max_passes + 1):
        latest_processed = await handler.handle(RawInput(code=current, filename=filename))
        latest_ledger = build_bug_ledger(current, latest_processed)

        if latest_processed.status == "execution_clean":
            security = await scan(current)
            if not security:
                return _result("clean", pass_number - 1, code, current, latest_ledger, attempts)
            feedback = "Security scan failed: " + "; ".join(security)

        response = await agent.fix(current, latest_ledger, validation_feedback=feedback)
        apply_result = apply_exact_edits(current, response.edits)
        validation_errors: list[str] = list(apply_result.failures)

        if apply_result.applied_code.strip() == current.strip():
            attempts.append(_attempt(pass_number, response, apply_result, ["no code change produced"]))
            return _result(
                "no_progress",
                pass_number,
                code,
                current,
                latest_ledger,
                attempts,
                remaining="no code change produced",
            )

        validation_errors.extend(
            await _validate_candidate(
                apply_result.applied_code,
                filename,
                handler,
                scan,
                run_tests,
                response.generated_tests,
            )
        )
        attempts.append(_attempt(pass_number, response, apply_result, validation_errors))

        current = apply_result.applied_code
        if not validation_errors:
            final_processed = await handler.handle(RawInput(code=current, filename=filename))
            final_ledger = build_bug_ledger(current, final_processed)
            return _result("clean", pass_number, code, current, final_ledger, attempts)

        feedback = "\n".join(validation_errors)

    final_processed = await handler.handle(RawInput(code=current, filename=filename))
    final_ledger = build_bug_ledger(current, final_processed)
    if final_processed.status == "execution_clean":
        security = await scan(current)
        if security:
            return _result("insecure", max_passes, code, current, final_ledger, attempts, remaining="; ".join(security))
        return _result("clean", max_passes, code, current, final_ledger, attempts)
    return _result(
        "unresolved",
        max_passes,
        code,
        current,
        final_ledger,
        attempts,
        remaining=final_processed.error_message or final_processed.error_type,
    )


async def _validate_candidate(
    code: str,
    filename: str | None,
    handler: InputHandler,
    security_scan: SecurityScan,
    test_runner: TestRunner,
    generated_tests: str,
) -> list[str]:
    errors: list[str] = []
    try:
        ast.parse(code)
    except SyntaxError as exc:
        errors.append(f"compile failed at line {exc.lineno}: {exc.msg}")
        return errors

    processed = await handler.handle(RawInput(code=code, filename=filename))
    if processed.status == "execution_timeout":
        errors.append("execution timed out")
    elif processed.status != "execution_clean":
        errors.append(
            f"execution failed: {processed.error_type or 'error'} at line "
            f"{processed.error_line}: {processed.error_message}"
        )

    security = await security_scan(code)
    if security:
        errors.append("security scan failed: " + "; ".join(security))

    if generated_tests.strip():
        test_result = await test_runner(code, generated_tests)
        if test_result.exit_code != 0 or test_result.timed_out:
            errors.append("generated tests failed: " + (test_result.stdout or test_result.stderr).strip()[:1000])

    return errors


def _attempt(
    pass_number: int,
    response: MultiIssueFixResponse,
    apply_result: ApplyResult,
    validation_errors: list[str],
) -> RepairAttempt:
    return RepairAttempt(
        pass_number=pass_number,
        summary=response.summary,
        issues_found=response.issues_found,
        applied_edits=apply_result.applied_count,
        edit_failures=apply_result.failures,
        validation_errors=validation_errors,
        confidence=response.confidence,
    )


def _result(
    status: Literal["clean", "unresolved", "no_progress", "insecure"],
    passes: int,
    original: str,
    final: str,
    ledger: BugLedger,
    attempts: list[RepairAttempt],
    *,
    remaining: str | None = None,
) -> RepairV2Result:
    return RepairV2Result(
        status=status,
        passes=passes,
        original_code=original,
        final_code=final,
        ledger=ledger,
        attempts=attempts,
        remaining_error=remaining,
    )
