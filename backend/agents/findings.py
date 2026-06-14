"""Unified, tiered classification of all review signals.

The pipeline produces findings at three confidence levels from three sources:
the Property Tester (proven counterexamples), the deterministic semantic linter
(static anti-patterns, carried on the ledger), and the Critic (reasoned logic
audit). This module merges them into one list classified into four tiers so the
UI can show *confidence*, not just a pile of findings:

  * confirmed — proven wrong (a failing counterexample)        [Property Tester]
  * likely    — definitive static pattern / high-confidence    [linter, Critic high]
  * potential — depends on intent or lower confidence          [Critic medium/low/intent]
  * style     — minor cleanups                                 [reserved]

No LLM calls — this is pure aggregation over signals already computed.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from backend.agents.critic import CritiqueReport
from backend.agents.property_tester import PropertyReport
from backend.orchestrator.repair_v2 import RepairV2Result

Tier = Literal["confirmed", "likely", "potential", "style"]

_TIER_ORDER = {"confirmed": 0, "likely": 1, "potential": 2, "style": 3}

# Deterministic semantic-lint kinds carried on the ledger (high-confidence static).
_LINTER_KINDS = {
    "mutable_default",
    "ignored_return",
    "shared_state_alias",
    "swallowed_exception",
    "infinite_loop",
    "background_thread",
}


class Finding(BaseModel):
    tier: Tier
    category: str            # e.g. "property", "mutable_default", "boundary"
    location: str            # function / line / test name
    detail: str              # the issue, or the failing counterexample
    source: Literal["property", "linter", "critic"]


def classify_findings(
    result: RepairV2Result,
    critique: CritiqueReport | None,
    property_report: PropertyReport | None,
) -> list[Finding]:
    findings: list[Finding] = []

    # Confirmed — proven by a failing property test (has a counterexample).
    if property_report is not None:
        for proven in property_report.proven_issues:
            findings.append(
                Finding(
                    tier="confirmed",
                    category="property",
                    location=proven.test,
                    detail=proven.detail or "property test failed",
                    source="property",
                )
            )

    # Likely — deterministic linter patterns on the final code (definitive, but
    # no per-input proof).
    for issue in result.ledger.issues:
        if issue.kind in _LINTER_KINDS:
            location = f"line {issue.line}"
            if issue.symbol:
                location += f" ({issue.symbol})"
            findings.append(
                Finding(
                    tier="likely",
                    category=issue.kind,
                    location=location,
                    detail=issue.message,
                    source="linter",
                )
            )

    # Likely / Potential — Critic's reasoned logic audit, de-noised so the same
    # bug isn't reported three times and low-confidence filler is dropped:
    #   * skip a concern already covered by a proven test or a linter pattern on
    #     the same function (property/linter evidence is stronger than reasoning);
    #   * drop low-severity speculative "how does it handle X?" questions — they
    #     add volume without signal. Keep medium/high, and all genuine intent Qs.
    covered = [_location_key(f.location) for f in findings]
    if critique is not None:
        for concern in critique.logic_audit:
            if concern.severity == "low" and concern.needs_intent:
                continue
            if _is_covered(_location_key(concern.location), covered):
                continue
            likely = concern.severity == "high" and not concern.needs_intent
            findings.append(
                Finding(
                    tier="likely" if likely else "potential",
                    category=concern.axis,
                    location=concern.location,
                    detail=concern.issue,
                    source="critic",
                )
            )

    findings.sort(key=lambda f: _TIER_ORDER[f.tier])
    return findings


def _location_key(location: str) -> str:
    """Normalise a finding location for comparison — lower-cased, without the
    parenthetical/bracketed suffix (``line 1 (log)`` -> ``line 1``)."""
    return location.strip().lower().split("(")[0].split("[")[0].strip()


def _is_covered(key: str, covered: list[str]) -> bool:
    """True if a stronger finding (proven test / linter) already names this place.
    Substring either way matches a Critic concern at ``highest`` against a proven
    test ``test_highest_returns_member`` without over-matching short common words."""
    if not key:
        return False
    return any(
        other and (key in other or other in key) and min(len(key), len(other)) >= 4
        for other in covered
    )


def tier_counts(findings: list[Finding]) -> dict[str, int]:
    counts = {tier: 0 for tier in _TIER_ORDER}
    for finding in findings:
        counts[finding.tier] += 1
    return counts
