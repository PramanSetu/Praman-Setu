"""Holistic fixing: fix the whole file, verify by running + a security gate.

Far fewer LLM calls than the per-bug loop (1-3 total), so it doesn't hit rate
limits on a messy multi-bug file. Two proofs on the result:
  - the patched file RUNS CLEAN in the sandbox (crash bugs proven gone), and
  - it passes a BANDIT security scan (no HIGH/MEDIUM findings like eval/exec).
If a security issue remains, the file is re-fixed with explicit feedback.

What it does NOT prove: per-bug behavioral correctness (silent logic bugs) — that
needs the per-bug Patcher pipeline's generated tests.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from backend.agents.holistic_fixer import FixedBug, HolisticFixerAgent
from backend.input_handler.models import ProcessedInput, RawInput
from backend.input_handler.service import smart_input_handler
from backend.llm.client import llm_client
from backend.tools.diff_regression import scan_code

_BLOCKING_SEVERITIES = {"HIGH", "MEDIUM"}


class InputHandler(Protocol):
    async def handle(self, request: RawInput) -> ProcessedInput: ...


class Fixer(Protocol):
    async def fix(self, code: str, latest_error: str | None, error_line: int | None) -> Any: ...


SecurityScan = Callable[[str], Awaitable[list[str]]]


class HolisticResult(BaseModel):
    status: Literal["clean", "insecure", "unresolved", "no_progress"]
    passes: int
    original_code: str
    final_code: str
    bugs_fixed: list[FixedBug] = Field(default_factory=list)
    security_findings: list[str] = Field(default_factory=list)
    remaining_error: str | None = None


async def _real_security_scan(code: str) -> list[str]:
    """Bandit findings worth blocking on (HIGH/MEDIUM) as readable strings."""
    scan = await scan_code(code)
    return [
        f"{f.rule} ({f.severity}) at line {f.line}"
        for f in scan.findings
        if f.severity in _BLOCKING_SEVERITIES
    ]


def _dedupe(bugs: list[FixedBug]) -> list[FixedBug]:
    seen: set[tuple[int | None, str]] = set()
    out: list[FixedBug] = []
    for bug in bugs:
        key = (bug.line, bug.bug_type.lower())
        if key not in seen:
            seen.add(key)
            out.append(bug)
    return out


def _result(status, passes, code, final_code, bugs, *, security=None, remaining=None) -> HolisticResult:
    return HolisticResult(
        status=status, passes=passes, original_code=code, final_code=final_code,
        bugs_fixed=_dedupe(bugs), security_findings=security or [], remaining_error=remaining,
    )


async def holistic_fix(
    code: str,
    filename: str | None = None,
    *,
    max_passes: int = 3,
    handler: InputHandler = smart_input_handler,
    fixer: Fixer | None = None,
    security_scan: SecurityScan | None = None,
) -> HolisticResult:
    agent = fixer or HolisticFixerAgent(llm_client)
    scan = security_scan or _real_security_scan
    current = code
    all_bugs: list[FixedBug] = []
    passes = 0
    remaining_error: str | None = None

    findings: list[str] = []
    for _ in range(max_passes):
        processed = await handler.handle(RawInput(code=current, filename=filename))

        securing = False
        if processed.status == "execution_clean":
            findings = await scan(current)
            if not findings:
                return _result("clean", passes, code, current, all_bugs)
            # Runs clean but insecure → re-fix with explicit security feedback.
            securing = True
            error_for_fix: str | None = (
                "Remove these security issues — do NOT use eval/exec, handle inputs "
                "safely: " + "; ".join(findings)
            )
            error_line: int | None = None
        elif processed.status == "execution_timeout":
            remaining_error = "execution timed out"
            break
        else:
            remaining_error = processed.error_message or processed.error_type
            error_for_fix = processed.error_message
            error_line = processed.error_line

        try:
            response = await agent.fix(current, error_for_fix, error_line)
        except Exception as exc:
            remaining_error = f"fixer failed: {exc}"
            break
        passes += 1
        if not response.fixed_code.strip() or response.fixed_code.strip() == current.strip():
            # Stuck: can't remove the security issue, or can't fix the crash.
            if securing:
                return _result("insecure", passes, code, current, all_bugs, security=findings)
            return _result("no_progress", passes, code, current, all_bugs, remaining=remaining_error)
        current = response.fixed_code
        all_bugs.extend(response.bugs_fixed)

    # Final verdict: must run clean AND pass the security gate.
    final = await handler.handle(RawInput(code=current, filename=filename))
    if final.status == "execution_clean":
        findings = await scan(current)
        if not findings:
            return _result("clean", passes, code, current, all_bugs)
        return _result("insecure", passes, code, current, all_bugs, security=findings)
    return _result("unresolved", passes, code, current, all_bugs,
                   remaining=final.error_message or remaining_error)
