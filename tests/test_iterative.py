from __future__ import annotations

from backend.input_handler.models import RawInput
from backend.orchestrator.iterative import iterative_fix
from backend.orchestrator.state import (
    ContextPackage,
    DetectionMethod,
    DiagnoserOutput,
    Hypothesis,
    LanguageDetection,
    PatcherOutput,
    ProcessedInput,
    ValidatorReport,
)

# Two-bug module: first call surfaces bug A, after the fix bug B, then clean.
CODE_V0 = "def f():\n    return undefined_a\n\ndef g():\n    return undefined_b\n\nf()"
CODE_V1 = "def f():\n    return 1\n\ndef g():\n    return undefined_b\n\nf()"
CODE_V2 = "def f():\n    return 1\n\ndef g():\n    return 2\n\nf()"


def _processed(code: str, status: str, error_type: str | None, line: int | None) -> ProcessedInput:
    return ProcessedInput(
        language="python",
        detection=LanguageDetection(
            language="python", confidence=1.0, method=DetectionMethod.EXTENSION, reason="t"
        ),
        filename="m.py",
        code=code,
        line_count=len(code.splitlines()),
        supplied_error_message=False,
        error_message=error_type or "",
        error_type=error_type,
        error_line=line,
        raw_stderr="",
        fast_path_eligible=False,
        execution=None,
        status=status,  # type: ignore[arg-type]
    )


class FakeHandler:
    """Returns failing inputs until the code reaches the clean version."""

    def __init__(self) -> None:
        self.calls = 0

    async def handle(self, request: RawInput):
        self.calls += 1
        if request.code == CODE_V2:
            return _processed(request.code, "execution_clean", None, None)
        if request.code == CODE_V0:
            return _processed(request.code, "execution_failed", "NameError", 2)
        return _processed(request.code, "execution_failed", "NameError", 5)


def _patcher(patched: str, target_src: str) -> PatcherOutput:
    return PatcherOutput(
        unified_diff="+fix", confidence=0.9, approach="fix", patched_code=patched,
        patch_target_source=target_src,
    )


def _passing_report() -> ValidatorReport:
    return ValidatorReport(
        overall_passed=True, gate_results={}, safety_diff=None, summary="ok", detailed_failures=[]
    )


def _diag() -> DiagnoserOutput:
    return DiagnoserOutput(
        root_cause="undefined name",
        hypotheses=[Hypothesis(id=f"H{i}", theory="t", confidence=0.5, fix_direction="f") for i in (1, 2, 3)],
        generated_test="def test():\n    assert True",
    )


class FakeGraph:
    """Returns a successful fix that turns V0->V1 then V1->V2."""

    async def ainvoke(self, state):
        code = state.raw_input.code
        if code == CODE_V0:
            ctx = ContextPackage(
                error_node="", function_signature="def f():", imports=[], runtime_trace={},
                language="python", full_code=CODE_V0, function_source="def f():\n    return undefined_a",
            )
            patch = _patcher("def f():\n    return 1", "def f():\n    return undefined_a")
        else:
            ctx = ContextPackage(
                error_node="", function_signature="def g():", imports=[], runtime_trace={},
                language="python", full_code=CODE_V1, function_source="def g():\n    return undefined_b",
            )
            patch = _patcher("def g():\n    return 2", "def g():\n    return undefined_b")
        return {"validator_report": _passing_report(), "patcher_output": patch,
                "context_package": ctx, "diagnoser_output": _diag()}


async def test_iterative_fixes_multiple_bugs_until_clean() -> None:
    result = await iterative_fix(CODE_V0, "m.py", handler=FakeHandler(), graph=FakeGraph())

    assert result.status == "clean"
    assert result.bugs_fixed == 2
    assert result.final_code == CODE_V2
    assert [s.fixed for s in result.steps] == [True, True]


class _StuckGraph:
    async def ainvoke(self, state):
        return {"validator_report": ValidatorReport(
            overall_passed=False, gate_results={}, safety_diff=None, summary="fail",
            detailed_failures=["nope"]), "patcher_output": None, "context_package": None}


async def _no_testless_fix(processed):
    return None


async def test_iterative_stops_when_a_bug_cannot_be_fixed() -> None:
    result = await iterative_fix(
        CODE_V0, "m.py", handler=FakeHandler(), graph=_StuckGraph(), testless_fixer=_no_testless_fix
    )
    assert result.status == "stuck"
    assert result.bugs_fixed == 0
    assert result.steps[-1].fixed is False


async def test_testless_fix_fallback_via_integration_proof() -> None:
    # The graph produces NO patch, but the testless fixer does, and the candidate
    # runs clean → accepted via integration proof, labeled runs_clean.
    async def fixer(processed):
        return (CODE_V2, "function", "off-by-one")

    class OneFixHandler:
        async def handle(self, request: RawInput):
            if request.code == CODE_V0:
                return _processed(request.code, "execution_failed", "IndexError", 2)
            return _processed(request.code, "execution_clean", None, None)

    result = await iterative_fix(
        CODE_V0, "m.py", handler=OneFixHandler(), graph=_StuckGraph(), testless_fixer=fixer
    )
    assert result.status == "clean"
    assert result.bugs_fixed == 1
    assert result.steps[0].fixed is True
    assert result.steps[0].proof == "runs_clean"


async def test_iterative_stops_on_clean_input_immediately() -> None:
    class CleanHandler:
        async def handle(self, request: RawInput):
            return _processed(request.code, "execution_clean", None, None)

    result = await iterative_fix(CODE_V2, "m.py", handler=CleanHandler(), graph=FakeGraph())
    assert result.status == "clean"
    assert result.bugs_fixed == 0


async def test_integration_proof_accepts_when_program_runs_clean() -> None:
    # The graph FAILS behavioral validation (overall_passed=False), but the spliced
    # candidate runs clean → accepted via integration proof, labeled "runs_clean".
    class FailingGraph:
        async def ainvoke(self, state):
            ctx = ContextPackage(
                error_node="", function_signature="def f():", imports=[], runtime_trace={},
                language="python", full_code=CODE_V0, function_source="def f():\n    return undefined_a",
            )
            patch = _patcher("def f():\n    return 1", "def f():\n    return undefined_a")
            return {
                "validator_report": ValidatorReport(
                    overall_passed=False, gate_results={}, safety_diff=None,
                    summary="no test", detailed_failures=["no behavioral test"],
                ),
                "patcher_output": patch, "context_package": ctx, "diagnoser_output": _diag(),
            }

    class OneFixHandler:
        # V0 crashes; after the single splice (-> V1) the program runs clean.
        async def handle(self, request: RawInput):
            if request.code == CODE_V0:
                return _processed(request.code, "execution_failed", "NameError", 2)
            return _processed(request.code, "execution_clean", None, None)

    result = await iterative_fix(CODE_V0, "m.py", handler=OneFixHandler(), graph=FailingGraph())
    assert result.status == "clean"
    assert result.bugs_fixed == 1
    assert result.steps[0].fixed is True
    assert result.steps[0].proof == "runs_clean"
