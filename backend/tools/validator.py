import asyncio
import tempfile
import subprocess
import os
import json
import time
import logging

import tree_sitter_python
from tree_sitter import Language, Parser

from backend.orchestrator.state import GateResult, ValidatorReport, SafetyDiff, SafetyFinding
from backend.tools.sandbox.pool import sandbox_pool
from backend.tools.diff_regression import run_security_scanners, get_safety_diff

logger = logging.getLogger(__name__)

def apply_diff(original_code: str, unified_diff: str) -> str:
    with tempfile.TemporaryDirectory() as td:
        orig_path = os.path.join(td, "orig.py")
        patch_path = os.path.join(td, "diff.patch")
        with open(orig_path, "w") as f:
            f.write(original_code)
        with open(patch_path, "w") as f:
            f.write(unified_diff)
        subprocess.run(["patch", orig_path, patch_path], capture_output=True, check=False)
        with open(orig_path, "r") as f:
            return f.read()

async def run_validator(patcher_output, context_package, diagnoser_output) -> ValidatorReport:
    start_time = time.time()
    try:
        patched_code = apply_diff(context_package.error_node, patcher_output.unified_diff)
    except Exception as e:
        return ValidatorReport(
            overall_passed=False,
            gate_results={"gate_1": GateResult(passed=False, error=f"Patch error: {e}", duration_s=time.time()-start_time)},
            safety_diff=None,
            summary="Patch failed",
            detailed_failures=[str(e)]
        )
    
    py_lang = Language(tree_sitter_python.language())
    parser = Parser(py_lang)
    tree = parser.parse(patched_code.encode("utf8"))
    gate_1_time = time.time() - start_time
    gate_results = {}
    
    if tree.root_node.has_error:
        gate_results["gate_1"] = GateResult(passed=False, error="syntax error", duration_s=gate_1_time)
        return ValidatorReport(
            overall_passed=False,
            gate_results=gate_results,
            safety_diff=None,
            summary="Gate 1 failed: Syntax error",
            detailed_failures=["Syntax error in patched code"]
        )
    else:
        gate_results["gate_1"] = GateResult(passed=True, error=None, duration_s=gate_1_time)

    # Gates 2, 3, 4
    t2_start = time.time()
    t2_task = sandbox_pool.execute(language="python", code=patched_code, cmd=["mypy", "--strict", "--ignore-missing-imports", "main.py"], timeout=10)
    
    t3_start = time.time()
    t3_task = run_security_scanners(patched_code)
    
    t4_start = time.time()
    test_code = patched_code + "\n\n" + diagnoser_output.generated_test
    t4_task = sandbox_pool.execute(language="python", code=test_code, cmd=["pytest", "main.py", "-v", "--tb=short"], timeout=10)

    t2_res, t3_findings, t4_res = await asyncio.gather(t2_task, t3_task, t4_task)
    
    g2_passed = t2_res.exit_code == 0
    gate_results["gate_2"] = GateResult(passed=g2_passed, error=None if g2_passed else t2_res.stdout, duration_s=time.time()-t2_start)
    
    gate_results["gate_3"] = GateResult(passed=True, error=None, duration_s=time.time()-t3_start)
    
    g4_passed = t4_res.exit_code == 0
    gate_results["gate_4"] = GateResult(passed=g4_passed, error=None if g4_passed else t4_res.stdout, duration_s=time.time()-t4_start)

    safety_diff = await get_safety_diff(context_package.error_node, t3_findings)
    g5_passed = safety_diff.verdict != "regression"
    
    gate_results["gate_5"] = GateResult(passed=g5_passed, error="regression" if not g5_passed else None, duration_s=0.1)
    
    overall_passed = g2_passed and g4_passed and g5_passed
    detailed_failures = []
    if not g2_passed: detailed_failures.append(f"Gate 2 Mypy failed: {t2_res.stdout}")
    if not g4_passed: detailed_failures.append(f"Gate 4 Pytest failed: {t4_res.stdout}")
    if not g5_passed: detailed_failures.append("Gate 5 Diff Regression failed.")

    return ValidatorReport(
        overall_passed=overall_passed,
        gate_results=gate_results,
        safety_diff=safety_diff,
        summary="Passed" if overall_passed else "Validation failed",
        detailed_failures=detailed_failures
    )
