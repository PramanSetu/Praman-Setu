from __future__ import annotations

import asyncio

from backend.input_handler.models import (
    DetectionMethod,
    LanguageDetection,
    ProcessedInput,
)
from backend.orchestrator.state import ContextPackage
from backend.tools.context_builder import ContextBuilder


def _processed_input(
    code: str,
    *,
    error_type: str | None = "ZeroDivisionError",
    error_message: str = "ZeroDivisionError: division by zero",
    error_line: int | None = 5,
    raw_stderr: str = "Traceback...\nZeroDivisionError: division by zero",
    captured_variables: bool = False,
    crash_locals: dict[str, str] | None = None,
    trace_snapshots: list[dict] | None = None,
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
        captured_variables=captured_variables,
        crash_locals=crash_locals,
        trace_snapshots=trace_snapshots or [],
    )


def test_context_builder_does_not_execute_code() -> None:
    # No sandbox is injected or used: the Context Builder is purely deterministic
    # AST work over the handler's already-gathered evidence.
    builder = ContextBuilder()
    assert not hasattr(builder, "sandbox")


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
    raw_stderr = (
        'Traceback (most recent call last):\n  File "user_code.py", line 7, in <module>\n'
        '  File "user_code.py", line 5, in divide\n    return a / b\n'
        "ZeroDivisionError: division by zero"
    )

    package = asyncio.run(
        ContextBuilder().build(_processed_input(code, raw_stderr=raw_stderr))
    )

    assert isinstance(package, ContextPackage)
    assert package.language == "python"
    assert package.error_node == code
    assert package.function_signature == "def divide(a, b):"
    assert package.imports == ["import os", "from math import sqrt"]
    assert package.runtime_trace == {
        "error_type": "ZeroDivisionError",
        "error_message": "division by zero",  # type prefix stripped
        "error_line": 5,
        "raw_stderr": raw_stderr,
        "captured_variables": False,
        "crash_locals": None,
        "snapshots": [],
    }


def test_runtime_trace_carries_captured_variables() -> None:
    code = "def divide(a, b):\n    return a / b\n\ndivide(1, 0)"
    snapshots = [{"line": 2, "locals": {"a": "1", "b": "0"}}]

    package = asyncio.run(
        ContextBuilder().build(
            _processed_input(
                code,
                error_line=2,
                captured_variables=True,
                crash_locals={"a": "1", "b": "0"},
                trace_snapshots=snapshots,
            )
        )
    )

    assert package.runtime_trace["captured_variables"] is True
    assert package.runtime_trace["crash_locals"] == {"a": "1", "b": "0"}
    assert package.runtime_trace["snapshots"] == snapshots


def test_enriches_same_file_context_for_method_error() -> None:
    code = "\n".join(
        [
            "DEFAULT_DOMAIN = 'example.com'",
            "",
            "def normalize_email(value):",
            "    return value.strip().lower()",
            "",
            "def send_welcome_email(user):",
            "    return user.email",
            "",
            "class UserService:",
            "    cache_enabled = True",
            "",
            "    def get_email(self, user):",
            "        return normalize_email(user.email)",
            "",
            "    def build_profile(self, user):",
            "        return {'email': self.get_email(user)}",
        ]
    )

    package = asyncio.run(ContextBuilder().build(_processed_input(code, error_line=13)))

    assert "class UserService:" in (package.enclosing_class or "")
    assert "def get_email(self, user):" in (package.enclosing_class or "")
    assert "def build_profile(self, user):" in (package.enclosing_class_source or "")
    assert "return {'email': self.get_email(user)}" in (package.enclosing_class_source or "")
    assert package.constants == ["DEFAULT_DOMAIN = 'example.com'"]
    assert any("def normalize_email(value):" in callee for callee in package.callees)
    assert any("def build_profile(self, user):" in caller for caller in package.callers)
    assert "13 |         return normalize_email(user.email)" in package.error_window_with_lines


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

    package = asyncio.run(ContextBuilder().build(_processed_input(code, error_line=5)))

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

    package = asyncio.run(ContextBuilder().build(_processed_input(code, error_line=4)))

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

    package = asyncio.run(
        ContextBuilder().build(
            _processed_input(
                code,
                error_type="SyntaxError",
                error_message="SyntaxError: invalid syntax",
                error_line=4,
                raw_stderr='  File "user_code.py", line 4\nSyntaxError: invalid syntax',
            )
        )
    )

    assert package.function_signature == "def broken(value):"
    assert package.imports == ["import os"]
    assert package.runtime_trace["error_type"] == "SyntaxError"
    assert package.runtime_trace["error_message"] == "invalid syntax"


def test_error_node_is_bounded_to_ten_lines() -> None:
    code = "\n".join(f"line_{index}" for index in range(1, 21))

    package = asyncio.run(
        ContextBuilder().build(
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

    package = asyncio.run(
        ContextBuilder().build(
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
