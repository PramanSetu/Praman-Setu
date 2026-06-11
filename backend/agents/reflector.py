"""Reflector Agent — strategic retry decision on validation failure (Agent 5)."""
from __future__ import annotations

import json

from pydantic import ValidationError

from backend.llm.client import LLMCompleter
from backend.llm.models import model_for
from backend.orchestrator.state import PipelineState, ReflectorDecision

SYSTEM_PROMPT = """You are Praman Setu Reflector, a strategic recovery agent.
When a patch fails validation, decide whether to refine the current approach or escalate to a new hypothesis.
You must return only a valid JSON object matching the ReflectorDecision schema.
- If the current hypothesis can be salvaged by addressing the specific failure, prefer 'refine_current'.
- If H2 has not been tried yet, prefer 'escalate_h2'.
- If H2 was already tried, prefer 'escalate_h3'.
- If all hypotheses are exhausted, 'give_up'."""

_GROQ_MODEL = model_for("reflector").primary
_OLLAMA_FALLBACK = model_for("reflector").fallback


class ReflectorError(Exception):
    pass


class ReflectorAgent:
    def __init__(self, llm_client: LLMCompleter):
        self.llm = llm_client

    async def reflect(self, state: PipelineState) -> ReflectorDecision:
        schema = json.dumps(ReflectorDecision.model_json_schema(), indent=2)

        error_msg = ""
        if state.validator_report and state.validator_report.detailed_failures:
            error_msg = "\n".join(state.validator_report.detailed_failures)

        available = [h.id for h in state.diagnoser_output.hypotheses] if state.diagnoser_output else []

        user_prompt = f"""VALIDATION FAILED
{error_msg}

CURRENT HYPOTHESIS USED: {state.hypothesis_used}
RETRY COUNT: {state.retry_count} (first failure = 0, second = 1)

AVAILABLE HYPOTHESES: {available}
ALREADY FAILED HYPOTHESES: {state.failed_hypotheses}

Provide your strategy following the JSON schema:
{schema}
"""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        response = await self.llm.complete(
            _GROQ_MODEL,
            messages,
            ReflectorDecision,
            temperature=0.0,
            max_tokens=300,
            timeout=15,
            fallback_model=_OLLAMA_FALLBACK,
        )

        if not isinstance(response, ReflectorDecision):
            try:
                response = ReflectorDecision.model_validate(response)
            except ValidationError as exc:
                raise ReflectorError(f"Invalid Reflector response: {exc}") from exc

        return response
