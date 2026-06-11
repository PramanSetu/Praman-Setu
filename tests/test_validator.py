from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.orchestrator.state import (
    ContextPackage,
    DiagnoserOutput,
    Hypothesis,
    PatcherOutput,
    SafetyDiff,
    SafetyFinding,
)
from backend.tools import validator as validator_mod
from backend.tools.diff_regression import ScanResult
from backend.tools.sandbox.executor import SandboxResult
from backend.tools.validator import run_validator, splice_patched_module

ORIGINAL_FULL = "def divide(a, b):\n    return a / b\n\ndivide(1, 0)"
ORIGINAL_FUNC = "def divide(a, b):\n    return a / b"
PATCHED_FUNC = "def divide(a, b):\n    if b == 0:\n        raise ZeroDivisionError('no')\n    return a / b"


def _ctx(
    full_code: str = ORIGINAL_FULL,
    function_source: str = ORIGINAL_FUNC,
    runtime_trace: dict | None = None,
) -> ContextPackage:
    return ContextPackage(
        error_node=function_source,
        function_signature="def divide(a, b):",
        imports=[],
        runtime_trace=runtime_trace or {},
        language="python",
        full_code=full_code,
        function_source=function_source,
    )


def _diag(test: str = "def test_divide():\n    assert divide(4, 2) == 2\n") -> DiagnoserOutput:
    hyps = [Hypothesis(id=f"H{i}", theory="t", confidence=0.5, fix_direction="f") for i in (1, 2, 3)]
    return DiagnoserOutput(root_cause="rc", hypotheses=hyps, generated_test=test)


def _patch(code: str = PATCHED_FUNC) -> PatcherOutput:
    return PatcherOutput(unified_diff="+guard", confidence=0.9, approach="add guard", patched_code=code)


def _sb(exit_code: int = 0, stdout: str = "", stderr: str = "") -> SandboxResult:
    return SandboxResult(exit_code=exit_code, stdout=stdout, stderr=stderr, timed_out=False, duration_s=0.01)


def _fake_execute(mypy_exit: int = 0, pytest_exit: int = 0, mypy_out: str = "", pytest_out: str = ""):
    async def execute(language, code, cmd=None, timeout=None):
        if cmd and cmd[0] == "mypy":
            return _sb(mypy_exit, mypy_out)
        if cmd and cmd[0] == "pytest":
            return _sb(pytest_exit, pytest_out)
        return _sb(0)

    return execute


def _wire(monkeypatch, *, mypy_exit=0, pytest_exit=0, findings=None, verdict="neutral"):
    monkeypatch.setattr(validator_mod.sandbox_pool, "execute", _fake_execute(mypy_exit, pytest_exit))
    monkeypatch.setattr(
        validator_mod,
        "scan_code",
        AsyncMock(return_value=ScanResult(findings=findings or [], errors=[])),
    )
    monkeypatch.setattr(
        validator_mod,
        "safety_diff_against_original",
        AsyncMock(return_value=SafetyDiff(introduced=[], fixed=[], verdict=verdict)),
    )


# --- pure splice ---


def test_splice_replaces_function_in_full_module() -> None:
    spliced = splice_patched_module(_ctx(), PATCHED_FUNC)
    assert "if b == 0:" in spliced
    assert spliced.endswith("divide(1, 0)")  # rest of module preserved
    assert spliced.count("def divide") == 1


def test_splice_replaces_explicit_patch_target_source() -> None:
    full = "\n".join(
        [
            "def parse_total(raw):",
            "    return int(raw)",
            "",
            "def load_total(payload):",
            "    raw_total = payload.get('total', '0')",
            "    return parse_total(raw_total)",
            "",
            "load_total({'total': ''})",
        ]
    )
    target = (
        "def load_total(payload):\n"
        "    raw_total = payload.get('total', '0')\n"
        "    return parse_total(raw_total)"
    )
    patched = (
        "def load_total(payload):\n"
        "    raw_total = payload.get('total') or '0'\n"
        "    return parse_total(raw_total)"
    )

    spliced = splice_patched_module(_ctx(full_code=full), patched, target)

    assert "raw_total = payload.get('total') or '0'" in spliced
    assert "def parse_total(raw):" in spliced
    assert "load_total({'total': ''})" in spliced


def test_splice_replaces_exact_class_patch_target_source() -> None:
    original_class = (
        "class Cart:\n"
        "    tax_rate = 0.18\n\n"
        "    def __init__(self, items):\n"
        "        self.items = items\n\n"
        "    def total(self):\n"
        "        return sum(self.items) * self.tax_rate"
    )
    full = original_class + "\n\nprint(Cart([100]).total())"
    patched_class = (
        "class Cart:\n"
        "    tax_rate = 0.18\n\n"
        "    def __init__(self, items):\n"
        "        self.items = items\n\n"
        "    def total(self):\n"
        "        subtotal = sum(self.items)\n"
        "        return subtotal + subtotal * self.tax_rate"
    )

    spliced = splice_patched_module(_ctx(full_code=full), patched_class, original_class)

    assert "subtotal = sum(self.items)" in spliced
    assert "print(Cart([100]).total())" in spliced
    assert spliced.count("class Cart:") == 1


def test_splice_raises_when_function_not_in_module() -> None:
    ctx = _ctx(full_code="def other():\n    pass", function_source=ORIGINAL_FUNC)
    with pytest.raises(ValueError):
        splice_patched_module(ctx, PATCHED_FUNC)


# --- gates ---


async def test_happy_path_passes_all_gates(monkeypatch) -> None:
    _wire(monkeypatch)
    report = await run_validator(_patch(), _ctx(), _diag())
    assert report.overall_passed is True
    assert all(g.passed for g in report.gate_results.values())


async def test_empty_patch_fails_fast(monkeypatch) -> None:
    _wire(monkeypatch)
    report = await run_validator(_patch(code="   "), _ctx(), _diag())
    assert report.overall_passed is False
    assert "gate_1" in report.gate_results


async def test_unchanged_patch_is_rejected_before_expensive_gates(monkeypatch) -> None:
    _wire(monkeypatch)
    report = await run_validator(_patch(code=ORIGINAL_FUNC), _ctx(), _diag())
    assert report.overall_passed is False
    assert report.gate_results["gate_1"].passed is False
    assert "identical" in report.gate_results["gate_1"].error


async def test_stub_patch_is_rejected(monkeypatch) -> None:
    _wire(monkeypatch)
    report = await run_validator(_patch(code="def divide(a, b):\n    pass"), _ctx(), _diag())
    assert report.overall_passed is False
    assert "empty stub" in report.gate_results["gate_1"].error


async def test_broad_exception_swallowing_is_rejected(monkeypatch) -> None:
    _wire(monkeypatch)
    code = "def divide(a, b):\n    try:\n        return a / b\n    except Exception:\n        pass"
    report = await run_validator(_patch(code=code), _ctx(), _diag())
    assert report.overall_passed is False
    assert "broad exceptions" in report.gate_results["gate_1"].error


async def test_patch_target_with_module_level_call_is_rejected(monkeypatch) -> None:
    _wire(monkeypatch)
    code = "def divide(a, b):\n    return a / b\n\nprint(divide(1, 0))"
    report = await run_validator(_patch(code=code), _ctx(), _diag())
    assert report.overall_passed is False
    assert "module-level executable calls" in report.gate_results["gate_1"].error


async def test_explicitly_raising_original_runtime_error_is_rejected(monkeypatch) -> None:
    _wire(monkeypatch)
    code = "def divide(a, b):\n    if b == 0:\n        raise ZeroDivisionError('division by zero')\n    return a / b"
    report = await run_validator(
        _patch(code=code),
        _ctx(runtime_trace={"error_type": "ZeroDivisionError"}),
        _diag(),
    )
    assert report.overall_passed is False
    assert "original runtime error ZeroDivisionError" in report.gate_results["gate_1"].error


async def test_generated_test_must_assert_behavior(monkeypatch) -> None:
    _wire(monkeypatch)
    report = await run_validator(
        _patch(),
        _ctx(),
        _diag(test="def test_divide():\n    divide(4, 2)\n"),
    )
    assert report.overall_passed is False
    assert report.gate_results["gate_4"].passed is False
    assert "assert or pytest.raises" in report.gate_results["gate_4"].error


async def test_syntax_error_fails_gate1_without_running_gates(monkeypatch) -> None:
    _wire(monkeypatch)
    report = await run_validator(_patch(code="def divide(a, b):\n    return a /"), _ctx(), _diag())
    assert report.overall_passed is False
    assert report.gate_results["gate_1"].passed is False
    assert "gate_2" not in report.gate_results  # fail-fast


async def test_splice_failure_is_reported_not_swallowed(monkeypatch) -> None:
    _wire(monkeypatch)
    ctx = _ctx(full_code="def unrelated():\n    pass", function_source=ORIGINAL_FUNC)
    report = await run_validator(_patch(), ctx, _diag())
    assert report.overall_passed is False
    assert "not found" in report.detailed_failures[0]


async def test_failing_test_fails_gate4(monkeypatch) -> None:
    _wire(monkeypatch, pytest_exit=1)
    report = await run_validator(_patch(), _ctx(), _diag())
    assert report.overall_passed is False
    assert report.gate_results["gate_4"].passed is False


async def test_high_severity_finding_fails_gate3(monkeypatch) -> None:
    _wire(monkeypatch, findings=[SafetyFinding(rule="B102", severity="HIGH", line=2)])
    report = await run_validator(_patch(), _ctx(), _diag())
    assert report.overall_passed is False
    assert report.gate_results["gate_3"].passed is False


async def test_security_regression_fails_gate5(monkeypatch) -> None:
    _wire(monkeypatch, verdict="regression")
    report = await run_validator(_patch(), _ctx(), _diag())
    assert report.overall_passed is False
    assert report.gate_results["gate_5"].passed is False


# --- opt-in real integration ---


@pytest.mark.integration
async def test_real_validator_passes_a_guarded_patch() -> None:
    """Runs the real 5 gates through Docker. Requires the sandbox image built."""
    ctx = _ctx()
    diag = _diag(
        test="import pytest\n\ndef test_zero():\n    with pytest.raises(ZeroDivisionError):\n        divide(1, 0)\n"
    )
    report = await run_validator(_patch(), ctx, diag)
    assert report.gate_results["gate_1"].passed is True
    assert report.gate_results["gate_4"].passed is True
    assert report.overall_passed is True
