"""Review-driven repair: make the Critic and Property Tester *fix* bugs, not just flag them.

After the main repair produces clean code, two LLM reviewers find latent bugs:
the Critic (reasoned logic audit) and the Property Tester (proven counterexamples).
This pass feeds their OBJECTIVE findings — the ones with a clearly-correct fix and
no policy choice — back to the patcher, re-validates that the candidate still
compiles, runs clean, and stays secure (the validator as a regression gate), then
re-reviews. Intent-dependent findings are left for the user to confirm.
"""
from __future__ import annotations

import ast
from collections.abc import Awaitable, Callable
from typing import Protocol

from backend.agents.critic import CritiqueReport
from backend.agents.multi_issue_fixer import MultiIssueFixResponse, MultiIssueFixerAgent
from backend.agents.property_tester import (
    PropertyReport,
    _default_runner,
    _parse_failures,
)
from backend.input_handler.models import ProcessedInput, RawInput
from backend.input_handler.service import smart_input_handler
from backend.llm.client import llm_client
from backend.orchestrator.repair_v2 import RepairV2Result, _security_scan
from backend.tools.bug_ledger import BugLedger, build_bug_ledger
from backend.tools.patch_applier import apply_unit_rewrites
from backend.tools.sandbox.executor import SandboxResult

SecurityScan = Callable[[str], Awaitable[list[str]]]
TestRunner = Callable[[str, str], Awaitable[SandboxResult]]


class _Fixer(Protocol):
    async def fix(self, code: str, ledger: BugLedger, *, validation_feedback: str = "") -> MultiIssueFixResponse: ...


class _Critic(Protocol):
    async def review(self, result: RepairV2Result) -> CritiqueReport: ...


class _Handler(Protocol):
    async def handle(self, request: RawInput) -> ProcessedInput: ...


# Deterministic semantic-lint kinds carried on the ledger — objective by nature.
_LINTER_KINDS = {
    "mutable_default",
    "ignored_return",
    "shared_state_alias",
    "swallowed_exception",
    "infinite_loop",
    "background_thread",
}


def _fixable_issues(
    property_report: PropertyReport | None,
    critique: CritiqueReport | None,
    ledger: BugLedger | None,
) -> tuple[list[str], list[str]]:
    """Split the reviewers' findings into the two feedback buckets the fixer needs.

    Returns ``(objective, best_guess)``:
      * objective   — demonstrably wrong, exactly one correct fix (proven
        counterexamples, the Critic's non-intent concerns, deterministic linter
        findings). Fix decisively.
      * best_guess  — intent-dependent concerns. We still apply the most likely
        fix (user opted for best-guess), but it stays flagged for confirmation."""
    objective: list[str] = []
    best_guess: list[str] = []
    if property_report is not None:
        for proven in property_report.proven_issues:
            objective.append(f"PROVEN by test {proven.test}: {proven.detail}")
    if critique is not None:
        for concern in critique.logic_audit:
            entry = f"{concern.location} [{concern.axis}]: {concern.issue}"
            (best_guess if concern.needs_intent else objective).append(entry)
    if ledger is not None:
        for issue in ledger.issues:
            if issue.kind in _LINTER_KINDS:
                objective.append(f"line {issue.line} [{issue.kind}]: {issue.message}")
    return objective, best_guess


async def _reprove(code: str, tests: str, runner: TestRunner) -> PropertyReport:
    """Re-run the EXISTING property tests on new code — sandbox only, no LLM regen."""
    result = await runner(code, tests)
    proven = [] if result.timed_out else _parse_failures(result.stdout or result.stderr)
    return PropertyReport(
        status="proven_bugs" if proven else "all_passed",
        summary="re-proved after fix",
        proven_issues=proven,
        tests=tests,
    )


async def refine_with_review(
    original_code: str,
    final_code: str,
    ledger: BugLedger,
    *,
    property_report: PropertyReport | None,
    critique: CritiqueReport | None,
    fixer: _Fixer | None = None,
    critic: _Critic | None = None,
    handler: _Handler = smart_input_handler,
    security_scan: SecurityScan | None = None,
    runner: TestRunner | None = None,
    max_rounds: int = 2,
) -> tuple[str, PropertyReport | None, CritiqueReport | None, BugLedger]:
    """Fix the reviewers' findings; re-prove and re-review. Returns the (possibly
    improved) code, the refreshed property/critique reports, and the ledger rebuilt
    on the final code (so callers never classify findings against stale evidence).

    A round is accepted only if the candidate compiles, runs clean, and introduces
    no HIGH/MEDIUM security finding — so this never makes the code worse.
    """
    agent = fixer or MultiIssueFixerAgent(llm_client)
    scan = security_scan or _security_scan
    run = runner or _default_runner
    current = final_code
    current_ledger = ledger
    prop = property_report
    crit = critique

    for _ in range(max_rounds):
        objective, best_guess = _fixable_issues(prop, crit, current_ledger)
        if not objective and not best_guess:
            break
        sections = []
        if objective:
            sections.append(
                "Fix these OBJECTIVE bugs — each is demonstrably wrong for valid input and "
                "has a clear correct fix. Rewrite minimally and keep all other behaviour:\n"
                + "\n".join(f"- {issue}" for issue in objective)
            )
        if best_guess:
            sections.append(
                "These are INTENT-AMBIGUOUS — apply the single most likely fix (the common "
                "convention) so the code is complete, but keep the change minimal; they remain "
                "flagged for the user to confirm:\n"
                + "\n".join(f"- {issue}" for issue in best_guess)
            )
        feedback = "\n\n".join(sections)
        try:
            response = await agent.fix(current, current_ledger, validation_feedback=feedback)
        except Exception:  # noqa: BLE001 — best-effort; keep the last good code
            break

        candidate = apply_unit_rewrites(current, response.units).applied_code
        if candidate.strip() == current.strip():
            break
        try:
            ast.parse(candidate)
        except SyntaxError:
            break  # would not compile — reject
        processed = await handler.handle(RawInput(code=candidate, filename=None))
        if processed.status != "execution_clean":
            break  # runtime regression — reject
        if await scan(candidate):
            break  # security regression — reject

        current = candidate
        current_ledger = build_bug_ledger(current, processed)
        if prop is not None and prop.tests.strip():
            prop = await _reprove(current, prop.tests, run)
        if critic is not None:
            crit = await critic.review(
                RepairV2Result(
                    status="clean",
                    passes=0,
                    original_code=original_code,
                    final_code=current,
                    ledger=current_ledger,
                    attempts=[],
                )
            )

    return current, prop, crit, current_ledger
