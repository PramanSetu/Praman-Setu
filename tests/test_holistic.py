from __future__ import annotations

from backend.agents.holistic_fixer import FixedBug, HolisticFixerAgent, HolisticFixResponse
from backend.input_handler.models import RawInput
from backend.orchestrator.holistic import _dedupe, holistic_fix
from backend.orchestrator.state import (
    DetectionMethod,
    LanguageDetection,
    ProcessedInput,
)

BUGGY = "def f():\n    return undefned\n\nf()"
FIXED = "def f():\n    return 1\n\nf()"


class FakeLLM:
    def __init__(self, response: object) -> None:
        self.response = response

    async def complete(self, *args, **kwargs):
        return self.response


def _processed(code: str, status: str, error_type: str | None = None, line: int | None = None) -> ProcessedInput:
    return ProcessedInput(
        language="python",
        detection=LanguageDetection(language="python", confidence=1.0, method=DetectionMethod.EXTENSION, reason="t"),
        filename="m.py",
        code=code,
        line_count=len(code.splitlines()),
        supplied_error_message=False,
        error_message=error_type or "",
        error_type=error_type,
        error_line=line,
        raw_stderr="",
        fast_path_eligible=False,
        execution=None,
        status=status,  # type: ignore[arg-type]
    )


# --- agent ---


async def test_agent_returns_fix_and_bug_list() -> None:
    payload = HolisticFixResponse(fixed_code=FIXED, bugs_fixed=[FixedBug(line=2, bug_type="NameError", explanation="typo")])
    agent = HolisticFixerAgent(FakeLLM(payload))
    result = await agent.fix(BUGGY, "NameError", 2)
    assert result.fixed_code == FIXED
    assert result.bugs_fixed[0].bug_type == "NameError"


async def test_agent_accepts_dict_response() -> None:
    agent = HolisticFixerAgent(FakeLLM({"fixed_code": FIXED, "bugs_fixed": []}))
    result = await agent.fix(BUGGY)
    assert result.fixed_code == FIXED


# --- orchestrator ---


class _OneFixFixer:
    async def fix(self, code, latest_error, error_line):
        return HolisticFixResponse(fixed_code=FIXED, bugs_fixed=[FixedBug(line=2, bug_type="NameError", explanation="typo")])


async def _secure(code: str) -> list[str]:
    return []


async def test_holistic_fixes_then_verifies_clean() -> None:
    class Handler:
        async def handle(self, request: RawInput):
            status = "execution_clean" if request.code == FIXED else "execution_failed"
            return _processed(request.code, status, "NameError" if status == "execution_failed" else None, 2)

    result = await holistic_fix(BUGGY, "m.py", handler=Handler(), fixer=_OneFixFixer(), security_scan=_secure)
    assert result.status == "clean"
    assert result.passes == 1
    assert result.final_code == FIXED
    assert result.bugs_fixed[0].bug_type == "NameError"


async def test_holistic_flags_insecure_when_eval_remains() -> None:
    # Runs clean, but bandit keeps finding eval and the fixer can't remove it.
    EVAL_CODE = "x = eval(input())\n"

    class CleanHandler:
        async def handle(self, request: RawInput):
            return _processed(request.code, "execution_clean", None, None)

    class CantFixFixer:
        async def fix(self, code, latest_error, error_line):
            return HolisticFixResponse(fixed_code=code, bugs_fixed=[])  # no change

    async def finds_eval(code: str) -> list[str]:
        return ["B307 (MEDIUM) at line 1"] if "eval(" in code else []

    result = await holistic_fix(EVAL_CODE, "m.py", handler=CleanHandler(), fixer=CantFixFixer(), security_scan=finds_eval)
    assert result.status == "insecure"
    assert result.security_findings and "B307" in result.security_findings[0]


async def test_holistic_refixes_security_then_clean() -> None:
    EVAL_CODE = "x = eval(input())\n"
    SAFE_CODE = "x = int(input())\n"

    class CleanHandler:
        async def handle(self, request: RawInput):
            return _processed(request.code, "execution_clean", None, None)

    class RemovesEvalFixer:
        async def fix(self, code, latest_error, error_line):
            return HolisticFixResponse(fixed_code=SAFE_CODE, bugs_fixed=[FixedBug(line=1, bug_type="security", explanation="removed eval")])

    async def finds_eval(code: str) -> list[str]:
        return ["B307 (MEDIUM) at line 1"] if "eval(" in code else []

    result = await holistic_fix(EVAL_CODE, "m.py", handler=CleanHandler(), fixer=RemovesEvalFixer(), security_scan=finds_eval)
    assert result.status == "clean"
    assert result.final_code == SAFE_CODE


async def test_holistic_unresolved_when_still_crashing() -> None:
    class AlwaysCrashHandler:
        async def handle(self, request: RawInput):
            return _processed(request.code, "execution_failed", "KeyError", 5)

    class NewCodeFixer:
        # Returns a different-but-still-crashing file each pass.
        def __init__(self):
            self.n = 0

        async def fix(self, code, latest_error, error_line):
            self.n += 1
            return HolisticFixResponse(fixed_code=code + f"\n# pass {self.n}", bugs_fixed=[])

    result = await holistic_fix(BUGGY, "m.py", max_passes=2, handler=AlwaysCrashHandler(), fixer=NewCodeFixer())
    assert result.status == "unresolved"
    assert result.passes == 2
    assert result.remaining_error == "KeyError"


async def test_holistic_no_progress_when_fix_unchanged() -> None:
    class CrashHandler:
        async def handle(self, request: RawInput):
            return _processed(request.code, "execution_failed", "NameError", 2)

    class SameCodeFixer:
        async def fix(self, code, latest_error, error_line):
            return HolisticFixResponse(fixed_code=code, bugs_fixed=[])

    result = await holistic_fix(BUGGY, "m.py", handler=CrashHandler(), fixer=SameCodeFixer())
    assert result.status == "no_progress"


def test_dedupe_collapses_same_line_and_type() -> None:
    bugs = [FixedBug(line=2, bug_type="NameError", explanation="a"),
            FixedBug(line=2, bug_type="nameerror", explanation="b"),
            FixedBug(line=5, bug_type="KeyError", explanation="c")]
    assert len(_dedupe(bugs)) == 2
