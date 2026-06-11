from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.orchestrator.graph import (
    build_graph,
    route_after_reflector,
    route_after_validator,
    run_patcher,
    run_reflector,
    run_validator,
)
from backend.orchestrator.state import (
    ContextPackage,
    DetectionMethod,
    DiagnoserOutput,
    GateResult,
    Hypothesis,
    LanguageDetection,
    PatcherOutput,
    PipelineState,
    ProcessedInput,
    ReflectorDecision,
    ValidatorReport,
)


def _get_mock_state() -> PipelineState:
    return PipelineState(
        raw_input=ProcessedInput(
            language="python",
            detection=LanguageDetection(
                language="python",
                confidence=1.0,
                method=DetectionMethod.EXTENSION,
                reason="test",
            ),
            filename="main.py",
            code="def foo(): pass",
            line_count=1,
            supplied_error_message=False,
            error_message="",
            error_type=None,
            error_line=None,
            raw_stderr="",
            fast_path_eligible=False,
            execution=None,
            status="ready",
        ),
        language="python",
        diagnoser_output=DiagnoserOutput(
            root_cause="test",
            hypotheses=[
                Hypothesis(id="H1", theory="t1", confidence=0.8, fix_direction="f1"),
                Hypothesis(id="H2", theory="t2", confidence=0.6, fix_direction="f2"),
                Hypothesis(id="H3", theory="t3", confidence=0.5, fix_direction="f3"),
            ],
            generated_test="def test_foo(): pass",
        ),
        context_package=ContextPackage(
            error_node="def foo(): pass",
            function_signature="def foo()",
            imports=[],
            runtime_trace={},
            language="python",
        ),
    )


def _gate2_report(passed: bool) -> ValidatorReport:
    return ValidatorReport(
        overall_passed=passed,
        gate_results={
            "gate_2": GateResult(
                passed=passed,
                error=None if passed else "mypy failed",
                duration_s=0.1,
            )
        },
        safety_diff=None,
        summary="Passed" if passed else "Validation failed",
        detailed_failures=[] if passed else ["Gate 2 Mypy failed: incompatible type"],
    )


def _reflector_decision(strategy: str = "refine_current") -> ReflectorDecision:
    return ReflectorDecision(
        strategy=strategy,
        failure_root_cause="Gate 2 type failure",
        constraint_for_next_attempt="preserve the return type expected by mypy",
        confidence_in_strategy=0.9,
        abandoning_hypothesis=None,
        new_hypothesis_to_try=None,
    )


@pytest.mark.asyncio
async def test_run_patcher_uses_selected_hypothesis_and_retry_constraint():
    captured = {}

    class FakePatcherAgent:
        def __init__(self, llm_client):
            self.llm_client = llm_client

        async def patch(self, context, diagnosis):
            captured["context"] = context
            captured["diagnosis"] = diagnosis
            return PatcherOutput(
                unified_diff="+fixed",
                confidence=0.95,
                approach="captured patch",
            )

    state = _get_mock_state().model_copy(
        update={
            "retry_count": 1,
            "hypothesis_used": "H2",
            "reflector_decision": _reflector_decision(),
        }
    )

    with patch("backend.orchestrator.graph.PatcherAgent", FakePatcherAgent):
        result = await run_patcher(state)

    diagnosis = captured["diagnosis"]
    assert result["patcher_output"].approach == "captured patch"
    assert diagnosis.hypotheses[0].id == "H2"
    assert diagnosis.hypotheses[0].fix_direction.startswith("f2")
    assert "preserve the return type expected by mypy" in diagnosis.hypotheses[0].fix_direction
    assert result["patcher_prompts"] == [
        "hypothesis=H2; retry_constraint=preserve the return type expected by mypy"
    ]


@pytest.mark.asyncio
async def test_run_validator_calls_real_five_gate_adapter_and_populates_report():
    expected_report = _gate2_report(True)
    state = _get_mock_state().model_copy(
        update={
            "patcher_output": PatcherOutput(
                unified_diff="+fixed",
                confidence=0.95,
                approach="valid patch",
            )
        }
    )

    with patch(
        "backend.orchestrator.graph.run_five_gate_validator",
        AsyncMock(return_value=expected_report),
    ) as mock_validator:
        result = await run_validator(state)

    assert result == {"validator_report": expected_report}
    mock_validator.assert_awaited_once_with(
        state.patcher_output,
        state.context_package,
        state.diagnoser_output,
    )


@pytest.mark.asyncio
async def test_run_reflector_populates_decision_and_mutates_retry_state():
    decision = ReflectorDecision(
        strategy="escalate_h2",
        failure_root_cause="H1 patch kept failing Gate 2",
        constraint_for_next_attempt="try the alternative type-safe branch",
        confidence_in_strategy=0.85,
        abandoning_hypothesis="H1",
        new_hypothesis_to_try="H2",
    )

    class FakeReflectorAgent:
        def __init__(self, llm_client):
            self.llm_client = llm_client

        async def reflect(self, state):
            return decision

    with patch("backend.orchestrator.graph.ReflectorAgent", FakeReflectorAgent):
        result = await run_reflector(_get_mock_state())

    assert result["reflector_decision"] == decision
    assert result["retry_count"] == 1
    assert result["failed_hypotheses"] == ["H1"]
    assert result["hypothesis_used"] == "H2"
    assert result["human_review_flag"] is False


@pytest.mark.asyncio
async def test_e2e_retry_success():
    """Gate 2 fails, reflector retries once, then validation passes."""
    mock_patcher = AsyncMock(
        side_effect=[
            {
                "patcher_output": PatcherOutput(
                    unified_diff="+bad",
                    confidence=0.6,
                    approach="first bad patch",
                ),
                "patcher_prompts": ["hypothesis=H1"],
            },
            {
                "patcher_output": PatcherOutput(
                    unified_diff="+good",
                    confidence=0.9,
                    approach="retry type-safe patch",
                ),
                "patcher_prompts": [
                    "hypothesis=H1; retry_constraint=preserve the return type expected by mypy"
                ],
            },
        ]
    )
    mock_validator = AsyncMock(
        side_effect=[
            {"validator_report": _gate2_report(False)},
            {"validator_report": _gate2_report(True)},
        ]
    )
    mock_reflector = AsyncMock(
        return_value={
            "reflector_decision": _reflector_decision(),
            "retry_count": 1,
            "failed_hypotheses": ["H1"],
            "hypothesis_used": "H1",
            "human_review_flag": False,
        }
    )

    with (
        patch("backend.orchestrator.graph.run_patcher", mock_patcher),
        patch("backend.orchestrator.graph.run_validator", mock_validator),
        patch("backend.orchestrator.graph.run_reflector", mock_reflector),
    ):
        app = build_graph()
        final_state = await app.ainvoke(_get_mock_state())

    assert final_state["retry_count"] == 1
    assert final_state["validator_report"].overall_passed is True
    assert final_state["human_review_flag"] is False
    assert mock_patcher.await_count == 2
    assert mock_validator.await_count == 2
    assert mock_reflector.await_count == 1
    assert len(final_state["patcher_prompts"]) == 2
    assert "retry_constraint=preserve the return type expected by mypy" in final_state[
        "patcher_prompts"
    ][1]


@pytest.mark.asyncio
async def test_e2e_human_review_when_retries_exhausted():
    """Repeated validation failure stops at retry limit and flags human review."""
    mock_patcher = AsyncMock(
        return_value={
            "patcher_output": PatcherOutput(
                unified_diff="+still-bad",
                confidence=0.5,
                approach="unsuccessful patch",
            ),
            "patcher_prompts": ["hypothesis=H1"],
        }
    )
    mock_validator = AsyncMock(return_value={"validator_report": _gate2_report(False)})
    mock_reflector = AsyncMock(
        side_effect=[
            {
                "reflector_decision": _reflector_decision(),
                "retry_count": 1,
                "failed_hypotheses": ["H1"],
                "hypothesis_used": "H1",
                "human_review_flag": False,
            },
            {
                "reflector_decision": _reflector_decision("give_up"),
                "retry_count": 2,
                "failed_hypotheses": ["H1"],
                "hypothesis_used": "H1",
                "human_review_flag": True,
            },
        ]
    )

    with (
        patch("backend.orchestrator.graph.run_patcher", mock_patcher),
        patch("backend.orchestrator.graph.run_validator", mock_validator),
        patch("backend.orchestrator.graph.run_reflector", mock_reflector),
    ):
        app = build_graph()
        final_state = await app.ainvoke(_get_mock_state())

    assert final_state["retry_count"] == 2
    assert final_state["human_review_flag"] is True
    assert mock_patcher.await_count == 2
    assert mock_validator.await_count == 2
    assert mock_reflector.await_count == 2


def test_route_after_reflector_never_retries_at_hard_limit():
    state = _get_mock_state().model_copy(
        update={
            "retry_count": 2,
            "reflector_decision": _reflector_decision(),
        }
    )

    assert route_after_reflector(state) == "done"


def test_route_after_validator_finishes_on_success_without_reflector():
    state = _get_mock_state().model_copy(update={"validator_report": _gate2_report(True)})

    assert route_after_validator(state) == "done"
