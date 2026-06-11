from langgraph.graph import StateGraph, END
from backend.orchestrator.state import PipelineState

async def run_diagnoser(state: PipelineState) -> dict:
    from backend.agents.diagnoser import DiagnoserAgent
    from backend.llm.client import LLMClient
    diagnoser = DiagnoserAgent(LLMClient())
    diagnoser_output = await diagnoser.diagnose(state.context_package) if hasattr(diagnoser, 'diagnose') else await diagnoser.run(state.context_package)
    return {"diagnoser_output": diagnoser_output}

async def run_patcher(state: PipelineState) -> dict:
    from backend.agents.patcher import PatcherAgent
    from backend.llm.client import LLMClient
    
    modified_diagnosis = state.diagnoser_output.model_copy(deep=True)
    target_hyp = next((h for h in modified_diagnosis.hypotheses if h.id == state.hypothesis_used), None)
    
    if target_hyp:
        modified_diagnosis.hypotheses.remove(target_hyp)
        modified_diagnosis.hypotheses.insert(0, target_hyp)
        # Append constraint_for_next_attempt to prompt constraints implicitly via fix_direction
        if state.reflector_decision and state.reflector_decision.constraint_for_next_attempt:
            target_hyp.fix_direction += f"\n\nConstraint for next attempt: {state.reflector_decision.constraint_for_next_attempt}"

    patcher = PatcherAgent(LLMClient())
    patcher_output = await patcher.patch(state.context_package, modified_diagnosis)
    return {"patcher_output": patcher_output}

async def run_validator(state: PipelineState) -> dict:
    from backend.tools.validator import run_validator as _run_validator
    report = await _run_validator(state.patcher_output, state.context_package, state.diagnoser_output)
    return {"validator_report": report}

async def run_reflector(state: PipelineState) -> dict:
    from backend.agents.reflector import ReflectorAgent
    from backend.llm.client import LLMClient
    reflector = ReflectorAgent(LLMClient())
    decision = await reflector.reflect(state)
    
    failed_hypotheses = state.failed_hypotheses + [state.hypothesis_used]
    hypothesis_used = state.hypothesis_used
    if decision.strategy in ("escalate_h2", "escalate_h3") and decision.new_hypothesis_to_try:
        hypothesis_used = decision.new_hypothesis_to_try
        
    return {
        "reflector_decision": decision,
        "retry_count": state.retry_count + 1,
        "failed_hypotheses": failed_hypotheses,
        "hypothesis_used": hypothesis_used
    }

def route_after_validator(state: PipelineState) -> str:
    if state.validator_report and state.validator_report.overall_passed:
        return END
    if state.retry_count >= 2:
        return "done_with_flag"
    return "run_reflector"

def route_after_reflector(state: PipelineState) -> str:
    if state.reflector_decision and state.reflector_decision.strategy == "give_up":
        return "done_with_flag"
    return "run_patcher"

def mark_human_review(state: PipelineState) -> dict:
    return {"human_review_flag": True}

def get_graph():
    workflow = StateGraph(PipelineState)
    workflow.add_node("run_diagnoser", run_diagnoser)
    workflow.add_node("run_patcher", run_patcher)
    workflow.add_node("run_validator", run_validator)
    workflow.add_node("run_reflector", run_reflector)
    workflow.add_node("done_with_flag", mark_human_review)

    workflow.set_entry_point("run_diagnoser")
    workflow.add_edge("run_diagnoser", "run_patcher")
    workflow.add_edge("run_patcher", "run_validator")
    
    workflow.add_conditional_edges("run_validator", route_after_validator, {
        END: END,
        "done_with_flag": "done_with_flag",
        "run_reflector": "run_reflector"
    })
    
    workflow.add_conditional_edges("run_reflector", route_after_reflector, {
        "done_with_flag": "done_with_flag",
        "run_patcher": "run_patcher"
    })
    
    workflow.add_edge("done_with_flag", END)
    
    return workflow.compile()
