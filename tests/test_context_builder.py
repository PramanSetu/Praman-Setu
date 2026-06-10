from __future__ import annotations

import asyncio

from backend.input_handler.models import (
    DetectionMethod,
    LanguageDetection,
    ProcessedInput,
)
from backend.orchestrator.state import ContextPackage
from backend.tools.context_builder import ContextBuilder
from backend.tools.sandbox.executor import SandboxResult


class FakeSandbox:
    def __init__(self, result: SandboxResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    async def execute(self, language: str, code: str, cmd=None, timeout=None) -> SandboxResult:
        self.calls.append((language, code))
        return self.result


def _sandbox(stderr: str, *, exit_code: int = 1, stdout: str = "") -> FakeSandbox:
    return FakeSandbox(
        SandboxResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            timed_out=False,
            duration_s=0.01,
        )
    )


def _processed_input(
    code: str,
    *,
    error_type: str | None = "ZeroDivisionError",
    error_message: str = "ZeroDivisionError: division by zero",
    error_line: int | None = 5,
    raw_stderr: str = "Traceback...\nZeroDivisionError: division by zero",
) -> ProcessedInput:
    return ProcessedInput(
        language="python",
        detection=LanguageDetection(
            language="python",
            confidence=0.99,
            method=DetectionMethod.EXTENSION,
            reason="test fixture",
        ),
        filename="main.py",
        code=code,
        line_count=len(code.splitlines()),
        supplied_error_message=True,
        error_message=error_message,
        error_type=error_type,
        error_line=error_line,
        raw_stderr=raw_stderr,
        fast_path_eligible=False,
        execution=None,
        status="ready",
    )


def test_builds_context_package_for_function_error() -> None:
    code = "\n".join(
        [
            "import os",
            "from math import sqrt",
            "",
            "def divide(a, b):",
            "    return a / b",
            "",
            "print(divide(1, 0))",
        ]
    )
    stderr = (
        'Traceback (most recent call last):\n  File "main.py", line 7, in <module>\n'
        '  File "main.py", line 5, in divide\n    return a / b\n'
        "ZeroDivisionError: division by zero"
    )
    sandbox = _sandbox(stderr)

    package = asyncio.run(ContextBuilder(sandbox=sandbox).build(_processed_input(code)))

    assert isinstance(package, ContextPackage)
    assert sandbox.calls == [("python", code)]
    assert package.language == "python"
    assert package.error_node == code
    assert package.function_signature == "def divide(a, b):"
    assert package.imports == ["import os", "from math import sqrt"]
    assert package.runtime_trace == {
        "error_type": "ZeroDivisionError",
        "error_message": "division by zero",
        "error_line": 5,
        "raw_stderr": stderr,
    }


def test_extracts_multiline_function_signature() -> None:
    code = "\n".join(
        [
            "def calculate(",
            "    numerator,",
            "    denominator,",
            "):",
            "    return numerator / denominator",
        ]
    )
    sandbox = _sandbox(
        'Traceback (most recent call last):\n  File "main.py", line 5, in calculate\n'
        "ZeroDivisionError: division by zero"
    )

    package = asyncio.run(ContextBuilder(sandbox=sandbox).build(_processed_input(code, error_line=5)))

    assert package.function_signature == "def calculate(\n    numerator,\n    denominator,\n):"


def test_extracts_top_level_imports_only() -> None:
    code = "\n".join(
        [
            "import os",
            "",
            "def load():",
            "    import sys",
            "    return sys.path",
        ]
    )
    sandbox = _sandbox(
        'Traceback (most recent call last):\n  File "main.py", line 4, in load\n'
        "NameError: name 'sys' is not defined"
    )

    package = asyncio.run(ContextBuilder(sandbox=sandbox).build(_processed_input(code, error_line=4)))

    assert package.imports == ["import os"]
    assert package.function_signature == "def load():"


def test_handles_broken_python_with_tree_sitter() -> None:
    code = "\n".join(
        [
            "import os",
            "",
            "def broken(value):",
            "    if value:",
            "        return value",
            "    return (",
        ]
    )
    sandbox = _sandbox('  File "main.py", line 6\nSyntaxError: invalid syntax')

    package = asyncio.run(
        ContextBuilder(sandbox=sandbox).build(
            _processed_input(
                code,
                error_type="SyntaxError",
                error_message="SyntaxError: invalid syntax",
                error_line=4,
                raw_stderr='  File "main.py", line 4\nSyntaxError: invalid syntax',
            )
        )
    )

    assert package.function_signature == "def broken(value):"
    assert package.imports == ["import os"]
    assert package.runtime_trace["error_type"] == "SyntaxError"
    assert package.runtime_trace["error_message"] == "invalid syntax"


def test_error_node_is_bounded_to_ten_lines() -> None:
    code = "\n".join(f"line_{index}" for index in range(1, 21))
    sandbox = _sandbox('Traceback...\n  File "main.py", line 12\nNameError: name x is not defined')

    package = asyncio.run(
        ContextBuilder(sandbox=sandbox).build(
            _processed_input(
                code,
                error_type="NameError",
                error_message="NameError: name 'x' is not defined",
                error_line=12,
            )
        )
    )

    assert package.error_node.splitlines() == [f"line_{index}" for index in range(7, 17)]
    assert package.function_signature == "<module-level>"


def test_defaults_missing_error_line_to_first_line_for_extraction() -> None:
    code = "print('ok')\nprint('still ok')"
    sandbox = _sandbox("", exit_code=0, stdout="ok\nstill ok\n")

    package = asyncio.run(
        ContextBuilder(sandbox=sandbox).build(
            _processed_input(
                code,
                error_type=None,
                error_message="",
                error_line=None,
                raw_stderr="",
            )
        )
    )

    assert package.error_node == code
    assert package.runtime_trace["error_line"] is None


def test_runtime_trace_parses_last_exception_line_and_last_file_line() -> None:
    code = "def fail():\n    return 1 / 0\n\nfail()"
    stderr = (
        'Traceback (most recent call last):\n  File "main.py", line 4, in <module>\n'
        '  File "main.py", line 2, in fail\n    return 1 / 0\n'
        "ZeroDivisionError: division by zero"
    )

    package = asyncio.run(
        ContextBuilder(sandbox=_sandbox(stderr)).build(
            _processed_input(
                code,
                error_type=None,
                error_message="",
                error_line=None,
                raw_stderr="",
            )
        )
    )

    assert package.runtime_trace == {
        "error_type": "ZeroDivisionError",
        "error_message": "division by zero",
        "error_line": 2,
        "raw_stderr": stderr,
    }
    assert package.function_signature == "def fail():"
