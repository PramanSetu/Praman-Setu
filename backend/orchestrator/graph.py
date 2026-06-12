"""LangGraph orchestration for the full product pipeline.

Context Builder -> Diagnoser -> Patcher -> Validator -> (Reflector -> Patcher)* -> done

The Context Builder and Diagnoser nodes are skip-guarded: if their output is
already present on the incoming state, they no-op. That makes the graph runnable
from any partial state (and keeps unit tests offline).
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from time import perf_counter

from langgraph.graph import END, StateGraph

from backend.agents.diagnoser import DiagnoserAgent, DiagnoserError
from backend.agents.patcher import PatcherAgent
from backend.agents.reflector import ReflectorAgent
from backend.llm.client import llm_client
from backend.observability.metrics import collect_llm_calls
from backend.orchestrator.state import (
    ContextPackage,
    PatcherOutput,
    PipelineState,
    ProcessedInput,
    ReflectorDecision,
)
from backend.tools.context_builder import context_builder
from backend.tools.validator import run_validator as run_five_gate_validator

MAX_RETRIES = 2

# Strategy -> hypothesis id. Escalation is deterministic, not parsed from LLM prose.
_ESCALATION = {"escalate_h2": "H2", "escalate_h3": "H3"}

# Node name -> the timing key recorded into PipelineState.node_timings.
_NODE_METRIC = {
    "run_context_builder": "context_builder_ms",
    "run_diagnoser": "diagnoser_ms",
    "run_patcher": "patcher_ms",
    "run_validator": "validator_ms",
    "run_reflector": "reflector_ms",
}


def _context_metrics(raw_input: ProcessedInput, ctx: ContextPackage) -> dict[str, int]:
    class_chars = len(ctx.enclosing_class_source or "")
    caller_chars = sum(len(c) for c in ctx.callers)
    callee_chars = sum(len(c) for c in ctx.callees)
    const_chars = sum(len(c) for c in ctx.constants)
    return {
        "line_count": raw_input.line_count,
        "function_chars": len(ctx.function_source),
        "class_chars": class_chars,
        "callers_count": len(ctx.callers),
        "callees_count": len(ctx.callees),
        "constants_count": len(ctx.constants),
        "context_chars": len(ctx.function_source) + class_chars + caller_chars + callee_chars + const_chars,
    }


async def run_context_builder(state: PipelineState) -> dict:
    if state.context_package is not None:
        return {}
    context = await context_builder.build(state.raw_input)
    return {
        "context_package": context,
        "context_metrics": _context_metrics(state.raw_input, context),
    }


async def run_diagnoser(state: PipelineState) -> dict:
    if state.diagnoser_output is not None:
        return {}
    assert state.context_package is not None, "context_package must be built before diagnosis"
    diagnoser = DiagnoserAgent(llm_client)
    with collect_llm_calls() as calls:
        try:
            output = await diagnoser.diagnose(state.context_package)
        except DiagnoserError:
            # No usable diagnosis/test after retry — fail safe to human review
            # rather than handing a bad test to the patch-only retry loop.
            return {"llm_calls": calls, "human_review_flag": True}
    update: dict = {"diagnoser_output": output, "llm_calls": calls}
    # If the Diagnoser can't safely infer the intended behavior, don't guess a
    # patch — surface it for human review.
    if output.requires_clarification:
        update["human_review_flag"] = True
    return update


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

    patcher = PatcherAgent(llm_client)
    with collect_llm_calls() as calls:
        try:
            output = await patcher.patch(state.context_package, diagnosis)
        except Exception as exc:
            # Never crash the pipeline (e.g. unparseable input). Emit a blocked
            # patch so the Validator rejects it and we fail safe to human review.
            blocked = PatcherOutput(
                unified_diff="(patch failed)",
                confidence=0.0,
                approach="patch generation failed",
                patched_code="",
                blocked_reason=str(exc)[:300],
                hypothesis_used=state.hypothesis_used,
            )
            return {
                "patcher_output": blocked,
                "patch_history": [blocked],
                "patcher_prompts": [f"hypothesis={state.hypothesis_used}; error={type(exc).__name__}"],
                "llm_calls": calls,
                "human_review_flag": True,
            }
    output = output.model_copy(update={"hypothesis_used": state.hypothesis_used})

    prompt_note = f"hypothesis={state.hypothesis_used}"
    if constraint:
        prompt_note += f"; retry_constraint={constraint}"
    return {
        "patcher_output": output,
        "patch_history": [output],
        "patcher_prompts": [prompt_note],
        "llm_calls": calls,
    }


async def run_validator(state: PipelineState) -> dict:
    assert (
        state.patcher_output is not None
        and state.context_package is not None
        and state.diagnoser_output is not None
    )
    report = await run_five_gate_validator(
        state.patcher_output, state.context_package, state.diagnoser_output
    )
    return {"validator_report": report, "validation_history": [report]}


async def run_reflector(state: PipelineState) -> dict:
    reflector = ReflectorAgent(llm_client)
    with collect_llm_calls() as calls:
        try:
            decision = await reflector.reflect(state)
        except Exception as exc:
            # Fail safe: a Reflector error becomes give_up -> terminates to review.
            decision = ReflectorDecision(
                strategy="give_up",
                failure_root_cause=f"reflector failed: {type(exc).__name__}",
                constraint_for_next_attempt="",
                confidence_in_strategy=0.0,
                abandoning_hypothesis=state.hypothesis_used,
                new_hypothesis_to_try=None,
            )

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
        "llm_calls": calls,
    }


def route_after_diagnoser(state: PipelineState) -> str:
    # No diagnosis (failed) or it asked for clarification -> stop for human review.
    if state.diagnoser_output is None:
        return "done"
    if state.diagnoser_output.requires_clarification:
        return "done"
    return "run_patcher"


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


def _timed(name: str, fn: Callable[[PipelineState], Awaitable[dict]]) -> Callable[[PipelineState], Awaitable[dict]]:
    """Wrap a node so it records its own wall-clock into node_timings.

    Applied only in build_graph, so direct unit tests call the raw node and see
    no timing key in the return.
    """
    metric = _NODE_METRIC[name]

    async def wrapper(state: PipelineState) -> dict:
        start = perf_counter()
        result = await fn(state)
        return {**result, "node_timings": {metric: round((perf_counter() - start) * 1000, 1)}}

    return wrapper


def build_graph(checkpointer=None):
    """Compile the pipeline graph.

    ``checkpointer`` is an optional LangGraph checkpoint store.  When provided
    (e.g. an ``AsyncSqliteSaver`` from the FastAPI lifespan), every node
    transition is persisted so the pipeline can resume after an LLM timeout or
    be paused at ``human_review_flag=True`` nodes.  When None (the default)
    the graph compiles without persistence — unit tests and scripts are
    unaffected.

    Usage with checkpointing::

        config = {"configurable": {"thread_id": request_id}}
        result = await graph.ainvoke(state, config=config)
    """
    workflow = StateGraph(PipelineState)
    workflow.add_node("run_context_builder", _timed("run_context_builder", run_context_builder))
    workflow.add_node("run_diagnoser", _timed("run_diagnoser", run_diagnoser))
    workflow.add_node("run_patcher", _timed("run_patcher", run_patcher))
    workflow.add_node("run_validator", _timed("run_validator", run_validator))
    workflow.add_node("run_reflector", _timed("run_reflector", run_reflector))

    workflow.set_entry_point("run_context_builder")
    workflow.add_edge("run_context_builder", "run_diagnoser")
    workflow.add_conditional_edges(
        "run_diagnoser", route_after_diagnoser, {"run_patcher": "run_patcher", "done": END}
    )
    workflow.add_edge("run_patcher", "run_validator")
    workflow.add_conditional_edges(
        "run_validator", route_after_validator, {"done": END, "run_reflector": "run_reflector"}
    )
    workflow.add_conditional_edges(
        "run_reflector", route_after_reflector, {"done": END, "run_patcher": "run_patcher"}
    )
    return workflow.compile(checkpointer=checkpointer)


# Back-compat alias.
get_graph = build_graph
