"""Prompt rendering for the Praman Setu Patcher agent."""
from __future__ import annotations

import json

from pydantic import BaseModel, Field

from backend.orchestrator.state import ContextPackage, DiagnoserOutput


class LLMPatchResponse(BaseModel):
    patched_code: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    approach: str = Field(min_length=1)
    potential_side_effects: list[str] = Field(default_factory=list)
    new_imports_required: list[str] = Field(default_factory=list)
    blocked_reason: str | None = None


SYSTEM_PROMPT = """\
You are Praman Setu Patcher, an expert Python code repair assistant. You write minimal, correct patches. You never change function signatures. You always make tests pass.

RULES (never violate):
1. Change MINIMUM lines necessary -- if you need more than 15 lines, explain why
2. Do NOT change the function signature (def line)
3. Do NOT add new imports unless strictly required
4. THE TEST IS THE GROUND TRUTH. Your patch MUST make the provided test pass EXACTLY AS WRITTEN.
   Before writing a single line of code, read the test assertion and determine what your function
   must return or raise for the tested input. Your implementation must produce that exact value.
   Examples:
     test asserts: result is None          → function MUST return None (not 0, not nan, not False)
     test asserts: result == 0             → function MUST return 0 (not None, not 0.0 unless int)
     test asserts: math.isnan(result)      → function MUST return float('nan')
     test asserts: pytest.raises(ValueError) → function MUST raise ValueError (not TypeError)
   If fix_direction and the test disagree, the TEST WINS — always.
5. Match the existing code style and indentation
6. Inside patched_code, output ONLY the complete patched target block selected by the system. No diff syntax. No markdown. No preamble.
7. Do NOT wrap patched_code in ```python code blocks.
8. Do NOT hide bugs with broad exception swallowing such as except Exception: pass.
9. If the fix cannot be made safely in the provided code block, set blocked_reason and keep patched_code as the original code.\
"""


def render_patcher_prompt(
    context: ContextPackage,
    diagnosis: DiagnoserOutput,
    *,
    retry: bool = False,
) -> list[dict[str, str]]:
    """Build a test-driven repair prompt that asks for patched code, not a diff."""
    h1 = diagnosis.hypotheses[0]
    schema = json.dumps(LLMPatchResponse.model_json_schema(), indent=2)
    imports = "\n".join(context.imports) if context.imports else "<none>"
    error_location = context.error_window_with_lines or context.error_node
    optional_context = _optional_context_sections(context)

    retry_instruction = ""
    if retry:
        retry_instruction = (
            "\nYour previous patched_code was invalid Python. Return syntactically valid "
            "Python only in patched_code, preserving the exact function signature.\n"
        )

    # Extract what the test asserts so we can surface it prominently above fix_direction.
    test_contract_note = _extract_test_contract_note(diagnosis.generated_test)

    user_prompt = f"""STEP 1 — READ THE TEST ASSERTION FIRST (this is your contract)
{diagnosis.generated_test}

{test_contract_note}

STEP 2 — HYPOTHESIS H1 (guidance, NOT override of the test)
theory: {h1.theory}
fix_direction: {h1.fix_direction}
  NOTE: fix_direction is advisory. If it contradicts the test assertion extracted in STEP 1,
  implement what the test requires. The test is the source of truth.
evidence: {h1.evidence}
risk_if_wrong: {h1.risk_if_wrong}

DIAGNOSIS CONTEXT
root_cause: {diagnosis.root_cause}
affected_scope: {diagnosis.affected_scope}
test_assertion_summary: {diagnosis.test_assertion_summary}

ERROR LOCATION
{error_location}

SELECTED PATCH TARGET
This may be the failing function, a same-file caller, a same-file callee, or the exact enclosing class. Return the complete replacement for this target only.
{context.error_node}

FUNCTION SIGNATURE -- DO NOT CHANGE
{context.function_signature}

AVAILABLE IMPORTS
{imports}

{optional_context}INTERNAL RESPONSE JSON SCHEMA
{schema}

CONSTRAINTS
{retry_instruction}
Respond ONLY with a valid JSON object matching the internal schema.
The patched_code field must contain the complete patched replacement for SELECTED PATCH TARGET, not a diff and not the full module.
Do not include markdown, preamble, explanation text, or ``` fences.
Preserve the original function signature exactly: {context.function_signature}
Minimize changed lines and preserve existing style.
Do not remove unrelated logic. Do not replace the function with a stub unless the original was already a stub.
If callers or callees reveal that a local-looking fix would break another path, choose the safer local behavior and list potential_side_effects.
"""

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def _extract_test_contract_note(generated_test: str) -> str:
    """Scan the generated test for common assertion patterns and surface them.

    Returns a short, explicit note like:
      "CONTRACT: For the tested inputs your function MUST return None."
    This is injected between the test code and fix_direction so the LLM sees
    it immediately after reading the assertion, before it reads fix_direction.
    """
    if not generated_test:
        return ""

    test_lower = generated_test.lower()

    # Order matters — more specific patterns first.
    if "math.isnan" in test_lower:
        return "CONTRACT: The test checks math.isnan(result). Your function MUST return float('nan') for the tested input."
    if "is none" in test_lower:
        return "CONTRACT: The test asserts `result is None`. Your function MUST return None (not 0, not nan, not False) for the tested input."
    if "is not none" in test_lower:
        return "CONTRACT: The test asserts `result is not None`. Your function MUST return a non-None value."
    if "pytest.raises" in test_lower:
        # Try to extract the exception name
        import re
        m = re.search(r"pytest\.raises\((\w+)", generated_test)
        exc = m.group(1) if m else "the specified exception"
        return f"CONTRACT: The test uses pytest.raises({exc}). Your function MUST raise {exc} for the tested input."
    if "== true" in test_lower or "is true" in test_lower:
        return "CONTRACT: The test asserts the result is True. Your function MUST return True for the tested input."
    if "== false" in test_lower or "is false" in test_lower:
        return "CONTRACT: The test asserts the result is False. Your function MUST return False for the tested input."
    if "== 0" in test_lower or "== 0.0" in test_lower:
        return "CONTRACT: The test asserts result == 0. Your function MUST return 0 (or 0.0) for the tested input."
    if "== []" in test_lower or "== list()" in test_lower:
        return "CONTRACT: The test asserts result == []. Your function MUST return an empty list for the tested input."
    if "==" in generated_test:
        return "CONTRACT: The test uses an equality assertion. Read the expected value on the right-hand side and ensure your function returns exactly that."

    return "CONTRACT: Read the test assertion carefully. Your patch must produce the exact value or exception that the assertion expects."


def _format_context_list(items: list[str]) -> str:
    if not items:
        return "<none>"
    return "\n\n".join(f"[{index}]\n{item}" for index, item in enumerate(items, start=1))


def _optional_context_sections(context: ContextPackage) -> str:
    """Only include caller/callee/class/constant blocks when they exist (token trim)."""
    sections: list[str] = []
    if context.enclosing_class:
        sections.append(f"ENCLOSING CLASS\n{context.enclosing_class}")
    if context.constants:
        sections.append("MODULE CONSTANTS\n" + "\n".join(context.constants))
    if context.callees:
        sections.append("SAME-FILE CALLEES FROM FAILING FUNCTION\n" + _format_context_list(context.callees))
    if context.callers:
        sections.append("SAME-FILE CALLERS OF FAILING FUNCTION\n" + _format_context_list(context.callers))
    return ("\n\n".join(sections) + "\n\n") if sections else ""
