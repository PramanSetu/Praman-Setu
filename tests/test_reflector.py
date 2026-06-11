from __future__ import annotations

import pytest

from backend.agents.reflector import ReflectorAgent, ReflectorError
from backend.orchestrator.state import (
    DetectionMethod,
    DiagnoserOutput,
    GateResult,
    Hypothesis,
    LanguageDetection,
    PipelineState,
    ProcessedInput,
    ReflectorDecision,
    ValidatorReport,
)


class FakeLLM:
    def __init__(self, response: object) -> None:
        self.response = response

    async def complete(self, *args, **kwargs):
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _decision(strategy: str = "escalate_h2") -> ReflectorDecision:
    return ReflectorDecision(
        strategy=strategy,
        failure_root_cause="Gate 2 type failure",
        constraint_for_next_attempt="preserve the return type",
        confidence_in_strategy=0.85,
        abandoning_hypothesis="H1",
        new_hypothesis_to_try="H2",
    )


def _state() -> PipelineState:
    processed = ProcessedInput(
        language="python",
        detection=LanguageDetection(
            language="python", confidence=1.0, method=DetectionMethod.EXTENSION, reason="t"
        ),
        filename="main.py",
        code="def f(): pass",
        line_count=1,
        supplied_error_message=False,
        error_message="",
        error_type=None,
        error_line=None,
        raw_stderr="",
        fast_path_eligible=False,
        execution=None,
        status="ready",
    )
    diagnosis = DiagnoserOutput(
        root_cause="rc",
        hypotheses=[Hypothesis(id=f"H{i}", theory="t", confidence=0.5, fix_direction="f") for i in (1, 2, 3)],
        generated_test="def test_f(): pass",
    )
    report = ValidatorReport(
        overall_passed=False,
        gate_results={"gate_2": GateResult(passed=False, error="mypy", duration_s=0.1)},
        safety_diff=None,
        summary="Validation failed",
        detailed_failures=["Gate 2 (mypy) failed: incompatible type"],
    )
    return PipelineState(
        raw_input=processed,
        language="python",
        diagnoser_output=diagnosis,
        validator_report=report,
    )


async def test_reflect_returns_decision_object() -> None:
    agent = ReflectorAgent(FakeLLM(_decision()))
    out = await agent.reflect(_state())
    assert out.strategy == "escalate_h2"


async def test_reflect_validates_dict_response() -> None:
    agent = ReflectorAgent(FakeLLM(_decision().model_dump()))
    out = await agent.reflect(_state())
    assert isinstance(out, ReflectorDecision)
    assert out.strategy == "escalate_h2"


async def test_reflect_raises_on_invalid_response() -> None:
    agent = ReflectorAgent(FakeLLM({"unexpected": "shape"}))
    with pytest.raises(ReflectorError):
        await agent.reflect(_state())
