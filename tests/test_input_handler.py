from __future__ import annotations

import asyncio

import pytest

from backend.input_handler import RawInput, SmartInputHandler
from backend.input_handler.classifier import (
    extract_error_line,
    extract_error_type,
    extract_exception_line,
    is_fast_path_eligible,
)
from backend.input_handler.detector import (
    UnsupportedLanguageError,
    detect_python_language,
    is_python_by_ast,
)
from backend.tools.sandbox.executor import SandboxResult


class FakeSandbox:
    def __init__(self, result: SandboxResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    async def execute(self, language: str, code: str, cmd=None, timeout=None) -> SandboxResult:
        self.calls.append((language, code))
        return self.result


def test_detects_python_by_extension() -> None:
    detection = detect_python_language("print('ok')", "main.py")

    assert detection.language == "python"
    assert detection.method == "extension"


def test_rejects_blank_code_at_request_boundary() -> None:
    with pytest.raises(ValueError):
        RawInput(code="   \n")


def test_rejects_known_non_python_extension() -> None:
    with pytest.raises(UnsupportedLanguageError):
        detect_python_language("console.log('nope')", "app.ts")


def test_detects_python_by_shebang() -> None:
    detection = detect_python_language("#!/usr/bin/env python3\nprint('ok')")

    assert detection.language == "python"
    assert detection.method == "shebang"


def test_rejects_unlabeled_syntax_invalid_input() -> None:
    with pytest.raises(UnsupportedLanguageError):
        detect_python_language("def broken(:\n    pass")


def test_ast_detection_returns_false_for_syntax_errors() -> None:
    assert is_python_by_ast("def broken(:\n    pass") is False
    assert is_python_by_ast("print('ok')") is True


def test_fast_path_eligibility_is_metadata_only() -> None:
    assert is_fast_path_eligible("NameError", line_count=1) is True
    assert is_fast_path_eligible("SyntaxError", line_count=49) is True
    assert is_fast_path_eligible("ZeroDivisionError", line_count=1) is False


def test_no_fast_path_for_long_snippet() -> None:
    assert is_fast_path_eligible("SyntaxError", line_count=50) is False


def test_extracts_last_traceback_error_type() -> None:
    error = "During handling...\nValueError: bad\n\nTraceback...\nNameError: name x is not defined"

    assert extract_error_type(error) == "NameError"


def test_extracts_exception_message_and_line() -> None:
    error = (
        'Traceback (most recent call last):\n  File "main.py", line 2, in <module>\n'
        "    print(1 / 0)\nZeroDivisionError: division by zero"
    )

    assert extract_exception_line(error) == "ZeroDivisionError: division by zero"
    assert extract_error_line(error) == 2


def test_uses_supplied_error_without_executing_sandbox() -> None:
    sandbox = FakeSandbox(
        SandboxResult(exit_code=0, stdout="", stderr="", timed_out=False, duration_s=0.01)
    )
    handler = SmartInputHandler(sandbox=sandbox)  # type: ignore[arg-type]

    result = asyncio.run(
        handler.handle(
            RawInput(
                code="print(missing)", filename="main.py", error_message="NameError: missing"
            )
        )
    )

    assert sandbox.calls == []
    assert result.status == "ready"
    assert result.error_type == "NameError"
    assert result.error_message == "NameError: missing"
    assert result.fast_path_eligible is True


def test_auto_executes_when_error_is_missing() -> None:
    sandbox = FakeSandbox(
        SandboxResult(
            exit_code=1,
            stdout="",
            stderr="NameError: name 'missing' is not defined",
            timed_out=False,
            duration_s=0.02,
        )
    )
    handler = SmartInputHandler(sandbox=sandbox)  # type: ignore[arg-type]

    result = asyncio.run(handler.handle(RawInput(code="print(missing)", filename="main.py")))

    assert sandbox.calls == [("python", "print(missing)")]
    assert result.status == "execution_failed"
    assert result.error_message == "NameError: name 'missing' is not defined"
    assert result.raw_stderr == "NameError: name 'missing' is not defined"
    assert result.error_type == "NameError"
    assert result.fast_path_eligible is True
