"""Diagnoser Agent for the Praman Setu pipeline."""
from __future__ import annotations

import asyncio
from typing import Any

from pydantic import ValidationError

from backend.agents.prompts.diagnoser_prompt import render_diagnoser_prompt
from backend.llm.client import GROQ_PRIMARY_MODEL, LLMCompleter
from backend.orchestrator.state import ContextPackage, DiagnoserOutput, Hypothesis


class DiagnoserError(Exception):
    pass


class DiagnoserAgent:
    def __init__(self, llm_client: LLMCompleter):
        self.llm = llm_client

    async def diagnose(self, context: ContextPackage) -> DiagnoserOutput:
        messages = render_diagnoser_prompt(context)
        try:
            output = await self._complete(messages)
            return self._validate_output(output)
        except (ValidationError, ValueError, TypeError, DiagnoserError) as first_error:
            retry_messages = render_diagnoser_prompt(context, retry=True)
            try:
                output = await self._complete(retry_messages)
                return self._validate_output(output)
            except (ValidationError, ValueError, TypeError, DiagnoserError) as retry_error:
                raise DiagnoserError(
                    f"Invalid LLM response after retry: {retry_error}; first error: {first_error}"
                ) from retry_error
        except TimeoutError as exc:
            raise DiagnoserError("LLM timeout after 10s") from exc
        except asyncio.TimeoutError as exc:
            raise DiagnoserError("LLM timeout after 10s") from exc

        raise DiagnoserError("Diagnoser failed before producing output")

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
            )
            for index, hypothesis in enumerate(sorted_hypotheses, start=1)
        ]

        if not output.generated_test.strip():
            raise DiagnoserError("Diagnoser output generated_test must not be empty")
        if "def test_" not in output.generated_test:
            raise DiagnoserError("Diagnoser output generated_test must contain a pytest function")

        return DiagnoserOutput(
            root_cause=output.root_cause,
            hypotheses=normalized_hypotheses,
            generated_test=output.generated_test,
        )
