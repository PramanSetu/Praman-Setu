from __future__ import annotations

import pytest

from backend.agents.explainer import (
    ExplainerAgent,
    FixDetail,
    RepairExplanation,
    _ExplainerLLMOut,
)
from backend.orchestrator.repair_v2 import RepairAttempt, RepairV2Result
from backend.tools.bug_ledger import BugLedger


def _result(status: str, *, issues=None, remaining=None) -> RepairV2Result:
    attempts = [
        RepairAttempt(
            pass_number=1,
            summary="fixed stuff",
            issues_found=issues or [],
            applied_edits=1,
            edit_failures=[],
            validation_errors=[],
            confidence=0.9,
        )
    ]
    return RepairV2Result(
        status=status,  # type: ignore[arg-type]
        passes=1,
        original_code="def f():\n    return missing\n",
        final_code="def f():\n    return 1\n",
        ledger=BugLedger(code_compiles=True),
        attempts=attempts,
        remaining_error=remaining,
    )


class _FakeLLM:
    def __init__(self, out: _ExplainerLLMOut | None = None, raises: bool = False) -> None:
        self._out = out
        self._raises = raises

    async def complete(self, *args, **kwargs):
        if self._raises:
            raise RuntimeError("llm down")
        return self._out


async def test_explainer_uses_deterministic_verification_for_clean() -> None:
    out = _ExplainerLLMOut(
        headline="Fixed the undefined name.",
        fixes=[FixDetail(issue="`missing` was undefined", fix="returns 1", category="NameError")],
        flagged=[],
    )
    agent = ExplainerAgent(_FakeLLM(out))  # type: ignore[arg-type]

    exp = await agent.explain(_result("clean"))

    assert isinstance(exp, RepairExplanation)
    assert exp.status == "clean"
    assert exp.headline == "Fixed the undefined name."
    assert exp.fixes[0].category == "NameError"
    # Verification is derived from status, NOT from the LLM.
    assert "compiles" in exp.verification and "security scan" in exp.verification


async def test_explainer_carries_flagged_items() -> None:
    out = _ExplainerLLMOut(headline="Partial.", fixes=[], flagged=["age==0 behaviour was guessed"])
    agent = ExplainerAgent(_FakeLLM(out))  # type: ignore[arg-type]

    exp = await agent.explain(_result("unresolved", remaining="KeyError remains"))

    assert exp.flagged == ["age==0 behaviour was guessed"]
    assert "could not be fixed automatically" in exp.verification


async def test_explainer_falls_back_when_llm_fails() -> None:
    agent = ExplainerAgent(_FakeLLM(raises=True))  # type: ignore[arg-type]

    exp = await agent.explain(
        _result("clean", issues=["undefined name 'missing'"]),
    )

    # Deterministic fallback: still returns a usable explanation, never raises.
    assert isinstance(exp, RepairExplanation)
    assert exp.status == "clean"
    assert any("missing" in f.issue for f in exp.fixes)
    assert "compiles" in exp.verification


async def test_explainer_fallback_surfaces_remaining_error_as_flagged() -> None:
    agent = ExplainerAgent(_FakeLLM(raises=True))  # type: ignore[arg-type]

    exp = await agent.explain(_result("unresolved", remaining="ZeroDivisionError at line 9"))

    assert "ZeroDivisionError at line 9" in exp.flagged


@pytest.mark.parametrize("status", ["clean", "unresolved", "insecure", "no_progress"])
async def test_explainer_has_verification_for_every_status(status: str) -> None:
    agent = ExplainerAgent(_FakeLLM(raises=True))  # type: ignore[arg-type]
    exp = await agent.explain(_result(status))
    assert exp.verification  # non-empty for every terminal status
