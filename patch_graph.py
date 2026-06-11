import re

with open("backend/orchestrator/graph.py", "r") as f:
    text = f.read()

new_patcher = r"""async def run_patcher(state: PipelineState) -> dict:
    from backend.agents.patcher import PatcherAgent
    from backend.llm.client import LLMClient
    
    # Filter/reorder hypothesis so Patcher gets the correctly scoped one at index 0
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
"""

with open("backend/orchestrator/graph.py", "w") as f:
    f.write(text.replace(text[text.find("async def run_patcher"):text.find("async def run_reflector")], new_patcher))
    
