"""Reflector Agent — strategic retry decision on validation failure (Agent 5)."""
from __future__ import annotations

import json
import re

from pydantic import ValidationError

from backend.llm.client import LLMCompleter
from backend.llm.models import model_for
from backend.orchestrator.state import PipelineState, ReflectorDecision

SYSTEM_PROMPT = """\
You are Praman Setu Reflector, a strategic recovery agent.
When a patch fails validation, decide whether to refine the current approach or escalate to a new hypothesis.
You must return only a valid JSON object matching the ReflectorDecision schema.
- If the current hypothesis can be salvaged by addressing the specific failure, prefer 'refine_current'.
- If H2 has not been tried yet, prefer 'escalate_h2'.
- If H2 was already tried, prefer 'escalate_h3'.
- If all hypotheses are exhausted, 'give_up'.

IMPORTANT — Gate 4 (pytest) failures:
When Gate 4 fails, the Patcher produced a patch that does not satisfy the generated test's assertion.
In constraint_for_next_attempt you MUST include:
1. The exact assertion that failed (copy it from the Gate 4 output).
2. An explicit instruction to the Patcher: "Your function MUST return X for input Y" where X is the
   expected value read directly from the assertion.
This prevents the Patcher from re-producing the same wrong return value on retry.\
"""

_GROQ_MODEL = model_for("reflector").primary
_OLLAMA_FALLBACK = model_for("reflector").fallback


class ReflectorError(Exception):
    pass


class ReflectorAgent:
    def __init__(self, llm_client: LLMCompleter):
        self.llm = llm_client

    async def reflect(self, state: PipelineState) -> ReflectorDecision:
        schema = json.dumps(ReflectorDecision.model_json_schema(), indent=2)

        error_msg = ""
        if state.validator_report and state.validator_report.detailed_failures:
            error_msg = "\n".join(state.validator_report.detailed_failures)

        # Extract Gate 4-specific precision context to help the Patcher on retry.
        gate4_constraint = _build_gate4_constraint(state)

        available = [h.id for h in state.diagnoser_output.hypotheses] if state.diagnoser_output else []
        patch_history = [
            {
                "hypothesis_used": patch.hypothesis_used,
                "approach": patch.approach,
                "lines_changed": patch.lines_changed,
                "blocked_reason": patch.blocked_reason,
            }
            for patch in state.patch_history
        ]
        validation_history = [
            {
                "overall_passed": report.overall_passed,
                "summary": report.summary,
                "failures": report.detailed_failures,
            }
            for report in state.validation_history
        ]

        user_prompt = f"""VALIDATION FAILED
{error_msg}

CURRENT HYPOTHESIS USED: {state.hypothesis_used}
RETRY COUNT: {state.retry_count} (first failure = 0, second = 1)

AVAILABLE HYPOTHESES: {available}
ALREADY FAILED HYPOTHESES: {state.failed_hypotheses}

PATCH HISTORY:
{json.dumps(patch_history, indent=2)}

VALIDATION HISTORY:
{json.dumps(validation_history, indent=2)}
{gate4_constraint}
Provide your strategy following the JSON schema:
{schema}
"""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        response = await self.llm.complete(
            _GROQ_MODEL,
            messages,
            ReflectorDecision,
            temperature=0.0,
            max_tokens=400,
            timeout=15,
            fallback_model=_OLLAMA_FALLBACK,
        )

        if not isinstance(response, ReflectorDecision):
            try:
                response = ReflectorDecision.model_validate(response)
            except ValidationError as exc:
                raise ReflectorError(f"Invalid Reflector response: {exc}") from exc

        return response


# ---------------------------------------------------------------------------
# Gate 4 constraint extractor
# ---------------------------------------------------------------------------

def _build_gate4_constraint(state: PipelineState) -> str:
    """Build a precision constraint block when Gate 4 (pytest) failed.

    Scans the Gate 4 failure output for the assertion error line, extracts what
    the test expected vs what the patch returned, and injects a mandatory
    instruction for the Patcher's next attempt.

    Returns an empty string when Gate 4 passed or when no useful pattern is found.
    """
    report = state.validator_report
    if not report:
        return ""

    g4 = report.gate_results.get("gate_4")
    if not g4 or g4.passed:
        return ""

    gate4_text = g4.error or ""

    # --- Pattern 1: AssertionError with assert X is None / is not None
    m = re.search(r"AssertionError: assert (\S+) is (None|not None)", gate4_text)
    if m:
        actual = m.group(1)
        expected = m.group(2)
        return (
            f"\nGATE 4 PRECISION CONSTRAINT:\n"
            f"The test asserts `result is {expected}` but the patch returned `{actual}`.\n"
            f"For constraint_for_next_attempt include: "
            f"\"Your function MUST return {expected} (not {actual}) for the failing input case. "
            f"Read the test assertion: the test expects `is {expected}`.\"\n"
        )

    # --- Pattern 2: AssertionError with == comparison
    m = re.search(r"AssertionError: assert (\S+) == (\S+)", gate4_text)
    if m:
        actual, expected = m.group(1), m.group(2)
        return (
            f"\nGATE 4 PRECISION CONSTRAINT:\n"
            f"The test asserts `result == {expected}` but the patch returned `{actual}`.\n"
            f"For constraint_for_next_attempt include: "
            f"\"Your function MUST return {expected} (not {actual}) for the failing input case.\"\n"
        )

    # --- Pattern 3: Wrong exception type
    m = re.search(r"Failed: DID NOT RAISE.*?(\w+Error|\w+Exception)", gate4_text)
    if m:
        exc = m.group(1)
        return (
            f"\nGATE 4 PRECISION CONSTRAINT:\n"
            f"The test expected a {exc} to be raised but no exception was raised.\n"
            f"For constraint_for_next_attempt include: "
            f"\"Your function MUST raise {exc} for the tested input. "
            f"Do not return a value — raise the exception.\"\n"
        )

    # --- Pattern 4: Generic pytest failure — surface the raw assertion block
    assertion_block = _extract_assertion_block(gate4_text)
    if assertion_block:
        return (
            f"\nGATE 4 PRECISION CONSTRAINT:\n"
            f"The test failed with this assertion:\n{assertion_block}\n"
            f"For constraint_for_next_attempt explicitly state what return value your patch "
            f"must produce to satisfy this assertion.\n"
        )

    return ""


def _extract_assertion_block(gate4_text: str) -> str:
    """Extract the AssertionError section from pytest output (up to 5 lines)."""
    lines = gate4_text.splitlines()
    out: list[str] = []
    in_assert = False
    for line in lines:
        if "AssertionError" in line or line.strip().startswith("E   assert"):
            in_assert = True
        if in_assert:
            out.append(line)
            if len(out) >= 5:
                break
    return "\n".join(out).strip()
