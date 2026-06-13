"""Groq-powered one-file repair agent using deterministic bug-ledger evidence."""
from __future__ import annotations

import json

from pydantic import BaseModel, Field

from backend.llm.client import LLMCompleter
from backend.llm.models import model_for
from backend.tools.bug_ledger import BugLedger
from backend.tools.patch_applier import CodeEdit


class MultiIssueFixResponse(BaseModel):
    summary: str = Field(min_length=1)
    issues_found: list[str] = Field(default_factory=list)
    edits: list[CodeEdit] = Field(default_factory=list)
    generated_tests: str = ""
    confidence: float = Field(ge=0.0, le=1.0)


_SYSTEM_PROMPT = """\
You are Praman Setu RepairAgent for a single pasted Python file.
You fix practical Python bugs with exact minimal edits.

Rules:
1. Return exact old/new code-block edits, not a full rewritten file.
2. Each old block must be copied exactly from the input code and should identify one location.
3. Fix all visible practical bugs supported by the bug ledger: syntax errors, undefined names,
   wrong variable names, bad method names, IndexError, KeyError, TypeError, ZeroDivisionError,
   top-level script crashes, and simple clear logic errors.
4. Do not refactor, rename public APIs gratuitously, remove functionality, or invent unrelated behavior.
5. If intent is ambiguous, make the smallest safe change that lets the script run, and mention the risk.
6. generated_tests may be empty, but include pytest tests when a behavior is inferable.
7. Return only JSON matching the schema. No markdown.
"""

_MODEL = model_for("patcher").primary
_FALLBACK = model_for("patcher").fallback


class MultiIssueFixerAgent:
    def __init__(self, llm_client: LLMCompleter):
        self.llm = llm_client

    async def fix(
        self,
        code: str,
        ledger: BugLedger,
        *,
        validation_feedback: str = "",
    ) -> MultiIssueFixResponse:
        numbered = "\n".join(f"{index:>4} | {line}" for index, line in enumerate(code.splitlines(), 1))
        schema = json.dumps(MultiIssueFixResponse.model_json_schema(), indent=2)
        feedback = f"\nVALIDATION FEEDBACK FROM PREVIOUS ATTEMPT\n{validation_feedback}\n" if validation_feedback else ""
        prompt = f"""Repair this single Python file using exact edits.

BUG LEDGER
{ledger.prompt_summary()}
{feedback}
CODE WITH LINE NUMBERS
{numbered}

RESPONSE JSON SCHEMA
{schema}

Return only a JSON object. Each edit.old must be an exact contiguous substring
from the original unnumbered code. Prefer several small edits over one large
rewrite. If the file has a SyntaxError, first make it compile, but also fix other
clear ledger-backed bugs when the exact edit is obvious.
"""
        response = await self.llm.complete(
            _MODEL,
            [{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
            MultiIssueFixResponse,
            temperature=0.1,
            max_tokens=3500,
            timeout=30,
            fallback_model=_FALLBACK,
            reasoning_effort="none",
            reasoning_format="hidden",
        )
        if not isinstance(response, MultiIssueFixResponse):
            response = MultiIssueFixResponse.model_validate(response)
        return response
