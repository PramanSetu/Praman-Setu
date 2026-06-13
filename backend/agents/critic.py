"""Critic Agent — semantic review of an accepted repair.

Scope is deliberately narrow. Mechanical correctness is ALREADY proven by the
validator (the patched file compiles, runs clean in the sandbox, passes bandit,
and any generated tests pass). The Critic must NOT re-litigate that. It judges
only the things the gates cannot:

  * root cause vs symptom masking — did the fix solve the bug, or just hide it
    (e.g. a bare ``except: pass`` that swallows the error)?
  * intent preservation — did a whole-unit rewrite quietly change unrelated
    behaviour?
  * confidence — which fixes are solid vs. a guess that needs the user's intent?

Its ``needs_human_review`` list is the authoritative "flag for a human" output,
sharper than the Explainer's narrative-level flags. Like the Explainer it has a
deterministic fallback so it never blocks the response.
"""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field

from backend.llm.client import LLMCompleter
from backend.llm.models import model_for
from backend.orchestrator.repair_v2 import RepairV2Result

_MODEL = model_for("critic").primary
_FALLBACK = model_for("critic").fallback


class FixAssessment(BaseModel):
    target: str = Field(min_length=1)          # function/area the fix touched
    addresses_root_cause: bool = True          # False => masks the symptom
    preserves_intent: bool = True              # False => changed unrelated behaviour
    confidence: Literal["high", "medium", "low"] = "high"
    concern: str = ""                          # required when any verdict is negative/low


class LogicConcern(BaseModel):
    """A suspected latent logic bug in the working code — something that runs fine
    but is probably wrong (and so was never surfaced as a crash or syntax error)."""

    location: str = Field(min_length=1)        # function / line / area
    issue: str = Field(min_length=1)           # the suspected logic flaw, concretely
    severity: Literal["high", "medium", "low"] = "medium"


class CritiqueReport(BaseModel):
    overall: Literal["solid", "acceptable", "risky", "unassessed"]
    summary: str
    assessments: list[FixAssessment] = Field(default_factory=list)
    logic_audit: list[LogicConcern] = Field(default_factory=list)
    needs_human_review: list[str] = Field(default_factory=list)


_SYSTEM_PROMPT = """\
You are Praman Setu Critic. The repair you are reviewing has ALREADY been proven
in a sandbox: it compiles, runs without errors, and passes a security scan. Do
NOT re-check or comment on whether it runs, compiles, or is secure — that is
settled. Your job is the things execution cannot decide. You have TWO jobs.

JOB 1 — Review the fixes (the diff between original and final):
1. Root cause vs symptom masking — does each fix actually solve the bug, or just
   hide it (e.g. swallowing an exception, returning a placeholder, looping to
   avoid an error)? Set addresses_root_cause=false and explain in `concern`.
2. Intent preservation — did a rewrite change behaviour unrelated to the bug?
   Set preserves_intent=false and explain.
3. Confidence — high if the fix is obviously correct; low if the tool had to
   guess the user's intent (e.g. what to do on divide-by-zero / empty input).
Record these in `assessments`.

JOB 2 — Audit the WHOLE final program for LATENT logic bugs:
Read every function in the final code, including code that was NOT changed. A
program can run cleanly and still be wrong. Look hard for:
  * wrong formulas / operators (e.g. interest as `balance * rate` instead of
    `balance * (1 + rate/100)`; discount as `price - percent` instead of a %),
  * bad initial values (e.g. `max_val = 0` that breaks for all-negative input),
  * ignored return values (e.g. calling a function that returns False on failure
    but proceeding anyway — money/state created incorrectly),
  * off-by-one and boundary errors (e.g. `> 80` where `>= 80` was meant),
  * incorrect accumulation, mutation of shared state, or wrong comparison.
Record each suspected latent bug in `logic_audit` with location, issue, severity.
It is BETTER to flag a borderline case than to miss a real one — but only flag
things that are genuinely suspicious, with a concrete reason.

Finally, `needs_human_review` = the union of fix concerns and logic_audit issues,
phrased as short action items for a human.
overall = "solid" (no concerns at all), "acceptable" (only minor/low-severity or
low-confidence items), or "risky" (a fix masks the bug, breaks intent, or a
high-severity latent logic bug exists). Return only JSON. No markdown.
"""


class CriticAgent:
    def __init__(self, llm_client: LLMCompleter):
        self.llm = llm_client

    async def review(self, result: RepairV2Result) -> CritiqueReport:
        try:
            return await self._review(result)
        except Exception:  # noqa: BLE001 — critic must never block the response
            return _fallback(result)

    async def _review(self, result: RepairV2Result) -> CritiqueReport:
        schema = json.dumps(CritiqueReport.model_json_schema(), indent=2)
        remaining = f"\nKNOWN UNRESOLVED: {result.remaining_error}" if result.remaining_error else ""
        prompt = f"""Review this repair for semantic quality only.

REPAIR STATUS: {result.status}{remaining}

ORIGINAL CODE
{result.original_code}

FINAL (ACCEPTED) CODE
{result.final_code}

RESPONSE JSON SCHEMA
{schema}

Remember: it already compiles, runs clean, and passed security. (1) Review the
fixes for root-cause/intent/confidence, AND (2) audit every function in the FINAL
code for latent logic bugs (wrong formulas, bad initial values, ignored return
values, off-by-one/boundary errors) — including code that was never changed.
Return only JSON.
"""
        response = await self.llm.complete(
            _MODEL,
            [{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
            CritiqueReport,
            temperature=0.1,
            max_tokens=1200,
            timeout=20,
            fallback_model=_FALLBACK,
        )
        if not isinstance(response, CritiqueReport):
            response = CritiqueReport.model_validate(response)
        return response


def _fallback(result: RepairV2Result) -> CritiqueReport:
    """Neutral report when the LLM review fails — never blocks, never over-claims."""
    needs_review = [result.remaining_error] if result.remaining_error else []
    return CritiqueReport(
        overall="unassessed",
        summary="Semantic review unavailable; mechanical validation (compile, run, security) still holds.",
        assessments=[],
        needs_human_review=needs_review,
    )
