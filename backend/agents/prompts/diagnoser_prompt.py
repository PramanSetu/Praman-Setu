"""Prompt rendering for the Praman Setu Diagnoser agent."""
from __future__ import annotations

import json

from backend.orchestrator.state import ContextPackage, DiagnoserOutput


SYSTEM_PROMPT = (
    "You are Praman Setu Diagnoser, an expert Python debugging assistant. "
    "Your job is to analyze buggy code context and produce a structured diagnosis "
    "with 3 ranked hypotheses and a failing test."
)


def render_diagnoser_prompt(
    context: ContextPackage,
    *,
    retry: bool = False,
) -> list[dict[str, str]]:
    """Build evidence-first messages for schema-forced diagnosis."""
    trace = context.runtime_trace
    schema = json.dumps(DiagnoserOutput.model_json_schema(), indent=2)
    imports = "\n".join(context.imports) if context.imports else "<none>"
    error_location = context.error_window_with_lines or context.error_node
    variables_block = _format_crash_variables(trace)
    optional_context = _optional_context_sections(context)

    retry_instruction = ""
    if retry:
        retry_instruction = (
            "\nYour previous response was invalid. Most commonly, generated_test was empty. "
            "The generated_test field MUST contain complete, non-empty pytest code with a "
            "def test_ function and a meaningful behavioral assertion. Respond ONLY with "
            "JSON that matches the schema exactly. Do not include markdown or explanatory text.\n"
        )

    user_prompt = f"""FUNCTION SIGNATURE
{context.function_signature}

ERROR LOCATION
{error_location}

ENCLOSING FUNCTION
{context.function_source or context.error_node}

AVAILABLE IMPORTS
{imports}

{optional_context}RUNTIME EVIDENCE
error_type: {trace.get("error_type")}
error_message: {trace.get("error_message")}
error_line: {trace.get("error_line")}
{variables_block}raw_stderr:
{trace.get("raw_stderr")}

DIAGNOSER OUTPUT JSON SCHEMA
{schema}

INSTRUCTIONS
{retry_instruction}
Respond ONLY with a valid JSON object matching this exact schema. No markdown, no preamble, no explanation outside the JSON.
Produce exactly 3 ranked hypotheses with ids H1, H2, and H3.
H2 must be a DIFFERENT theory than H1, not a reformulation. H3 must be the least likely but still plausible.
Confidence scores must be calibrated as follows: H1 between 0.6 and 0.95, H2 between 0.2 and 0.6, H3 between 0.05 and 0.3.
The root_cause must be one sentence.
Set affected_scope to the smallest accurate scope: local, caller, callee, class, module, or unknown.
Use the evidence fields to cite concrete lines, runtime values, callers, callees, or imports from the provided context.
The generated_test must be a NON-EMPTY string containing standalone pytest code, not inside a class.
The generated_test must include a function whose name starts with def test_.
The generated_test must reference the buggy function DIRECTLY by name — it is defined in the SAME file as the test, so do NOT import it (no `from user_code import ...`).
Do NOT write a test that merely expects the same crash shown in runtime evidence. A patch that only raises {trace.get("error_type")} again is not a real fix.
Use pytest.raises only when the code context clearly shows that raising a specific domain/validation exception is the correct contract. Otherwise assert the corrected non-crashing behavior that is most directly implied by callers, constants, function name, or existing code.
If the correct behavior cannot be inferred safely, set requires_clarification=true and put the exact question in clarification_question.
The generated_test must contain at least one assert or pytest.raises.
"""

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def _format_crash_variables(trace: dict) -> str:
    """Render observed variable values at the crash point, when the tracer ran.

    This is the execution tracer's payoff: real values, not speculation.
    """
    if not trace.get("captured_variables"):
        return ""
    crash_locals = trace.get("crash_locals") or {}
    if not crash_locals:
        return ""
    rendered = "\n".join(f"  {name} = {value}" for name, value in crash_locals.items())
    return f"observed_variables_at_crash:\n{rendered}\n"


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
