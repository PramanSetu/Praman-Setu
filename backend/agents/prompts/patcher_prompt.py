"""Prompt rendering for the PatchMind Patcher agent."""
from __future__ import annotations

import json

from pydantic import BaseModel, Field

from backend.orchestrator.state import ContextPackage, DiagnoserOutput


class LLMPatchResponse(BaseModel):
    patched_code: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    approach: str = Field(min_length=1)


SYSTEM_PROMPT = """You are PatchMind Patcher, an expert Python code repair assistant. You write minimal, correct patches. You never change function signatures. You always make tests pass.

RULES (never violate):
1. Change MINIMUM lines necessary -- if you need more than 15 lines, explain why
2. Do NOT change the function signature (def line)
3. Do NOT add new imports unless strictly required
4. Your patch MUST make the provided test pass
5. Match the existing code style and indentation
6. Inside patched_code, output ONLY the complete patched code block. No diff syntax. No markdown. No preamble.
7. Do NOT wrap patched_code in ```python code blocks."""


def render_patcher_prompt(
    context: ContextPackage,
    diagnosis: DiagnoserOutput,
    *,
    retry: bool = False,
) -> list[dict[str, str]]:
    """Build a test-driven repair prompt that asks for patched code, not a diff."""
    h1 = diagnosis.hypotheses[0]
    schema = json.dumps(LLMPatchResponse.model_json_schema(), indent=2)

    retry_instruction = ""
    if retry:
        retry_instruction = (
            "\nYour previous patched_code was invalid Python. Return syntactically valid "
            "Python only in patched_code, preserving the exact function signature.\n"
        )

    user_prompt = f"""HYPOTHESIS H1
theory: {h1.theory}
fix_direction: {h1.fix_direction}

GENERATED TEST -- MUST PASS
The following test currently fails. Your patched code must make it pass.
{diagnosis.generated_test}

BUGGY CODE TO FIX
{context.error_node}

FUNCTION SIGNATURE -- DO NOT CHANGE
{context.function_signature}

INTERNAL RESPONSE JSON SCHEMA
{schema}

CONSTRAINTS
{retry_instruction}
Respond ONLY with a valid JSON object matching the internal schema.
The patched_code field must contain the complete patched code block, not a diff.
Do not include markdown, preamble, explanation text, or ``` fences.
Preserve the original function signature exactly: {context.function_signature}
Minimize changed lines and preserve existing style.
"""

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
