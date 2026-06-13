"""Holistic Fixer — fix every bug in a file in one LLM pass.

The recall-first, low-call-count alternative to the per-bug iterative loop: the
LLM reads the whole file and returns the fully-corrected file plus a list of the
bugs it fixed. The orchestrator then VERIFIES by running it in the sandbox; if it
still crashes, the file + the new error are fed back for another whole-file pass.
"""
from __future__ import annotations

import json

from pydantic import BaseModel, Field

from backend.llm.client import LLMCompleter
from backend.llm.models import model_for


class FixedBug(BaseModel):
    line: int | None = None
    bug_type: str
    explanation: str


class HolisticFixResponse(BaseModel):
    fixed_code: str = Field(min_length=1)
    bugs_fixed: list[FixedBug] = Field(default_factory=list)


_SYSTEM = (
    "You are an expert Python debugger. You fix EVERY bug in a file in a single "
    "pass and return the complete corrected file. You change only what is needed "
    "to fix bugs — you never remove functionality, rename things gratuitously, or "
    "alter intended behavior."
)

_MODEL = model_for("patcher").primary
_FALLBACK = model_for("patcher").fallback


class HolisticFixerError(Exception):
    pass


class HolisticFixerAgent:
    def __init__(self, llm_client: LLMCompleter):
        self.llm = llm_client

    async def fix(
        self, code: str, latest_error: str | None = None, error_line: int | None = None
    ) -> HolisticFixResponse:
        numbered = "\n".join(f"{i:>3} | {line}" for i, line in enumerate(code.splitlines(), start=1))
        schema = json.dumps(HolisticFixResponse.model_json_schema(), indent=2)
        error_hint = ""
        if latest_error:
            error_hint = f"\nWhen run, it currently fails with: {latest_error} (line {error_line}).\n"

        user_prompt = f"""Fix EVERY bug in this Python file and return the complete corrected file.

CODE (line-numbered):
{numbered}
{error_hint}
Fix all of these: SyntaxError (missing colon, bad indent), NameError / misspelled
or undefined variables, IndexError / off-by-one (e.g. range(len(x) + 1)), KeyError
(missing dict key), TypeError (e.g. str + int), ZeroDivisionError, and clear logic
errors. Keep input() calls. Preserve structure and intended behavior — change only
what is needed.

fixed_code must be the ENTIRE corrected file. bugs_fixed must list each bug you
fixed (line, bug_type, one-sentence explanation).

RESPONSE JSON SCHEMA
{schema}

Return ONLY a JSON object matching the schema. No markdown, no prose outside JSON.
"""
        response = await self.llm.complete(
            _MODEL,
            [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user_prompt}],
            HolisticFixResponse,
            temperature=0.1,
            max_tokens=3000,
            timeout=30,
            fallback_model=_FALLBACK,
            reasoning_effort="none",
            reasoning_format="hidden",
        )
        if not isinstance(response, HolisticFixResponse):
            try:
                response = HolisticFixResponse.model_validate(response)
            except Exception as exc:
                raise HolisticFixerError(f"Invalid holistic-fix response: {exc}") from exc
        return response
