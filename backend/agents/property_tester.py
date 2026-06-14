"""Property Tester — turns suspected logic bugs into PROVEN ones.

The Critic *reasons* about logic bugs; this agent *proves* them. It generates
pytest property tests for the repaired module, runs them in the sandbox, and
reports concrete counterexamples (the failing input/assertion).

Crucial design rule: the tests assert only **intent-independent** properties —
things that must hold regardless of the program's business rules, so a failure is
a genuine bug, not a guess about intent. Examples:
  * no crash on representative/edge inputs (empty, zero, negative, None, single);
  * structural invariants: a max/min/selection returns an element OF the input; a
    reverse applied twice is the original; a length is non-negative;
  * type invariants.
It must NOT assert business values it would have to guess (exact discount, grade
thresholds, interest amounts) — those belong to the Critic's needs_intent path.
"""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Literal

from pydantic import BaseModel, Field

from backend.llm.client import LLMCompleter
from backend.llm.models import model_for
from backend.tools.sandbox.executor import SandboxResult
from backend.tools.sandbox.pool import sandbox_pool
from backend.tools.test_module_constructor import build_test_module

_MODEL = model_for("property_tester").primary
_FALLBACK = model_for("property_tester").fallback

TestRunner = Callable[[str, str], Awaitable[SandboxResult]]


class ProvenIssue(BaseModel):
    test: str            # the property test that failed
    detail: str = ""     # the failing assertion / counterexample


class PropertyReport(BaseModel):
    status: Literal["proven_bugs", "all_passed", "no_tests", "unavailable"]
    summary: str
    proven_issues: list[ProvenIssue] = Field(default_factory=list)
    tests: str = ""   # the generated property-test source, so it can be re-run cheaply


class _GeneratedTests(BaseModel):
    tests: str = ""


_SYSTEM_PROMPT = """\
You write PROPERTY-BASED tests with **Hypothesis** for one Python module to expose
latent logic bugs. Hypothesis generates and shrinks the inputs — so you write the
PROPERTY and let it find the adversarial input (negatives, empty, zero, …). Do NOT
hand-pick example inputs; that is the whole point.

Assert ONLY intent-independent properties — things that must hold no matter the
program's business rules, so a failure is a real bug, not a guess:
  • structural invariants: a max/min/selection returns an element OF its input; a
    reversed string reversed twice equals the original; a flattened nested list
    contains no lists; a count/length is non-negative; output type is consistent;
  • mathematical identities that hold by definition (e.g. factorial(n) >= 1 for
    n >= 0; sum/round-trip relations);
  • no crash on any valid generated input.

Do NOT assert specific business values you would have to guess (exact discount,
grade thresholds, interest amount). If a function's correctness depends on intent,
skip it.

NEVER assert that a function equals an arithmetic formula of its inputs
(`apply_tax(p, r) == p - r`, `total(a, b) == a + b`). That just restates a guess
about what the math SHOULD be — it is intent, not an invariant, and a "failure"
only means your guessed formula differs from the code. A real invariant holds by
definition no matter the formula: membership (`max(xs) in xs`), sign/bounds
(`abs(x) >= 0`), idempotence/round-trips (`rev(rev(s)) == s`), type stability.
If the only thing you can say about a function is its arithmetic, skip it.

Format — use Hypothesis and pytest:
  from hypothesis import given, settings, strategies as st

  @settings(max_examples=50, deadline=None)
  @given(st.lists(st.integers(), min_size=1))
  def test_find_max_returns_member(xs):
      assert find_max(xs) in xs

Rules: the module's functions/classes are ALREADY defined in the test file — call
them directly, do NOT import them (only import hypothesis/pytest). ALWAYS use
@settings(deadline=None) to avoid flaky timing failures. Choose strategies that
include adversarial values (negatives, zero, empty where the function should still
behave). Keep tests deterministic; no network/file/thread/input. One property per
test, named test_<function>_<property>.

Return only JSON: {"tests": "<full pytest+Hypothesis source, or empty string>"}.
"""


class PropertyTesterAgent:
    def __init__(self, llm_client: LLMCompleter):
        self.llm = llm_client

    async def probe(self, code: str, test_runner: TestRunner | None = None) -> PropertyReport:
        try:
            return await self._probe(code, test_runner or _default_runner)
        except Exception:  # noqa: BLE001 — proving is best-effort; never block the response
            return PropertyReport(status="unavailable", summary="Property testing unavailable.")

    async def _probe(self, code: str, run_tests: TestRunner) -> PropertyReport:
        generated = await self._generate(code)
        if not generated.strip():
            return PropertyReport(status="no_tests", summary="No intent-independent properties to test.")

        result = await run_tests(code, generated)
        if result.timed_out:
            return PropertyReport(status="unavailable", summary="Property tests timed out.", tests=generated)

        proven = _parse_failures(result.stdout or result.stderr)
        if proven:
            return PropertyReport(
                status="proven_bugs",
                summary=f"{len(proven)} property test(s) failed — these are proven bugs with counterexamples.",
                proven_issues=proven,
                tests=generated,
            )
        return PropertyReport(status="all_passed", summary="All generated property tests passed.", tests=generated)

    async def _generate(self, code: str) -> str:
        numbered = "\n".join(f"{i:>4} | {line}" for i, line in enumerate(code.splitlines(), 1))
        schema = json.dumps(_GeneratedTests.model_json_schema(), indent=2)
        prompt = f"""Write intent-independent pytest property tests for this module.

CODE
{numbered}

RESPONSE JSON SCHEMA
{schema}

Return only JSON with a single "tests" string (the pytest source, or "" if there
is nothing you can test without guessing business intent)."""
        response = await self.llm.complete(
            _MODEL,
            [{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
            _GeneratedTests,
            temperature=0.1,
            max_tokens=2000,
            timeout=30,
            fallback_model=_FALLBACK,
            reasoning_effort="none",
            reasoning_format="hidden",
        )
        if not isinstance(response, _GeneratedTests):
            response = _GeneratedTests.model_validate(response)
        return response.tests


async def _default_runner(code: str, tests: str) -> SandboxResult:
    test_code = build_test_module(code, tests)
    return await sandbox_pool.execute(
        language="python",
        code=test_code,
        cmd=["pytest", "main.py", "-q", "-p", "no:cacheprovider", "--tb=line"],
        timeout=15,
    )


def _parse_failures(output: str) -> list[ProvenIssue]:
    """Parse pytest's short failure summary lines:
    ``FAILED main.py::test_find_max_member - AssertionError: assert 0 in [-5, -2]``"""
    out: list[ProvenIssue] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line.startswith("FAILED "):
            continue
        rest = line[len("FAILED "):]
        name, _, reason = rest.partition(" - ")
        test_name = name.split("::")[-1].strip()
        out.append(ProvenIssue(test=test_name, detail=reason.strip()[:300]))
    return out
