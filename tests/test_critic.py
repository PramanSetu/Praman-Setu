from __future__ import annotations

from backend.agents.critic import CriticAgent, CritiqueReport, FixAssessment, LogicConcern
from backend.orchestrator.repair_v2 import RepairAttempt, RepairV2Result
from backend.tools.bug_ledger import BugLedger


def _result(status: str = "clean", *, remaining=None) -> RepairV2Result:
    return RepairV2Result(
        status=status,  # type: ignore[arg-type]
        passes=1,
        original_code="def f(x):\n    return 1 / x\n\nf(0)\n",
        final_code="def f(x):\n    try:\n        return 1 / x\n    except ZeroDivisionError:\n        return 0\n\nf(0)\n",
        ledger=BugLedger(code_compiles=True),
        attempts=[
            RepairAttempt(
                pass_number=1, summary="guard div", issues_found=["ZeroDivisionError"],
                applied_edits=1, edit_failures=[], validation_errors=[], confidence=0.9,
            )
        ],
        remaining_error=remaining,
    )


class _FakeLLM:
    def __init__(self, out: CritiqueReport | None = None, raises: bool = False) -> None:
        self._out = out
        self._raises = raises

    async def complete(self, *args, **kwargs):
        if self._raises:
            raise RuntimeError("llm down")
        return self._out


async def test_critic_returns_structured_review() -> None:
    out = CritiqueReport(
        overall="acceptable",
        summary="Guard is reasonable but the zero case is a guess.",
        assessments=[
            FixAssessment(
                target="f", addresses_root_cause=True, preserves_intent=True,
                confidence="low", concern="Returning 0 on divide-by-zero is an assumed behaviour.",
            )
        ],
        needs_human_review=["Confirm 0 is the desired result when x == 0."],
    )
    critic = CriticAgent(_FakeLLM(out))  # type: ignore[arg-type]

    report = await critic.review(_result())

    assert report.overall == "acceptable"
    assert report.assessments[0].confidence == "low"
    assert "Confirm 0" in report.needs_human_review[0]


async def test_critic_surfaces_latent_logic_audit() -> None:
    out = CritiqueReport(
        overall="risky",
        summary="Runs clean but a formula is wrong.",
        assessments=[],
        logic_audit=[
            LogicConcern(
                location="apply_interest",
                issue="balance * rate multiplies by the rate instead of applying a percentage.",
                severity="high",
            )
        ],
        needs_human_review=["apply_interest formula likely wrong"],
    )
    critic = CriticAgent(_FakeLLM(out))  # type: ignore[arg-type]

    report = await critic.review(_result())

    assert report.overall == "risky"
    assert report.logic_audit[0].severity == "high"
    assert "apply_interest" in report.logic_audit[0].location


async def test_critic_falls_back_when_llm_fails() -> None:
    critic = CriticAgent(_FakeLLM(raises=True))  # type: ignore[arg-type]

    report = await critic.review(_result(remaining="KeyError remains"))

    # Never raises; returns an honest "unassessed" report that doesn't over-claim.
    assert isinstance(report, CritiqueReport)
    assert report.overall == "unassessed"
    assert "KeyError remains" in report.needs_human_review


async def test_critic_fallback_has_no_review_items_when_nothing_remains() -> None:
    critic = CriticAgent(_FakeLLM(raises=True))  # type: ignore[arg-type]

    report = await critic.review(_result())

    assert report.overall == "unassessed"
    assert report.needs_human_review == []
