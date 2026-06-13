"""Syntax Fixer — the SyntaxError fast path.

A SyntaxError can't go through the behavioral-test pipeline: you can't write a
runtime test for code that doesn't parse. This agent fixes ONLY the syntax error
(minimal change) and returns the complete corrected module. The graph validates it
with parse-only (Gate 1): if it parses, the syntax bug is proven fixed.
"""
from __future__ import annotations

import json

from pydantic import BaseModel, Field

from backend.llm.client import LLMCompleter
from backend.llm.models import model_for


class SyntaxFixResponse(BaseModel):
    fixed_code: str = Field(min_length=1)


_SYSTEM_PROMPT = (
    "You fix ONLY Python syntax errors. Return the complete corrected module with "
    "the minimal change needed to make it parse. Do NOT fix logic bugs, do NOT "
    "refactor, do NOT rename anything, do NOT change behavior — only make it "
    "syntactically valid."
)

_MODEL = model_for("diagnoser").primary
_FALLBACK = model_for("diagnoser").fallback


class SyntaxFixerError(Exception):
    pass


class SyntaxFixerAgent:
    def __init__(self, llm_client: LLMCompleter):
        self.llm = llm_client

    async def fix(self, full_code: str, error_message: str, error_line: int | None) -> str:
        schema = json.dumps(SyntaxFixResponse.model_json_schema(), indent=2)
        user_prompt = f"""BROKEN PYTHON MODULE
SyntaxError at line {error_line}: {error_message}

{full_code}

RESPONSE JSON SCHEMA
{schema}

Return ONLY a JSON object matching the schema. fixed_code must be the ENTIRE
corrected module. Fix ONLY the syntax error — change as few characters as
possible. Do not alter logic, names, structure, or behavior.
"""
        response = await self.llm.complete(
            _MODEL,
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            SyntaxFixResponse,
            temperature=0.0,
            max_tokens=2000,
            timeout=15,
            fallback_model=_FALLBACK,
        )
        if not isinstance(response, SyntaxFixResponse):
            try:
                response = SyntaxFixResponse.model_validate(response)
            except Exception as exc:
                raise SyntaxFixerError(f"Invalid syntax-fix response: {exc}") from exc
        return response.fixed_code
