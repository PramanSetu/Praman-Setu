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


# General programming-correctness axes — domain-agnostic categories of how code
# goes wrong, NOT facts about any particular application.
LogicAxis = Literal[
    "return_contract",   # a returned success/failure or result value is dropped/wrong
    "boundary",          # off-by-one, > vs >=, inclusive/exclusive ranges
    "init_value",        # accumulator / min / max / counter seeded wrong
    "invariant",         # a state invariant the code clearly implies is broken
    "edge_case",         # empty / zero / negative / None / single-element input
    "shared_state",      # mutating a caller's object or a shared/default structure
    "other",
]


class LogicConcern(BaseModel):
    """A suspected latent logic bug in the working code — something that runs fine
    but is probably wrong (and so was never surfaced as a crash or syntax error)."""

    location: str = Field(min_length=1)        # function / line / area
    axis: LogicAxis = "other"                  # which general correctness axis failed
    issue: str = Field(min_length=1)           # the suspected flaw (or, if needs_intent, a question)
    severity: Literal["high", "medium", "low"] = "medium"
    needs_intent: bool = False                 # True => correctness depends on the user's intent


class CritiqueReport(BaseModel):
    overall: Literal["solid", "acceptable", "risky", "unassessed"]
    summary: str
    assessments: list[FixAssessment] = Field(default_factory=list)
    logic_audit: list[LogicConcern] = Field(default_factory=list)
    needs_human_review: list[str] = Field(default_factory=list)


_SYSTEM_PROMPT = """\
You are Praman Setu Critic. The repair already compiles, runs clean, and passed a
security scan — do NOT re-check or comment on that; it is settled. You judge only
what execution cannot decide. You are given the fixes and a list of issues a
static linter ALREADY found deterministically — do not re-report those.

Do TWO things.

JOB 1 — Assess each fix (original vs final): set addresses_root_cause (false if it
masks the bug, e.g. swallowing an error or returning a placeholder),
preserves_intent (false if it changed unrelated behaviour), and confidence. Record
in `assessments`.

JOB 2 — Run this CHECKLIST over EVERY function in the final code (including
UNCHANGED code). The checklist is a thinking aid, NOT a quota: most functions are
fine and produce ZERO concerns. Record a concern ONLY when you can name the
concrete input and the WRONG result it produces (e.g. "highest([-5,-2]) returns 0,
but no element is 0"). Do NOT emit open questions ("how does it handle an empty
list?", "is an empty string valid?") — an axis you merely *thought about* is not a
finding. If a function is correct, say nothing about it. Set `axis`:

  • return_contract — does it return what callers rely on, on all paths? is a
    returned success/failure value actually used by the caller, or dropped?
  • boundary — off-by-one / comparison edges: `>` vs `>=`, `range(len(x))` vs
    `+1`, inclusive vs exclusive ranges.
  • init_value — are accumulators / min / max / counters seeded correctly? (e.g. a
    "maximum" seeded at 0 is wrong for all-negative input.)
  • invariant — does the function keep an invariant the surrounding code CLEARLY
    implies (a counter stays in sync, state stays consistent, nothing is created
    or lost that shouldn't be)? Only if the invariant is evident from the code.
  • edge_case — empty input, zero, negative, None, single element.
  • shared_state — mutating a caller's object or a shared/default structure.

These axes are GENERAL programming-correctness checks that apply to ANY program.
Do NOT assume a domain (bank, shop, game, …) and do NOT invent domain rules.

For each concern set `severity` and `needs_intent` — this decides whether it gets
AUTO-FIXED, so classify carefully:
  • needs_intent = FALSE, severity = "high" when the code is demonstrably wrong for
    some VALID input — there is a clearly-correct fix and no policy choice involved.
    These WILL be fixed, so be decisive. Examples (all needs_intent=false):
      – a max/min/selection seeded with a literal that fails for valid input
        (`best = 0` returns 0 for an all-negative list — a max must be a member);
      – a function that returns the wrong type, or whose return is dropped by a
        caller that needed it (success/failure ignored → corrupt state);
      – an index/loop that goes out of range or skips elements for valid sizes;
      – an accumulation/initialization that's provably wrong.
    Phrase `issue` as a STATEMENT of the bug and its fix ("best starts at 0, so an
    all-negative list returns 0; seed it from the first element") — never a yes/no
    question like "does it return correctly?".
  • needs_intent = TRUE only when correctness depends on a POLICY the code does not
    state — there is no single right answer without the user. Examples:
      – is a grade boundary inclusive (`>` vs `>=`)?
      – is an argument a percentage or a multiplier or an absolute amount?
    Phrase `issue` as a QUESTION; never guess a domain answer.
When unsure whether something is objective or intent: if you can name the single
correct fix without assuming a policy, it is OBJECTIVE (needs_intent=false).

`needs_human_review` = short action items (objective bugs + intent questions).
overall = "solid" (nothing), "acceptable" (only low-severity and/or needs_intent
items), "risky" (a clear high-severity bug, or a fix that masks the bug). Return
only JSON. No markdown.
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
        already_detected = _deterministic_findings(result)
        prompt = f"""Review this repair for semantic quality only.

REPAIR STATUS: {result.status}{remaining}

ALREADY DETECTED by a static linter (do NOT re-report — focus your reasoning on
the checklist axes a linter can't decide):
{already_detected}

ORIGINAL CODE
{result.original_code}

FINAL (ACCEPTED) CODE
{result.final_code}

RESPONSE JSON SCHEMA
{schema}

(1) Assess each fix (root-cause / intent / confidence). (2) Run the per-function
checklist over EVERY function in the FINAL code (return_contract, boundary,
init_value, invariant, edge_case, shared_state) — including unchanged code. Use
needs_intent=true (phrased as a question) when correctness depends on the user's
intent. Do not assume any domain. Return only JSON.
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


_SEMANTIC_KINDS = {"mutable_default", "ignored_return", "shared_state_alias", "swallowed_exception"}


def _deterministic_findings(result: RepairV2Result) -> str:
    """The semantic-lint warnings already found on the final code — fed to the
    Critic so it corroborates rather than rediscovers them and spends its
    reasoning on the axes a linter can't decide."""
    lines = [
        f"- {issue.kind} at line {issue.line}: {issue.message}"
        for issue in result.ledger.issues
        if issue.kind in _SEMANTIC_KINDS
    ]
    return "\n".join(lines) if lines else "(none)"


def _fallback(result: RepairV2Result) -> CritiqueReport:
    """Neutral report when the LLM review fails — never blocks, never over-claims."""
    needs_review = [result.remaining_error] if result.remaining_error else []
    return CritiqueReport(
        overall="unassessed",
        summary="Semantic review unavailable; mechanical validation (compile, run, security) still holds.",
        assessments=[],
        needs_human_review=needs_review,
    )
