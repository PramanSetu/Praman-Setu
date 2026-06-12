"""Deterministic quality check for an LLM-generated pytest test.

Shared by the Diagnoser (self-check at generation, so a malformed test triggers a
re-diagnosis instead of dead-ending the patch-only retry loop) and the Validator
(Gate 4 pre-check).
"""
from __future__ import annotations

import ast


def generated_test_failure(generated_test: str) -> str | None:
    """Return a reason string if the test is unusable, else None."""
    if not generated_test.strip():
        return "generated test is empty"
    try:
        module = ast.parse(generated_test)
    except SyntaxError as exc:
        return f"generated test has invalid syntax: {exc.msg}"

    has_test_function = any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
        for node in ast.walk(module)
    )
    if not has_test_function:
        return "generated test must define a test_ function"
    if not _has_assertion_or_pytest_raises(module):
        return "generated test must contain an assert or pytest.raises"
    return None


def _has_assertion_or_pytest_raises(module: ast.Module) -> bool:
    for node in ast.walk(module):
        if isinstance(node, ast.Assert):
            return True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "raises"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "pytest"
        ):
            return True
    return False
