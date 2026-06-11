import json
from typing import Any
from backend.orchestrator.state import ReflectorDecision, PipelineState
from backend.llm.client import LLMCompleter, GROQ_PRIMARY_MODEL

SYSTEM_PROMPT = """You are Praman Setu Reflector, a strategic recovery agent.
When a patch fails validation, decide whether to refine the current approach or escalate to a new hypothesis.
You must return only a valid JSON object matching the ReflectorDecision schema.
- If retry_count == 1 and H2 exists, prefer to 'escalate_h2'.
- If retry_count == 1 and H2 already tried, prefer 'escalate_h3'.
- If all hypotheses exhausted, 'give_up'."""

class ReflectorAgent:
    def __init__(self, llm_client: LLMCompleter):
        self.llm = llm_client

    async def reflect(self, state: PipelineState) -> ReflectorDecision:
        schema = json.dumps(ReflectorDecision.model_json_schema(), indent=2)
        
        failed_gate = "Unknown"
        error_msg = ""
        if state.validator_report and state.validator_report.detailed_failures:
            error_msg = "\n".join(state.validator_report.detailed_failures)
            failed_gate = "Detailed Failures"

        available_hypos = [h.id for h in state.diagnoser_output.hypotheses] if state.diagnoser_output else []

        user_prompt = f"""VALIDATION FAILED
Gate/Errors: {failed_gate}
{error_msg}

CURRENT HYPOTHESIS USED: {state.hypothesis_used}
RETRY COUNT: {state.retry_count} (first failure = 1, second = 2)

AVAILABLE HYPOTHESES:
{available_hypos}

ALREADY FAILED HYPOTHESES:
{state.failed_hypotheses}

Provide your strategy following the JSON schema:
{schema}
"""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]

        response = await self.llm.complete(
            GROQ_PRIMARY_MODEL,
            messages,
            ReflectorDecision,
            temperature=0.0,
            max_tokens=300,
            timeout=15
        )

        if not isinstance(response, ReflectorDecision):
            response = ReflectorDecision.model_validate(response)
        
        return response
