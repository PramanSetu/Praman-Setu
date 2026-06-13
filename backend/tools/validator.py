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
from backend.tools.diff_regression import ScanResult, safety_diff_against_original, scan_code
from backend.tools.sandbox.pool import sandbox_pool
from backend.tools.test_quality import generated_test_failure

logger = logging.getLogger(__name__)

_PY_LANGUAGE = Language(tree_sitter_python.language())

_ORIG_MYPY_CACHE: dict[int, list[str]] = {}

# Per-patched-module bandit scan cache.
# Key: hash(patched_module_source).  Value: ScanResult returned by scan_code.
# Bandit results are deterministic for identical source, so this is safe to
# cache for the lifetime of the process.  Keyed on the full patched module
# (not just the function) to account for import-level changes.
_PATCHED_SCAN_CACHE: dict[int, ScanResult] = {}

def _parse_mypy_errors(output: str) -> list[str]:
    errors = []
    for line in output.splitlines():
        if "error:" in line:
            errors.append(line[line.find("error:"):].strip())
    return errors


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
# Kept here for reference; the canonical set lives in test_module_constructor.
_LOCAL_MODULES = {"user_code", "main", "solution", "snippet"}

# ---------------------------------------------------------------------------
# Test module construction — delegates to the AST-based constructor
# ---------------------------------------------------------------------------
# build_test_module is re-exported here so callers (tests, smoke scripts)
# that import it from validator continue to work.
from backend.tools.test_module_constructor import build_test_module  # noqa: E402


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

    test_failure = generated_test_failure(diagnoser_output.generated_test)
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

    # Run original mypy if needed
    original_module = context_package.full_code or context_package.function_source or context_package.error_node
    code_hash = hash(original_module)
    if code_hash not in _ORIG_MYPY_CACHE:
        orig_mypy_res = await sandbox_pool.execute(
            language="python",
            code=original_module,
            cmd=["mypy", "--ignore-missing-imports", "--no-incremental", "--no-error-summary", "main.py"],
            timeout=15,
        )
        _ORIG_MYPY_CACHE[code_hash] = _parse_mypy_errors(orig_mypy_res.stdout or orig_mypy_res.stderr or "")
    
    old_mypy_errors = _ORIG_MYPY_CACHE[code_hash]

    # Gates 2-4 in parallel.
    # Bandit (Gate 3 / Gate 5 input) is cached per patched module hash so that
    # reflector retries re-submitting the same patch don't spin up a new sandbox.
    test_module = build_test_module(patched_module, diagnoser_output.generated_test)
    g_start = time.time()

    patched_hash = hash(patched_module)
    if patched_hash in _PATCHED_SCAN_CACHE:
        cached_scan = _PATCHED_SCAN_CACHE[patched_hash]
        mypy_task = sandbox_pool.execute(
            language="python",
            code=patched_module,
            cmd=["mypy", "--ignore-missing-imports", "--no-incremental", "--no-error-summary", "main.py"],
            timeout=15,
        )
        pytest_task = sandbox_pool.execute(
            language="python",
            code=test_module,
            cmd=["pytest", "main.py", "-q", "-p", "no:cacheprovider", "--tb=short"],
            timeout=15,
        )
        mypy_res, pytest_res = await asyncio.gather(mypy_task, pytest_task)
        scan_res = cached_scan
    else:
        mypy_task = sandbox_pool.execute(
            language="python",
            code=patched_module,
            cmd=["mypy", "--ignore-missing-imports", "--no-incremental", "--no-error-summary", "main.py"],
            timeout=15,
        )
        # Run the scan as its own task (different return type) so gather doesn't
        # widen everything to ``object``; still concurrent with mypy + pytest.
        scan_future = asyncio.ensure_future(scan_code(patched_module))
        pytest_task = sandbox_pool.execute(
            language="python",
            code=test_module,
            cmd=["pytest", "main.py", "-q", "-p", "no:cacheprovider", "--tb=short"],
            timeout=15,
        )
        mypy_res, pytest_res = await asyncio.gather(mypy_task, pytest_task)
        scan_res = await scan_future
        _PATCHED_SCAN_CACHE[patched_hash] = scan_res

    new_mypy_errors = _parse_mypy_errors(mypy_res.stdout or mypy_res.stderr or "")
    introduced_mypy = len(set(new_mypy_errors) - set(old_mypy_errors))

    # Gate 2 — type check (non-blocking, informational only)
    g2_passed = True
    g2_msg = f"type check: {len(old_mypy_errors)} pre-existing issues, {introduced_mypy} new issues introduced"
    gate_results["gate_2"] = GateResult(
        passed=g2_passed,
        error=g2_msg,
        duration_s=time.time() - g_start,
    )

    # Gate 5 — diff regression (full original vs patched)
    g5_start = time.time()
    safety_diff = await safety_diff_against_original(original_module, scan_res.findings)
    g5_passed = safety_diff.verdict != "regression"
    gate_results["gate_5"] = GateResult(
        passed=g5_passed,
        error=None if g5_passed else "new HIGH/MEDIUM security finding introduced",
        duration_s=time.time() - g5_start,
    )

    # Gate 3 — security absolute floor: any HIGH severity finding in the patched
    # code is rejected, regardless of whether it pre-existed in the original.
    # Gate 5 (diff regression) handles the "newly introduced" angle separately.
    patched_high = [f for f in scan_res.findings if f.severity == "HIGH"]
    g3_passed = not patched_high
    g3_notes = []
    if patched_high:
        g3_notes.append("HIGH severity: " + ", ".join(f.rule for f in patched_high))
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
