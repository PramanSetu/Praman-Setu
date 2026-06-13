from __future__ import annotations

from backend.agents.syntax_fixer import SyntaxFixerAgent, SyntaxFixResponse
from backend.orchestrator.graph import (
    _minimal_syntax_fix,
    _validate_syntax_fix,
    route_after_context_builder,
)
from backend.orchestrator.state import (
    DetectionMethod,
    LanguageDetection,
    PipelineState,
    ProcessedInput,
)

BROKEN = "def f(x):\n    if x:\n        return 1\n    else\n        return 0"
FIXED = "def f(x):\n    if x:\n        return 1\n    else:\n        return 0"


class FakeLLM:
    def __init__(self, response: object) -> None:
        self.response = response

    async def complete(self, *args, **kwargs):
        return self.response


def _processed(error_type: str | None) -> ProcessedInput:
    return ProcessedInput(
        language="python",
        detection=LanguageDetection(
            language="python", confidence=1.0, method=DetectionMethod.EXTENSION, reason="t"
        ),
        filename="m.py",
        code=BROKEN,
        line_count=5,
        supplied_error_message=False,
        error_message="expected ':'",
        error_type=error_type,
        error_line=4,
        raw_stderr="",
        fast_path_eligible=False,
        execution=None,
        status="execution_failed",
    )


def _state(error_type: str | None) -> PipelineState:
    return PipelineState(raw_input=_processed(error_type), language="python")


# --- routing ---


def test_syntax_error_routes_to_fast_path() -> None:
    assert route_after_context_builder(_state("SyntaxError")) == "run_syntax_fix"


def test_runtime_error_routes_to_diagnoser() -> None:
    assert route_after_context_builder(_state("NameError")) == "run_diagnoser"


# --- parse-only validation ---


def test_validate_accepts_a_parsing_fix() -> None:
    report = _validate_syntax_fix(BROKEN, FIXED)
    assert report.overall_passed is True
    assert report.gate_results["gate_1"].passed is True


def test_validate_rejects_still_broken_fix() -> None:
    report = _validate_syntax_fix(BROKEN, "def f(x):\n    return (")  # unclosed paren
    assert report.overall_passed is False
    assert "syntax" in report.gate_results["gate_1"].error.lower()


def test_validate_rejects_no_change() -> None:
    report = _validate_syntax_fix(BROKEN, BROKEN)
    assert report.overall_passed is False


# --- surgical minimal fix (revert over-fixes) ---


def test_minimal_fix_reverts_unrelated_overfix() -> None:
    # LLM fixed the syntax (else:) AND over-fixed a NameError (number->numbers).
    original = "def f(numbers):\n    for n in number:\n        pass\n    if numbers:\n        return 1\n    else\n        return 0"
    overfixed = "def f(numbers):\n    for n in numbers:\n        pass\n    if numbers:\n        return 1\n    else:\n        return 0"
    # Error is the `else` on line 6 — only that change should survive.
    minimal = _minimal_syntax_fix(original, overfixed, error_line=6)
    assert minimal is not None
    assert "else:" in minimal                  # syntax fix kept
    assert "for n in number:" in minimal       # over-fix reverted (NameError remains)
    assert "for n in numbers:" not in minimal


def test_minimal_fix_keeps_a_genuine_one_line_fix() -> None:
    original = "x = 1\nif x:\n    print(x)\nelse\n    print(0)"
    fixed = "x = 1\nif x:\n    print(x)\nelse:\n    print(0)"
    minimal = _minimal_syntax_fix(original, fixed, error_line=4)
    assert minimal == fixed


# --- agent ---


async def test_syntax_fixer_returns_fixed_code() -> None:
    agent = SyntaxFixerAgent(FakeLLM(SyntaxFixResponse(fixed_code=FIXED)))
    result = await agent.fix(BROKEN, "expected ':'", 4)
    assert result == FIXED


async def test_syntax_fixer_validates_dict_response() -> None:
    agent = SyntaxFixerAgent(FakeLLM({"fixed_code": FIXED}))
    result = await agent.fix(BROKEN, "expected ':'", 4)
    assert result == FIXED
