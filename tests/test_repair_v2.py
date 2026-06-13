from __future__ import annotations

from backend.agents.multi_issue_fixer import MultiIssueFixResponse
from backend.input_handler.models import RawInput
from backend.orchestrator.repair_v2 import repair_v2
from backend.orchestrator.state import DetectionMethod, LanguageDetection, ProcessedInput
from backend.tools.patch_applier import CodeEdit, apply_exact_edits
from backend.tools.sandbox.executor import SandboxResult


BUGGY = "def f():\n    return missing\n\nprint(f())"
FIXED = "def f():\n    return 1\n\nprint(f())"


def _processed(code: str, status: str, error_type: str | None = None, line: int | None = None) -> ProcessedInput:
    return ProcessedInput(
        language="python",
        detection=LanguageDetection(
            language="python",
            confidence=1.0,
            method=DetectionMethod.EXTENSION,
            reason="test",
        ),
        filename="main.py",
        code=code,
        line_count=len(code.splitlines()),
        supplied_error_message=False,
        error_message=f"{error_type}: boom" if error_type else "",
        error_type=error_type,
        error_line=line,
        raw_stderr="",
        fast_path_eligible=False,
        execution=None,
        status=status,  # type: ignore[arg-type]
    )


class Handler:
    async def handle(self, request: RawInput):
        if request.code == FIXED:
            return _processed(request.code, "execution_clean")
        return _processed(request.code, "execution_failed", "NameError", 2)


class Fixer:
    async def fix(self, code, ledger, *, validation_feedback=""):
        return MultiIssueFixResponse(
            summary="fixed undefined name",
            issues_found=[issue.message for issue in ledger.issues],
            edits=[CodeEdit(old="return missing", new="return 1", reason="missing was undefined")],
            generated_tests="",
            confidence=0.9,
        )


async def _secure(code: str) -> list[str]:
    return []


async def _tests_pass(code: str, tests: str) -> SandboxResult:
    return SandboxResult(exit_code=0, stdout="", stderr="", timed_out=False, duration_s=0.01)


def test_exact_edit_applier_rejects_ambiguous_blocks() -> None:
    result = apply_exact_edits("x = 1\nx = 1", [CodeEdit(old="x = 1", new="x = 2")])

    assert result.applied_count == 0
    assert "matched 2 locations" in result.failures[0]


async def test_repair_v2_applies_exact_edits_and_validates_clean() -> None:
    result = await repair_v2(
        BUGGY,
        "main.py",
        handler=Handler(),
        fixer=Fixer(),
        security_scan=_secure,
        test_runner=_tests_pass,
    )

    assert result.status == "clean"
    assert result.final_code == FIXED
    assert result.attempts[0].applied_edits == 1
    assert result.ledger.code_compiles is True
