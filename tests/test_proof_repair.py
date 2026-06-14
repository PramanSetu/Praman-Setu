from __future__ import annotations

from backend.agents.critic import CritiqueReport, LogicConcern
from backend.agents.multi_issue_fixer import MultiIssueFixResponse
from backend.agents.property_tester import PropertyReport, ProvenIssue
from backend.input_handler.models import RawInput
from backend.orchestrator.proof_repair import refine_with_review
from backend.orchestrator.state import DetectionMethod, LanguageDetection, ProcessedInput
from backend.tools.bug_ledger import BugLedger
from backend.tools.bug_ledger import LedgerIssue
from backend.tools.patch_applier import UnitRewrite
from backend.tools.sandbox.executor import SandboxResult

BUGGY = "def highest(xs):\n    best = 0\n    for x in xs:\n        if x > best:\n            best = x\n    return best\n"
FIXED = "def highest(xs):\n    best = xs[0]\n    for x in xs:\n        if x > best:\n            best = x\n    return best\n"


def _ledger() -> BugLedger:
    return BugLedger(code_compiles=True)


def _processed(code: str, status: str = "execution_clean") -> ProcessedInput:
    return ProcessedInput(
        language="python",
        detection=LanguageDetection(language="python", confidence=1.0, method=DetectionMethod.EXTENSION, reason="t"),
        filename="app.py",
        code=code,
        line_count=len(code.splitlines()),
        supplied_error_message=False,
        error_message="",
        error_type=None,
        error_line=None,
        raw_stderr="",
        fast_path_eligible=False,
        execution=None,
        status=status,  # type: ignore[arg-type]
    )


class _Handler:
    async def handle(self, request: RawInput):
        return _processed(request.code)


class _BadHandler:
    async def handle(self, request: RawInput):
        return _processed(request.code, status="execution_failed")


async def _secure(code: str) -> list[str]:
    return []


class _Fixer:
    def __init__(self, new_source: str) -> None:
        self.new_source = new_source

    async def fix(self, code, ledger, *, validation_feedback=""):
        return MultiIssueFixResponse(
            summary="fix objective bug",
            issues_found=[],
            units=[UnitRewrite(target="highest", new_source=self.new_source, reason="seed best from first element")],
            generated_tests="",
            confidence=0.9,
        )


class _ClassFixer:
    async def fix(self, code, ledger, *, validation_feedback=""):
        return MultiIssueFixResponse(
            summary="fix clone shared state",
            issues_found=[],
            units=[
                UnitRewrite(
                    target="ShoppingCart",
                    new_source=(
                        "class ShoppingCart:\n"
                        "    def __init__(self):\n"
                        "        self.items = []\n"
                        "        self.discounts = {}\n\n"
                        "    def clone(self):\n"
                        "        new_cart = ShoppingCart()\n"
                        "        new_cart.items = [dict(item) for item in self.items]\n"
                        "        new_cart.discounts = dict(self.discounts)\n"
                        "        return new_cart"
                    ),
                    reason="clone must not share mutable state with the original",
                )
            ],
            generated_tests="",
            confidence=0.9,
        )


# A property-test runner that fails while the bug (best = 0) is present.
async def _runner(code: str, tests: str) -> SandboxResult:
    if "best = 0" in code:
        out = "FAILED main.py::test_highest_member - AssertionError: assert 0 in [-1]"
        return SandboxResult(exit_code=1, stdout=out, stderr="", timed_out=False, duration_s=0.01)
    return SandboxResult(exit_code=0, stdout="1 passed", stderr="", timed_out=False, duration_s=0.01)


async def test_proof_driven_fix() -> None:
    report = PropertyReport(
        status="proven_bugs", summary="1 failed",
        proven_issues=[ProvenIssue(test="test_highest_member", detail="assert 0 in [-1]")],
        tests="def test_highest_member():\n    pass\n",
    )
    code, prop, _, _ = await refine_with_review(
        BUGGY, BUGGY, _ledger(),
        property_report=report, critique=None,
        fixer=_Fixer(FIXED.strip()), handler=_Handler(), security_scan=_secure, runner=_runner,
    )
    assert "best = xs[0]" in code
    assert prop is not None and prop.status == "all_passed"


async def test_critic_driven_fix() -> None:
    critique = CritiqueReport(
        overall="risky", summary="",
        logic_audit=[LogicConcern(location="highest", axis="init_value", issue="best=0 wrong for negatives", severity="high", needs_intent=False)],
    )

    class _CleanCritic:
        async def review(self, result):
            return CritiqueReport(overall="solid", summary="", logic_audit=[])

    code, _, crit, _ = await refine_with_review(
        BUGGY, BUGGY, _ledger(),
        property_report=PropertyReport(status="all_passed", summary="", tests=""),
        critique=critique,
        fixer=_Fixer(FIXED.strip()), critic=_CleanCritic(), handler=_Handler(), security_scan=_secure,
    )
    assert "best = xs[0]" in code
    assert crit is not None and crit.overall == "solid"


async def test_linter_driven_shared_alias_fix() -> None:
    buggy = (
        "class ShoppingCart:\n"
        "    def __init__(self):\n"
        "        self.items = []\n"
        "        self.discounts = {}\n\n"
        "    def clone(self):\n"
        "        new_cart = ShoppingCart()\n"
        "        new_cart.items = copy(self.items)\n"
        "        new_cart.discounts = self.discounts\n"
        "        return new_cart\n"
    )
    ledger = BugLedger(
        code_compiles=True,
        issues=[
            LedgerIssue(
                kind="shared_state_alias",
                line=8,
                symbol="items",
                message="clone shares mutable state",
                severity="warning",
            )
        ],
    )

    code, _, _, final_ledger = await refine_with_review(
        buggy, buggy, ledger,
        property_report=None, critique=None,
        fixer=_ClassFixer(), handler=_Handler(), security_scan=_secure,
    )

    assert "dict(item) for item in self.items" in code
    assert "new_cart.discounts = dict(self.discounts)" in code
    assert all(issue.kind != "shared_state_alias" for issue in final_ledger.issues)


async def test_best_guess_fixes_intent_item() -> None:
    # An intent-dependent concern now gets a best-guess fix applied (and stays
    # flagged for the user) — per the product choice to complete the code.
    critique = CritiqueReport(
        overall="acceptable", summary="",
        logic_audit=[LogicConcern(location="highest", axis="init_value", issue="seed best from first element?", severity="medium", needs_intent=True)],
    )

    class _CleanCritic:
        async def review(self, result):
            return CritiqueReport(overall="solid", summary="", logic_audit=[])

    code, _, _, _ = await refine_with_review(
        BUGGY, BUGGY, _ledger(),
        property_report=PropertyReport(status="all_passed", summary="", tests=""),
        critique=critique,
        fixer=_Fixer(FIXED.strip()), critic=_CleanCritic(), handler=_Handler(), security_scan=_secure,
    )
    assert "best = xs[0]" in code  # best-guess fix applied


async def test_noop_when_nothing_to_fix() -> None:
    # No objective and no intent concerns => the fixer is never called.
    code, _, _, _ = await refine_with_review(
        BUGGY, BUGGY, _ledger(),
        property_report=PropertyReport(status="all_passed", summary="", tests=""),
        critique=CritiqueReport(overall="solid", summary="", logic_audit=[]),
        fixer=_Fixer(FIXED), handler=_Handler(), security_scan=_secure,
    )
    assert code == BUGGY  # untouched


async def test_rejects_regression() -> None:
    report = PropertyReport(
        status="proven_bugs", summary="",
        proven_issues=[ProvenIssue(test="t", detail="assert 0 in [-1]")],
        tests="def t():\n    pass\n",
    )
    code, _, _, _ = await refine_with_review(
        BUGGY, BUGGY, _ledger(),
        property_report=report, critique=None,
        fixer=_Fixer(FIXED.strip()), handler=_BadHandler(), security_scan=_secure, runner=_runner,
    )
    assert code == BUGGY  # regression rejected — original kept
