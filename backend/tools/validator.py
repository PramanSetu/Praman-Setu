"""Tool 3 — the deterministic 5-gate Validator.

Validates the Patcher's *complete patched code* directly (no diff round-trip),
spliced back into the full original module so every gate runs against a runnable
file. All execution happens inside the hardened sandbox.

Gate 1: syntax (tree-sitter)         — fail-fast
Gates 2-4 in parallel:
  Gate 2: type check (mypy)
  Gate 3: security scan (bandit)      — fails on HIGH severity
  Gate 4: tests (pytest)              — generated test must pass
Gate 5: diff regression              — rejects newly-introduced HIGH/MEDIUM findings
"""
from __future__ import annotations

import ast
import asyncio
import logging
import time

import tree_sitter_python
from tree_sitter import Language, Parser

from backend.orchestrator.state import (
    ContextPackage,
    DiagnoserOutput,
    GateResult,
    PatcherOutput,
    ValidatorReport,
)
from backend.tools.diff_regression import safety_diff_against_original, scan_code
from backend.tools.sandbox.pool import sandbox_pool

logger = logging.getLogger(__name__)

_PY_LANGUAGE = Language(tree_sitter_python.language())


def _fail_report(summary: str, gate: str, detail: str, elapsed: float) -> ValidatorReport:
    return ValidatorReport(
        overall_passed=False,
        gate_results={gate: GateResult(passed=False, error=detail, duration_s=elapsed)},
        safety_diff=None,
        summary=summary,
        detailed_failures=[detail],
    )


# The tracer runs user code under this virtual filename, so the LLM-generated test
# often writes `from user_code import ...`. The function is in the same test file,
# so that import is both redundant and unresolvable — strip it.
_LOCAL_MODULES = {"user_code", "main", "solution", "snippet"}


def _strip_top_level_calls(code: str) -> str:
    """Drop module-level bare calls (the original crash reproduction)."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code
    tree.body = [
        node
        for node in tree.body
        if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call))
    ]
    return ast.unparse(tree)


def _strip_local_imports(code: str) -> str:
    """Drop imports of the function-under-test from its own (same-file) module."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code
    body = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module in _LOCAL_MODULES:
            continue
        if isinstance(node, ast.Import) and any(a.name in _LOCAL_MODULES for a in node.names):
            continue
        body.append(node)
    tree.body = body
    return ast.unparse(tree)


def _ensure_pytest_import(code: str) -> str:
    """Prepend `import pytest` when the test uses it but forgot to import it.

    The LLM frequently writes `pytest.raises(...)` without `import pytest`, which
    fails at runtime with NameError. Adding the import makes the test runnable.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code
    uses_pytest = any(isinstance(n, ast.Name) and n.id == "pytest" for n in ast.walk(tree))
    has_import = any(
        isinstance(n, ast.Import) and any(a.name == "pytest" for a in n.names)
        for n in ast.walk(tree)
    )
    if uses_pytest and not has_import:
        return "import pytest\n" + code
    return code


def build_test_module(patched_module: str, generated_test: str) -> str:
    """Module the test runs against.

    Drops the original's top-level crash reproduction (so importing the file for
    pytest doesn't re-raise the bug at collection time), strips the generated
    test's redundant self-import of the function under test, and ensures pytest is
    imported when the test relies on it.
    """
    test = _ensure_pytest_import(_strip_local_imports(generated_test))
    return _strip_top_level_calls(patched_module) + "\n\n" + test


def splice_patched_module(
    context: ContextPackage,
    patched_function: str,
    patch_target_source: str = "",
) -> str:
    """Rebuild the full module with the patched function in place.

    Raises ValueError if the original target can't be located in the full module
    (so the Validator fails loudly instead of validating the wrong code).
    """
    target = patch_target_source or context.function_source or context.error_node
    full = context.full_code or target

    if target and target in full:
        return full.replace(target, patched_function, 1)
    if full == target or not context.full_code:
        # Module-level fix, or no full module available (unit fixtures).
        return patched_function
    raise ValueError("patched function source not found in original module")


async def run_validator(
    patcher_output: PatcherOutput,
    context_package: ContextPackage,
    diagnoser_output: DiagnoserOutput,
) -> ValidatorReport:
    start = time.time()

    patched_function = patcher_output.patched_code.strip()
    if not patched_function:
        return _fail_report("Patch missing", "gate_1", "patcher produced no patched_code", 0.0)

    try:
        patched_module = splice_patched_module(
            context_package,
            patched_function,
            patcher_output.patch_target_source,
        )
    except ValueError as exc:
        return _fail_report("Patch apply failed", "gate_1", str(exc), time.time() - start)

    error_type = context_package.runtime_trace.get("error_type")
    # A same-type raise is only a "cheat" when the test does NOT intend it. If the
    # generated test asserts pytest.raises(<that type>), raising it is the contract.
    test_expects_error = _test_expects_error_type(diagnoser_output.generated_test, error_type)
    guard_failure = _patch_guard_failure(
        patcher_output.patch_target_source
        or context_package.function_source
        or context_package.error_node,
        patched_function,
        error_type,
        test_expects_error,
    )
    if guard_failure:
        return _fail_report("Patch rejected", "gate_1", guard_failure, time.time() - start)

    # Gate 1 — syntax (fail-fast)
    tree = Parser(_PY_LANGUAGE).parse(patched_module.encode("utf8"))
    g1_time = time.time() - start
    if tree.root_node.has_error:
        return _fail_report("Gate 1 failed: syntax error", "gate_1", "syntax error in patched code", g1_time)
    gate_results = {"gate_1": GateResult(passed=True, error=None, duration_s=g1_time)}

    test_failure = _generated_test_guard_failure(diagnoser_output.generated_test)
    if test_failure:
        gate_results["gate_4"] = GateResult(
            passed=False,
            error=test_failure,
            duration_s=time.time() - start,
        )
        return ValidatorReport(
            overall_passed=False,
            gate_results=gate_results,
            safety_diff=None,
            summary="Generated test rejected",
            detailed_failures=[f"Gate 4 (pytest) failed: {test_failure}"],
        )

    # Gates 2-4 in parallel
    test_module = build_test_module(patched_module, diagnoser_output.generated_test)
    g_start = time.time()
    mypy_task = sandbox_pool.execute(
        language="python",
        code=patched_module,
        cmd=["mypy", "--ignore-missing-imports", "--no-incremental", "--no-error-summary", "main.py"],
        timeout=15,
    )
    scan_task = scan_code(patched_module)
    pytest_task = sandbox_pool.execute(
        language="python",
        code=test_module,
        cmd=["pytest", "main.py", "-q", "-p", "no:cacheprovider", "--tb=short"],
        timeout=15,
    )
    mypy_res, scan_res, pytest_res = await asyncio.gather(mypy_task, scan_task, pytest_task)

    # Gate 2 — type check
    g2_passed = mypy_res.exit_code == 0
    gate_results["gate_2"] = GateResult(
        passed=g2_passed,
        error=None if g2_passed else (mypy_res.stdout or mypy_res.stderr).strip()[:1000],
        duration_s=time.time() - g_start,
    )

    # Gate 3 — security (HIGH severity blocks; capture scanner errors)
    high = [f for f in scan_res.findings if f.severity == "HIGH"]
    g3_passed = not high
    g3_notes = []
    if high:
        g3_notes.append("HIGH severity: " + ", ".join(f.rule for f in high))
    g3_notes.extend(scan_res.errors)
    gate_results["gate_3"] = GateResult(
        passed=g3_passed,
        error="; ".join(g3_notes) or None,
        duration_s=time.time() - g_start,
    )

    # Gate 4 — tests
    g4_passed = pytest_res.exit_code == 0
    gate_results["gate_4"] = GateResult(
        passed=g4_passed,
        error=None if g4_passed else (pytest_res.stdout or pytest_res.stderr).strip()[:1000],
        duration_s=time.time() - g_start,
    )

    # Gate 5 — diff regression (full original vs patched)
    g5_start = time.time()
    original_module = context_package.full_code or context_package.function_source or context_package.error_node
    safety_diff = await safety_diff_against_original(original_module, scan_res.findings)
    g5_passed = safety_diff.verdict != "regression"
    gate_results["gate_5"] = GateResult(
        passed=g5_passed,
        error=None if g5_passed else "new HIGH/MEDIUM security finding introduced",
        duration_s=time.time() - g5_start,
    )

    overall = g2_passed and g3_passed and g4_passed and g5_passed
    detailed_failures = []
    if not g2_passed:
        detailed_failures.append(f"Gate 2 (mypy) failed: {gate_results['gate_2'].error}")
    if not g3_passed:
        detailed_failures.append(f"Gate 3 (security) failed: {gate_results['gate_3'].error}")
    if not g4_passed:
        detailed_failures.append(f"Gate 4 (pytest) failed: {gate_results['gate_4'].error}")
    if not g5_passed:
        detailed_failures.append("Gate 5 (diff regression) failed: security regression")

    return ValidatorReport(
        overall_passed=overall,
        gate_results=gate_results,
        safety_diff=safety_diff,
        summary="Passed" if overall else "Validation failed",
        detailed_failures=detailed_failures,
    )


def _patch_guard_failure(
    original_function: str,
    patched_function: str,
    original_error_type: str | None,
    test_expects_error_type: bool = False,
) -> str | None:
    if _normalize_code(original_function) == _normalize_code(patched_function):
        return "patch is identical to the original code"
    try:
        module = ast.parse(patched_function)
    except SyntaxError:
        return None

    if _is_only_stub_function(module):
        return "patch replaces the function with an empty stub"
    if _has_module_level_bare_call(module):
        return "patch target includes module-level executable calls"
    if _has_broad_exception_swallow(module):
        return "patch swallows broad exceptions without handling the root cause"
    if (
        original_error_type
        and not test_expects_error_type
        and _explicitly_raises_error_type(module, original_error_type)
    ):
        return f"patch explicitly raises the original runtime error {original_error_type}"
    return None


def _test_expects_error_type(generated_test: str, error_type: str | None) -> bool:
    """True if the generated test asserts ``pytest.raises(<error_type>)``.

    When it does, the contract intends that exception, so the Patcher raising it is
    correct — not a re-raise cheat.
    """
    if not error_type:
        return False
    try:
        module = ast.parse(generated_test)
    except SyntaxError:
        return False
    for node in ast.walk(module):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "raises"
        ):
            for arg in node.args:
                if isinstance(arg, ast.Name) and arg.id == error_type:
                    return True
    return False


def _generated_test_guard_failure(generated_test: str) -> str | None:
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


def _normalize_code(code: str) -> str:
    try:
        return ast.unparse(ast.parse(code)).strip()
    except SyntaxError:
        return "\n".join(line.rstrip() for line in code.strip().splitlines())


def _is_only_stub_function(module: ast.Module) -> bool:
    functions = [
        node for node in ast.walk(module) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    if not functions:
        return False
    for func in functions:
        body = [
            node
            for node in func.body
            if not (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            )
        ]
        if body and not all(isinstance(node, (ast.Pass, ast.Expr)) for node in body):
            return False
        if any(
            isinstance(node, ast.Expr)
            and not (isinstance(node.value, ast.Constant) and node.value.value is Ellipsis)
            for node in body
        ):
            return False
    return True


def _has_broad_exception_swallow(module: ast.Module) -> bool:
    for node in ast.walk(module):
        if not isinstance(node, ast.ExceptHandler):
            continue
        catches_broad = node.type is None or (
            isinstance(node.type, ast.Name) and node.type.id in {"Exception", "BaseException"}
        )
        body_only_pass = bool(node.body) and all(isinstance(child, ast.Pass) for child in node.body)
        if catches_broad and body_only_pass:
            return True
    return False


def _has_module_level_bare_call(module: ast.Module) -> bool:
    return any(isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) for node in module.body)


def _explicitly_raises_error_type(module: ast.Module, error_type: str) -> bool:
    """True only for an UNCONDITIONAL re-raise of the original error type.

    A bare `raise ZeroDivisionError(...)` as a direct statement of the function (or
    module) body is a non-fix. A GUARDED raise like `if b == 0: raise ZeroDivisionError`
    is a legitimate validation fix and is allowed — Gate 4's test decides if it's
    actually correct.
    """
    bodies: list[list[ast.stmt]] = [module.body]
    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bodies.append(node.body)

    for body in bodies:
        for stmt in body:
            if isinstance(stmt, ast.Raise) and _raises_named_type(stmt, error_type):
                return True
    return False


def _raises_named_type(node: ast.Raise, error_type: str) -> bool:
    if node.exc is None:
        return False
    exc = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
    return isinstance(exc, ast.Name) and exc.id == error_type


def _has_assertion_or_pytest_raises(module: ast.Module) -> bool:
    for node in ast.walk(module):
        if isinstance(node, ast.Assert):
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "raises" and isinstance(node.func.value, ast.Name):
                if node.func.value.id == "pytest":
                    return True
    return False
