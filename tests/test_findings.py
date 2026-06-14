from __future__ import annotations

from backend.agents.critic import CritiqueReport, LogicConcern
from backend.agents.findings import classify_findings, tier_counts
from backend.agents.property_tester import PropertyReport, ProvenIssue
from backend.orchestrator.repair_v2 import RepairV2Result
from backend.tools.bug_ledger import BugLedger, LedgerIssue


def _result(*issues: LedgerIssue) -> RepairV2Result:
    return RepairV2Result(
        status="clean",
        passes=1,
        original_code="x = 1\n",
        final_code="x = 1\n",
        ledger=BugLedger(code_compiles=True, issues=list(issues)),
        attempts=[],
    )


def test_property_counterexample_is_confirmed() -> None:
    prop = PropertyReport(
        status="proven_bugs",
        summary="1 failed",
        proven_issues=[ProvenIssue(test="test_find_max_member", detail="assert 0 in [-1]")],
    )
    findings = classify_findings(_result(), None, prop)
    assert len(findings) == 1
    assert findings[0].tier == "confirmed"
    assert findings[0].source == "property"
    assert "[-1]" in findings[0].detail


def test_linter_pattern_is_likely() -> None:
    issue = LedgerIssue(kind="mutable_default", line=3, symbol="items", message="shared default", severity="warning")
    findings = classify_findings(_result(issue), None, None)
    assert [f.tier for f in findings] == ["likely"]
    assert findings[0].source == "linter"
    assert "items" in findings[0].location


def test_shared_state_alias_pattern_is_likely() -> None:
    issue = LedgerIssue(
        kind="shared_state_alias",
        line=9,
        symbol="items",
        message="clone shares mutable state",
        severity="warning",
    )
    findings = classify_findings(_result(issue), None, None)
    assert [f.tier for f in findings] == ["likely"]
    assert findings[0].category == "shared_state_alias"


def test_info_ledger_issues_are_excluded() -> None:
    # top_level_execution is INFO context, not a finding.
    issue = LedgerIssue(kind="top_level_execution", line=5, message="ctx", severity="info")
    assert classify_findings(_result(issue), None, None) == []


def test_critic_high_is_likely_low_or_intent_is_potential() -> None:
    critique = CritiqueReport(
        overall="risky",
        summary="x",
        logic_audit=[
            LogicConcern(location="find_max", axis="init_value", issue="max=0 bug", severity="high", needs_intent=False),
            LogicConcern(location="grade", axis="boundary", issue="> vs >=", severity="medium", needs_intent=True),
            LogicConcern(location="tax", axis="invariant", issue="formula?", severity="high", needs_intent=True),
        ],
    )
    findings = classify_findings(_result(), critique, None)
    by_loc = {f.location: f.tier for f in findings}
    assert by_loc["find_max"] == "likely"      # high + not intent
    assert by_loc["grade"] == "potential"      # medium
    assert by_loc["tax"] == "potential"        # high but needs_intent => potential


def test_findings_sorted_by_tier_and_counts() -> None:
    prop = PropertyReport(status="proven_bugs", summary="", proven_issues=[ProvenIssue(test="t", detail="d")])
    issue = LedgerIssue(kind="ignored_return", line=2, message="dropped", severity="warning")
    critique = CritiqueReport(
        overall="risky",
        summary="",
        logic_audit=[LogicConcern(location="f", axis="boundary", issue="i", severity="medium", needs_intent=True)],
    )
    findings = classify_findings(_result(issue), critique, prop)
    tiers = [f.tier for f in findings]
    assert tiers == ["confirmed", "likely", "potential"]  # sorted by confidence
    assert tier_counts(findings) == {"confirmed": 1, "likely": 1, "potential": 1, "style": 0}
