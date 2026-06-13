from __future__ import annotations

from backend.orchestrator.state import DetectionMethod, LanguageDetection, ProcessedInput
from backend.tools.bug_ledger import build_bug_ledger


def _processed(code: str, error_type: str | None = None, line: int | None = None) -> ProcessedInput:
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
        status="execution_failed" if error_type else "execution_clean",
    )


def test_ledger_records_syntax_error_without_ast_inventory() -> None:
    ledger = build_bug_ledger("def broken(:\n    pass")

    assert ledger.code_compiles is False
    assert ledger.runtime_error_type == "SyntaxError"
    assert any(issue.kind == "syntax" for issue in ledger.issues)
    assert ledger.functions == []


def test_ledger_records_runtime_and_script_structure() -> None:
    code = "\n".join(
        [
            "import math",
            "",
            "def f():",
            "    return missing + 1",
            "",
            "name = input('name: ')",
            "print(f())",
        ]
    )

    ledger = build_bug_ledger(code, _processed(code, "NameError", 4))

    assert ledger.code_compiles is True
    assert ledger.runtime_error_type == "NameError"
    assert ledger.functions[0].name == "f"
    assert ledger.imports == ["import math"]
    assert 6 in ledger.top_level_input_lines
    assert 6 in ledger.top_level_executable_lines
    assert 7 in ledger.top_level_executable_lines
    assert any(issue.kind == "undefined_name_hint" and issue.symbol == "missing" for issue in ledger.issues)


def test_ledger_does_not_flag_builtin_or_local_names_as_undefined() -> None:
    code = "def total(values):\n    count = len(values)\n    return sum(values) / count"

    ledger = build_bug_ledger(code)

    assert not [issue for issue in ledger.issues if issue.kind == "undefined_name_hint"]
