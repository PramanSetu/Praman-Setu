"""LangGraph orchestration for the full product pipeline.

Context Builder -> Diagnoser -> Patcher -> Validator -> (Reflector -> Patcher)* -> done

The Context Builder and Diagnoser nodes are skip-guarded: if their output is
already present on the incoming state, they no-op. That makes the graph runnable
from any partial state (and keeps unit tests offline).
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from backend.agents.diagnoser import DiagnoserAgent
from backend.agents.patcher import PatcherAgent
from backend.agents.reflector import ReflectorAgent
from backend.llm.client import LLMClient
from backend.orchestrator.state import PipelineState
from backend.tools.context_builder import context_builder
from backend.tools.validator import run_validator as run_five_gate_validator

MAX_RETRIES = 2

# Strategy -> hypothesis id. Escalation is deterministic, not parsed from LLM prose.
_ESCALATION = {"escalate_h2": "H2", "escalate_h3": "H3"}


async def run_context_builder(state: PipelineState) -> dict:
    if state.context_package is not None:
        return {}
    context = await context_builder.build(state.raw_input)
    return {"context_package": context}


async def run_diagnoser(state: PipelineState) -> dict:
    if state.diagnoser_output is not None:
        return {}
    assert state.context_package is not None, "context_package must be built before diagnosis"
    diagnoser = DiagnoserAgent(LLMClient())
    output = await diagnoser.diagnose(state.context_package)
    return {"diagnoser_output": output}


async def run_patcher(state: PipelineState) -> dict:
    # Reorder the chosen hypothesis to the front (the Patcher uses H1) and fold in
    # the Reflector's retry constraint.
    assert state.diagnoser_output is not None and state.context_package is not None
    diagnosis = state.diagnoser_output.model_copy(deep=True)
    target = next((h for h in diagnosis.hypotheses if h.id == state.hypothesis_used), None)
    constraint = state.reflector_decision.constraint_for_next_attempt if state.reflector_decision else ""

    if target is not None:
        diagnosis.hypotheses.remove(target)
        diagnosis.hypotheses.insert(0, target)
        if constraint:
            target.fix_direction += f"\n\nConstraint for next attempt: {constraint}"

    patcher = PatcherAgent(LLMClient())
    output = await patcher.patch(state.context_package, diagnosis)

    prompt_note = f"hypothesis={state.hypothesis_used}"
    if constraint:
        prompt_note += f"; retry_constraint={constraint}"
    return {"patcher_output": output, "patcher_prompts": [prompt_note]}


async def run_validator(state: PipelineState) -> dict:
    assert (
        state.patcher_output is not None
        and state.context_package is not None
        and state.diagnoser_output is not None
    )
    report = await run_five_gate_validator(
        state.patcher_output, state.context_package, state.diagnoser_output
    )
    return {"validator_report": report}


async def run_reflector(state: PipelineState) -> dict:
    reflector = ReflectorAgent(LLMClient())
    decision = await reflector.reflect(state)

    new_retry = state.retry_count + 1
    failed = list(state.failed_hypotheses)
    next_hypothesis = state.hypothesis_used

    if decision.strategy in _ESCALATION:
        if state.hypothesis_used not in failed:
            failed.append(state.hypothesis_used)
        next_hypothesis = _ESCALATION[decision.strategy]
    elif decision.strategy == "give_up" and state.hypothesis_used not in failed:
        failed.append(state.hypothesis_used)

    human_review = decision.strategy == "give_up" or new_retry >= MAX_RETRIES
    return {
        "reflector_decision": decision,
        "retry_count": new_retry,
        "failed_hypotheses": failed,
        "hypothesis_used": next_hypothesis,
        "human_review_flag": human_review,
    }


def route_after_validator(state: PipelineState) -> str:
    if state.validator_report and state.validator_report.overall_passed:
        return "done"
    return "run_reflector"


def route_after_reflector(state: PipelineState) -> str:
    if state.reflector_decision and state.reflector_decision.strategy == "give_up":
        return "done"
    if state.retry_count >= MAX_RETRIES:
        return "done"
    return "run_patcher"


def build_graph():
    workflow = StateGraph(PipelineState)
    workflow.add_node("run_context_builder", run_context_builder)
    workflow.add_node("run_diagnoser", run_diagnoser)
    workflow.add_node("run_patcher", run_patcher)
    workflow.add_node("run_validator", run_validator)
    workflow.add_node("run_reflector", run_reflector)

    workflow.set_entry_point("run_context_builder")
    workflow.add_edge("run_context_builder", "run_diagnoser")
    workflow.add_edge("run_diagnoser", "run_patcher")
    workflow.add_edge("run_patcher", "run_validator")
    workflow.add_conditional_edges(
        "run_validator", route_after_validator, {"done": END, "run_reflector": "run_reflector"}
    )
    workflow.add_conditional_edges(
        "run_reflector", route_after_reflector, {"done": END, "run_patcher": "run_patcher"}
    )
    return workflow.compile()


# Back-compat alias.
get_graph = build_graph
