"""Prompt rendering for the PatchMind Diagnoser agent."""
from __future__ import annotations

import json

from backend.orchestrator.state import ContextPackage, DiagnoserOutput


SYSTEM_PROMPT = (
    "You are PatchMind Diagnoser, an expert Python debugging assistant. "
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

    retry_instruction = ""
    if retry:
        retry_instruction = (
            "\nYour previous response was invalid. Most commonly, generated_test was empty. "
            "The generated_test field MUST contain complete, non-empty pytest code with a "
            "def test_ function and pytest.raises for the runtime error. Respond ONLY with "
            "JSON that matches the schema exactly. Do not include markdown or explanatory text.\n"
        )

    user_prompt = f"""FUNCTION SIGNATURE
{context.function_signature}

ERROR LOCATION
{context.error_node}

AVAILABLE IMPORTS
{imports}

RUNTIME EVIDENCE
error_type: {trace.get("error_type")}
error_message: {trace.get("error_message")}
error_line: {trace.get("error_line")}
raw_stderr:
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
The generated_test must be a NON-EMPTY string containing standalone pytest code, not inside a class.
The generated_test must include a function whose name starts with def test_.
The generated_test must import or reference the buggy function correctly, trigger the EXACT error from runtime evidence, use pytest.raises({trace.get("error_type")}) for exceptions, be runnable without modification, and include a docstring explaining what it tests.
"""

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
