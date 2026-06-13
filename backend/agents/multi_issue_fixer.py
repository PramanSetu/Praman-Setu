"""Groq-powered one-file repair agent using deterministic bug-ledger evidence."""
from __future__ import annotations

import json

from pydantic import BaseModel, Field

from backend.llm.client import LLMCompleter
from backend.llm.models import model_for
from backend.tools.bug_ledger import BugLedger
from backend.tools.patch_applier import UnitRewrite


class MultiIssueFixResponse(BaseModel):
    summary: str = Field(min_length=1)
    issues_found: list[str] = Field(default_factory=list)
    units: list[UnitRewrite] = Field(default_factory=list)
    generated_tests: str = ""
    confidence: float = Field(ge=0.0, le=1.0)


_SYSTEM_PROMPT = """\
You are Praman Setu RepairAgent for a single pasted Python file.
You fix practical Python bugs by rewriting whole code units, not text fragments.

How to return fixes — a list of "units", each with a `target` and the COMPLETE
corrected `new_source` for that unit:
  * target = a top-level function or class name  -> new_source is the whole
    corrected function/class (full body, correct indentation).
  * target = "<module>"  -> new_source is the whole corrected block of top-level
    executable code (e.g. the `if __name__ == "__main__":` section).
  * target = "<file>"  -> new_source is the ENTIRE corrected file. You MUST use a
    single "<file>" unit when the original code has a SyntaxError (it cannot be
    parsed for unit-level edits). You may also use it for sweeping changes.

Rules:
1. new_source must be complete and self-consistent: a function unit is the full
   `def ...:` through its last line; never a partial snippet. Indentation must be
   valid Python.
2. To fix a method, rewrite its whole enclosing class as one unit.
3. Fix all visible practical bugs supported by the bug ledger: syntax errors,
   undefined names, wrong variable names, bad method names, IndexError, KeyError,
   TypeError, ZeroDivisionError, top-level script crashes, insecure calls
   (eval/exec), and simple clear logic errors.
4. Do not refactor, rename public APIs gratuitously, remove functionality, or
   invent unrelated behavior. Keep every unit you touch as close to the original
   as the fix allows.
5. If intent is ambiguous, make the smallest safe change that lets the script run,
   and mention the risk in `reason`.
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

Return only a JSON object. Prefer per-function / "<module>" units so each fix is
small and independently verifiable. Use a single "<file>" unit ONLY when the code
has a SyntaxError (so it can't be parsed for unit edits) or for a sweeping change.
Each new_source must be the COMPLETE corrected unit with valid indentation.
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
