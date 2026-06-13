"""Diagnoser Agent for the Praman Setu pipeline."""
from __future__ import annotations

import asyncio
from typing import Any

from pydantic import ValidationError

from backend.agents.prompts.diagnoser_prompt import render_diagnoser_prompt
from backend.llm.client import GROQ_PRIMARY_MODEL, LLMCompleter
from backend.orchestrator.state import ContextPackage, DiagnoserOutput, Hypothesis
from backend.tools.test_quality import generated_test_failure


class DiagnoserError(Exception):
    pass


_DIAGNOSE_ERRORS = (ValidationError, ValueError, TypeError, DiagnoserError, TimeoutError, asyncio.TimeoutError)


class DiagnoserAgent:
    def __init__(self, llm_client: LLMCompleter):
        self.llm = llm_client

    async def diagnose(self, context: ContextPackage) -> DiagnoserOutput:
        # Structural attempt + one retry (raises only on genuinely invalid structure).
        try:
            output = await self._attempt(context, retry=False)
        except _DIAGNOSE_ERRORS as first_error:
            try:
                output = await self._attempt(context, retry=True)
            except _DIAGNOSE_ERRORS as retry_error:
                raise DiagnoserError(
                    f"Invalid LLM response after retry: {retry_error}; first error: {first_error}"
                ) from retry_error

        # If the generated test is weak, try ONCE more for a better one — but keep
        # the best-effort diagnosis either way. We never dead-end on test quality:
        # integration proof (whole program runs clean) is the downstream backstop.
        if generated_test_failure(output.generated_test):
            try:
                improved = await self._attempt(context, retry=True)
                if not generated_test_failure(improved.generated_test):
                    output = improved
            except _DIAGNOSE_ERRORS:
                pass
        return output

    async def _attempt(self, context: ContextPackage, *, retry: bool) -> DiagnoserOutput:
        messages = render_diagnoser_prompt(context, retry=retry)
        return self._validate_output(await self._complete(messages))

    async def _complete(self, messages: list[dict[str, str]]) -> DiagnoserOutput:
        return await self.llm.complete(
            model=GROQ_PRIMARY_MODEL,
            messages=messages,
            schema=DiagnoserOutput,
            temperature=0.2,
            max_tokens=600,
            timeout=10,
            use_json_schema=True,
        )

    def _validate_output(self, output: Any) -> DiagnoserOutput:
        if not isinstance(output, DiagnoserOutput):
            output = DiagnoserOutput.model_validate(output)

        if len(output.hypotheses) != 3:
            raise DiagnoserError("Diagnoser output must contain exactly 3 hypotheses")

        ids = {hypothesis.id for hypothesis in output.hypotheses}
        if ids != {"H1", "H2", "H3"}:
            raise DiagnoserError("Diagnoser output hypotheses must have ids H1, H2, and H3")

        sorted_hypotheses = sorted(output.hypotheses, key=lambda item: item.confidence, reverse=True)
        normalized_hypotheses = [
            Hypothesis(
                id=f"H{index}",
                theory=hypothesis.theory,
                confidence=hypothesis.confidence,
                fix_direction=hypothesis.fix_direction,
                evidence=hypothesis.evidence,
                risk_if_wrong=hypothesis.risk_if_wrong,
            )
            for index, hypothesis in enumerate(sorted_hypotheses, start=1)
        ]

        return DiagnoserOutput(
            root_cause=output.root_cause,
            affected_scope=output.affected_scope,
            evidence=output.evidence,
            hypotheses=normalized_hypotheses,
            generated_test=output.generated_test,
            test_assertion_summary=output.test_assertion_summary,
            requires_clarification=output.requires_clarification,
            clarification_question=output.clarification_question,
        )
