"""Explainer Agent — turns a RepairV2Result into a human-readable narrative.

This is the user-facing layer. It does NOT judge correctness — that is already
proven mechanically by the validator (compile + sandbox run + bandit + tests).
Its job is to say, in plain language: what was broken, what was fixed, what is
flagged for human review, and how the result was verified.

The verification line is derived deterministically from the validated status so
the proof claim can never be hallucinated. The narrative (headline, per-fix
descriptions, flagged items) comes from one LLM call over the before/after code,
with a deterministic fallback so the explainer never blocks the response.
"""
from __future__ import annotations

import json

from pydantic import BaseModel, Field

from backend.llm.client import LLMCompleter
from backend.llm.models import model_for
from backend.orchestrator.repair_v2 import RepairV2Result

_MODEL = model_for("explainer").primary
_FALLBACK = model_for("explainer").fallback


class FixDetail(BaseModel):
    issue: str = Field(min_length=1)   # what was wrong, in plain language
    fix: str = Field(min_length=1)     # what was changed
    category: str = "bug"              # e.g. SyntaxError, NameError, Security, Logic


class _ExplainerLLMOut(BaseModel):
    headline: str = Field(min_length=1)
    fixes: list[FixDetail] = Field(default_factory=list)
    flagged: list[str] = Field(default_factory=list)


class RepairExplanation(BaseModel):
    status: str
    headline: str
    fixes: list[FixDetail] = Field(default_factory=list)
    flagged: list[str] = Field(default_factory=list)
    verification: str


_VERIFICATION = {
    "clean": (
        "Verified in the sandbox: the file compiles, runs without errors, and "
        "passes the security scan."
    ),
    "insecure": (
        "The code runs, but a security issue remains, so the result was not "
        "accepted as clean."
    ),
    "no_progress": (
        "No safe automated fix could be applied — every proposed change was "
        "rejected before it could be accepted."
    ),
    "unresolved": (
        "Partially repaired and verified in the sandbox; the remaining issues "
        "could not be fixed automatically without your intent."
    ),
}


_SYSTEM_PROMPT = """\
You are Praman Setu Explainer. You write a clear, honest, non-technical-user-
friendly summary of an automated Python repair. You do NOT verify or re-judge the
fix — correctness was already proven by a sandbox. Your job is only to explain.

Rules:
1. Describe ONLY changes that actually appear between the original and final code.
2. One `fixes` entry per distinct bug actually fixed: `issue` = what was wrong,
   `fix` = what changed, `category` = the bug kind (SyntaxError, NameError,
   IndexError, TypeError, ZeroDivisionError, Security, Logic, etc.).
3. Put anything still broken, risky, or dependent on the user's intent (e.g. a
   logic choice the tool had to guess) into `flagged` — be honest about limits.
4. `headline` is one plain sentence summarising the outcome.
5. Return only JSON matching the schema. No markdown.
"""


class ExplainerAgent:
    def __init__(self, llm_client: LLMCompleter):
        self.llm = llm_client

    async def explain(self, result: RepairV2Result) -> RepairExplanation:
        verification = _VERIFICATION.get(result.status, "")
        try:
            out = await self._narrate(result)
        except Exception:  # noqa: BLE001 — explainer must never block the response
            return _fallback(result, verification)
        return RepairExplanation(
            status=result.status,
            headline=out.headline,
            fixes=out.fixes,
            flagged=out.flagged,
            verification=verification,
        )

    async def _narrate(self, result: RepairV2Result) -> _ExplainerLLMOut:
        schema = json.dumps(_ExplainerLLMOut.model_json_schema(), indent=2)
        reported = sorted({issue for a in result.attempts for issue in a.issues_found})
        remaining = f"\nKNOWN UNRESOLVED: {result.remaining_error}" if result.remaining_error else ""
        prompt = f"""Explain this automated repair.

REPAIR STATUS: {result.status}
ISSUES THE REPAIR AGENT REPORTED (may be noisy/duplicated):
{json.dumps(reported, indent=2)}{remaining}

ORIGINAL CODE
{result.original_code}

FINAL CODE
{result.final_code}

RESPONSE JSON SCHEMA
{schema}

Compare original vs final. List each real fix, and flag anything left unresolved
or that depended on guessing the user's intent. Return only JSON.
"""
        response = await self.llm.complete(
            _MODEL,
            [{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
            _ExplainerLLMOut,
            temperature=0.2,
            max_tokens=1200,
            timeout=20,
            fallback_model=_FALLBACK,
        )
        if not isinstance(response, _ExplainerLLMOut):
            response = _ExplainerLLMOut.model_validate(response)
        return response


def _fallback(result: RepairV2Result, verification: str) -> RepairExplanation:
    """Deterministic explanation assembled from the structured result.

    Used when the LLM narration call fails so the API always returns something.
    """
    reported = sorted({issue for a in result.attempts for issue in a.issues_found})
    fixes = [FixDetail(issue=item, fix="Addressed in the applied repair.", category="bug") for item in reported]
    flagged: list[str] = []
    if result.remaining_error:
        flagged.append(result.remaining_error)
    if result.status == "clean":
        headline = f"Repaired the file — {len(fixes)} issue(s) fixed and verified."
    elif result.status == "unresolved":
        headline = "Fixed some issues; others could not be resolved automatically."
    else:
        headline = f"Repair ended with status '{result.status}'."
    return RepairExplanation(
        status=result.status,
        headline=headline,
        fixes=fixes,
        flagged=flagged,
        verification=verification,
    )
