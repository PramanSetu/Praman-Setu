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


SYSTEM_PROMPT = """You are Praman Setu Patcher, an expert Python code repair assistant. You write minimal, correct patches. You never change function signatures. You always make tests pass.

RULES (never violate):
1. Change MINIMUM lines necessary -- if you need more than 15 lines, explain why
2. Do NOT change the function signature (def line)
3. Do NOT add new imports unless strictly required
4. Your patch MUST make the provided test pass
5. Match the existing code style and indentation
6. Inside patched_code, output ONLY the complete patched target block selected by the system. No diff syntax. No markdown. No preamble.
7. Do NOT wrap patched_code in ```python code blocks.
8. Do NOT hide bugs with broad exception swallowing such as except Exception: pass.
9. If the fix cannot be made safely in the provided code block, set blocked_reason and keep patched_code as the original code."""


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
    constants = "\n".join(context.constants) if context.constants else "<none>"
    enclosing_class = context.enclosing_class or "<none>"
    callers = _format_context_list(context.callers)
    callees = _format_context_list(context.callees)
    error_location = context.error_window_with_lines or context.error_node

    retry_instruction = ""
    if retry:
        retry_instruction = (
            "\nYour previous patched_code was invalid Python. Return syntactically valid "
            "Python only in patched_code, preserving the exact function signature.\n"
        )

    user_prompt = f"""HYPOTHESIS H1
theory: {h1.theory}
fix_direction: {h1.fix_direction}
evidence: {h1.evidence}
risk_if_wrong: {h1.risk_if_wrong}

DIAGNOSIS CONTEXT
root_cause: {diagnosis.root_cause}
affected_scope: {diagnosis.affected_scope}
test_assertion_summary: {diagnosis.test_assertion_summary}

GENERATED TEST -- MUST PASS
The following test currently fails. Your patched code must make it pass.
{diagnosis.generated_test}

ERROR LOCATION
{error_location}

SELECTED PATCH TARGET
This may be the failing function, a same-file caller, a same-file callee, or the exact enclosing class. Return the complete replacement for this target only.
{context.error_node}

FUNCTION SIGNATURE -- DO NOT CHANGE
{context.function_signature}

ENCLOSING CLASS
{enclosing_class}

AVAILABLE IMPORTS
{imports}

MODULE CONSTANTS
{constants}

SAME-FILE CALLEES FROM FAILING FUNCTION
{callees}

SAME-FILE CALLERS OF FAILING FUNCTION
{callers}

INTERNAL RESPONSE JSON SCHEMA
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


def _format_context_list(items: list[str]) -> str:
    if not items:
        return "<none>"
    return "\n\n".join(f"[{index}]\n{item}" for index, item in enumerate(items, start=1))
