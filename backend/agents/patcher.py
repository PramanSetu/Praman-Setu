"""Patcher Agent for the Praman Setu pipeline."""
from __future__ import annotations

import ast
import asyncio
import difflib
import logging
from typing import Any

from pydantic import ValidationError

from backend.agents.prompts.patcher_prompt import LLMPatchResponse, render_patcher_prompt
from backend.llm.client import LLMCompleter
from backend.llm.models import model_for
from backend.orchestrator.state import ContextPackage, DiagnoserOutput, PatcherOutput


LOGGER = logging.getLogger(__name__)
GROQ_PATCHER_MODEL = model_for("patcher").primary
OLLAMA_PATCHER_FALLBACK_MODEL = model_for("patcher").fallback


class PatcherError(Exception):
    pass


class PatcherAgent:
    def __init__(self, llm_client: LLMCompleter):
        self.llm = llm_client

    async def patch(self, context: ContextPackage, diagnosis: DiagnoserOutput) -> PatcherOutput:
        # Patch the full enclosing function. Prefer the Context Builder's exact
        # function source; fall back to extracting from the error window for unit
        # fixtures that don't populate function_source.
        target_source = (
            context.function_source
            or _extract_first_function_source(context.error_node)
            or context.error_node
        )
        patch_context = context.model_copy(update={"error_node": target_source})
        messages = render_patcher_prompt(patch_context, diagnosis)
        first_error: Exception
        try:
            response = await self._complete(messages)
            return self._build_output(patch_context, response)
        except PatcherError as exc:
            if "Signature changed" in str(exc):
                raise
            first_error = exc
        except (ValidationError, ValueError, TypeError) as exc:
            first_error = exc
        except TimeoutError as exc:
            raise PatcherError("LLM timeout after 15s") from exc
        except asyncio.TimeoutError as exc:
            raise PatcherError("LLM timeout after 15s") from exc

        retry_messages = render_patcher_prompt(patch_context, diagnosis, retry=True)
        try:
            response = await self._complete(retry_messages)
            return self._build_output(patch_context, response)
        except PatcherError as exc:
            raise PatcherError(f"Invalid patched_code after retry: {exc}") from exc
        except (ValidationError, ValueError, TypeError) as retry_error:
            raise PatcherError(
                f"Invalid LLM patch response after retry: {retry_error}; first error: {first_error}"
            ) from retry_error

    async def _complete(self, messages: list[dict[str, str]]) -> LLMPatchResponse:
        return await self.llm.complete(
            GROQ_PATCHER_MODEL,
            messages,
            LLMPatchResponse,
            temperature=0.1,
            max_tokens=800,
            timeout=15,
            fallback_model=OLLAMA_PATCHER_FALLBACK_MODEL,
            reasoning_effort="none",
            reasoning_format="hidden",
        )

    def _build_output(
        self,
        context: ContextPackage,
        response: LLMPatchResponse | dict[str, Any],
    ) -> PatcherOutput:
        if not isinstance(response, LLMPatchResponse):
            response = LLMPatchResponse.model_validate(response)

        patched_code = response.patched_code
        if not patched_code.strip():
            raise PatcherError("patched_code must not be empty")

        _validate_python_syntax(patched_code)
        _assert_signature_preserved(context.error_node, patched_code, context.function_signature)
        unified_diff = _compute_unified_diff(context.error_node, patched_code)

        changed_lines = _changed_line_count(unified_diff)
        if changed_lines > 15:
            LOGGER.warning("Patcher changed %s lines, exceeding Phase 1 minimality target", changed_lines)

        return PatcherOutput(
            unified_diff=unified_diff,
            confidence=response.confidence,
            approach=response.approach,
            patched_code=patched_code,
        )


def _validate_python_syntax(code: str) -> None:
    try:
        ast.parse(code)
    except SyntaxError as exc:
        raise PatcherError(f"Invalid Python syntax in patched_code: {exc.msg}") from exc


def _assert_signature_preserved(
    original_code: str,
    patched_code: str,
    expected_signature: str,
) -> None:
    original_signature = _extract_signature(original_code) or expected_signature.strip()
    patched_signature = _extract_signature(patched_code)
    if patched_signature is None:
        raise PatcherError("No function signature found in patched_code")
    if patched_signature != original_signature:
        raise PatcherError(
            f"Signature changed: expected {original_signature!r}, got {patched_signature!r}"
        )


def _extract_signature(code: str) -> str | None:
    try:
        module = ast.parse(code)
    except SyntaxError as exc:
        raise PatcherError(f"Invalid Python syntax while extracting signature: {exc.msg}") from exc

    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            lines = code.splitlines()
            start = node.lineno - 1
            end = node.body[0].lineno - 1 if node.body else node.lineno
            return "\n".join(lines[start:end]).strip()
    return None


def _extract_first_function_source(code: str) -> str | None:
    try:
        module = ast.parse(code)
    except SyntaxError:
        return None

    lines = code.splitlines()
    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end_lineno = getattr(node, "end_lineno", None)
            if end_lineno is None:
                return None
            return "\n".join(lines[node.lineno - 1 : end_lineno]).strip()
    return None


def _compute_unified_diff(original_code: str, patched_code: str) -> str:
    try:
        diff = difflib.unified_diff(
            original_code.splitlines(),
            patched_code.splitlines(),
            fromfile="original.py",
            tofile="patched.py",
            lineterm="",
        )
        return "\n".join(diff)
    except Exception as exc:
        raise PatcherError(f"Failed to compute unified diff: {exc}") from exc


def _changed_line_count(unified_diff: str) -> int:
    return sum(
        1
        for line in unified_diff.splitlines()
        if line[:1] in {"+", "-"} and not line.startswith(("+++", "---"))
    )
