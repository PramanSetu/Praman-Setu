from __future__ import annotations

from backend.agents.multi_issue_fixer import MultiIssueFixResponse
from backend.input_handler.models import RawInput
from backend.orchestrator.repair_v2 import repair_v2
from backend.orchestrator.state import DetectionMethod, LanguageDetection, ProcessedInput
from backend.tools.patch_applier import (
    CodeEdit,
    UnitRewrite,
    apply_exact_edits,
    apply_unit_rewrites,
)
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
            units=[UnitRewrite(target="f", new_source="def f():\n    return 1", reason="missing was undefined")],
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


# --- apply_unit_rewrites (AST splice) ---

_MOD = (
    "def a():\n    return undefined\n\n"
    "def b():\n    return 2\n\n"
    'if __name__ == "__main__":\n    print(a())\n    eval(input())\n'
)


def test_unit_rewrite_replaces_named_function_by_ast() -> None:
    result = apply_unit_rewrites(_MOD, [UnitRewrite(target="a", new_source="def a():\n    return 1")])

    assert result.applied_count == 1
    assert result.failures == []
    assert "return 1" in result.applied_code
    assert result.applied_code.count("def a(") == 1
    assert "def b():\n    return 2" in result.applied_code  # untouched


def test_unit_rewrite_replaces_trailing_module_block() -> None:
    result = apply_unit_rewrites(
        _MOD, [UnitRewrite(target="<module>", new_source='if __name__ == "__main__":\n    print(a())')]
    )

    assert result.applied_count == 1
    assert "eval(" not in result.applied_code
    assert "def a():" in result.applied_code  # functions preserved


def test_unit_rewrite_skips_unit_that_breaks_compilation() -> None:
    # Bad indentation in the new source must be dropped, leaving the file intact.
    result = apply_unit_rewrites(_MOD, [UnitRewrite(target="a", new_source="def a():\nreturn 1")])

    assert result.applied_count == 0
    assert "does not compile" in result.failures[0]
    assert result.applied_code == _MOD


def test_unit_rewrite_reports_unknown_target() -> None:
    result = apply_unit_rewrites(_MOD, [UnitRewrite(target="nope", new_source="def nope():\n    pass")])

    assert result.applied_count == 0
    assert "not a top-level function/class" in result.failures[0]


def test_unit_rewrite_whole_file_fixes_syntax_error() -> None:
    # The current code does not parse, so only a <file> unit can repair it.
    broken = "def f(x)\n    return x\n"
    result = apply_unit_rewrites(broken, [UnitRewrite(target="<file>", new_source="def f(x):\n    return x\n")])

    assert result.applied_count == 1
    assert result.failures == []
    assert "def f(x):" in result.applied_code


def test_unit_rewrite_requires_file_target_when_code_unparseable() -> None:
    broken = "def f(x)\n    return x\n"
    result = apply_unit_rewrites(broken, [UnitRewrite(target="f", new_source="def f(x):\n    return x")])

    assert result.applied_count == 0
    assert "SyntaxError" in result.failures[0]


class _CleanHandler:
    async def handle(self, request: RawInput):
        return _processed(request.code, "execution_clean")


async def test_repair_v2_neutralizes_background_thread_then_proceeds() -> None:
    code = (
        "import threading\n"
        "def worker():\n"
        "    while True:\n"
        "        pass\n"
        "for i in range(3):\n"
        "    threading.Thread(target=worker).start()\n"
    )
    result = await repair_v2(
        code, "app.py", handler=_CleanHandler(), fixer=Fixer(), security_scan=_secure, test_runner=_tests_pass
    )

    # Neutralized (daemonized) and validated rather than failing fast.
    assert "daemon=True" in result.final_code
    assert result.status == "clean"


class _ExplodingHandler:
    async def handle(self, request: RawInput):
        raise AssertionError("handler should not run when the blocker can't be neutralized")


async def test_repair_v2_fails_fast_when_cannot_neutralize() -> None:
    # threading imported + a top-level .start() on a non-Thread => can't daemonize.
    code = "import threading\nserver = make_server()\nserver.start()\n"
    result = await repair_v2(code, "app.py", handler=_ExplodingHandler(), fixer=Fixer())

    assert result.status == "unresolved"
    assert result.passes == 0
    assert "non-terminating" in (result.remaining_error or "").lower()
    assert result.final_code == code


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


async def test_repair_v2_emits_streamable_repair_events() -> None:
    events: list[tuple[str, dict]] = []

    async def collect(event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    result = await repair_v2(
        BUGGY,
        "main.py",
        handler=Handler(),
        fixer=Fixer(),
        security_scan=_secure,
        test_runner=_tests_pass,
        on_event=collect,
    )

    event_types = [event_type for event_type, _ in events]
    patch_events = [payload for event_type, payload in events if event_type == "patch"]

    assert result.status == "clean"
    assert "input" in event_types
    assert "ledger" in event_types
    assert "repair" in event_types
    assert "validation" in event_types
    assert patch_events[0]["code"] == FIXED
