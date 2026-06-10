from __future__ import annotations

import asyncio

import pytest

from backend.agents.diagnoser import DiagnoserAgent
from backend.agents.patcher import (
    GROQ_PATCHER_MODEL,
    LLMPatchResponse,
    PatcherAgent,
    PatcherError,
)
from backend.input_handler.service import SmartInputHandler
from backend.input_handler.models import RawInput
from backend.orchestrator.state import (
    ContextPackage,
    DiagnoserOutput,
    Hypothesis,
    PatcherOutput,
)
from backend.tools.context_builder import ContextBuilder
from backend.tools.sandbox.executor import SandboxResult


class FakeLLMClient:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.calls: list[dict] = []

    async def complete(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeSandbox:
    def __init__(self, result: SandboxResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    async def execute(self, language: str, code: str, cmd=None, timeout=None) -> SandboxResult:
        self.calls.append((language, code))
        return self.result


def _context(
    *,
    error_node: str = "def divide(a, b):\n    return a / b",
    function_signature: str = "def divide(a, b):",
    error_type: str = "ZeroDivisionError",
    error_message: str = "division by zero",
) -> ContextPackage:
    return ContextPackage(
        error_node=error_node,
        function_signature=function_signature,
        imports=[],
        runtime_trace={
            "error_type": error_type,
            "error_message": error_message,
            "error_line": 2,
            "raw_stderr": f"{error_type}: {error_message}",
        },
        language="python",
    )


def _diagnosis(
    *,
    theory: str = "The denominator can be zero and is used directly in division.",
    fix_direction: str = "Guard against zero before dividing.",
    generated_test: str = (
        "import pytest\n\n"
        "def test_divide_by_zero_is_guarded():\n"
        '    """Zero denominator should raise the runtime error deliberately."""\n'
        "    with pytest.raises(ZeroDivisionError):\n"
        "        divide(1, 0)\n"
    ),
) -> DiagnoserOutput:
    return DiagnoserOutput(
        root_cause="The function divides by an unchecked zero denominator.",
        hypotheses=[
            Hypothesis(id="H1", theory=theory, confidence=0.9, fix_direction=fix_direction),
            Hypothesis(id="H2", theory="Caller passes invalid input.", confidence=0.4, fix_direction="Validate caller input."),
            Hypothesis(id="H3", theory="Defaults resolve to zero.", confidence=0.1, fix_direction="Audit defaults."),
        ],
        generated_test=generated_test,
    )


def _patch_response(patched_code: str, *, confidence: float = 0.8) -> LLMPatchResponse:
    return LLMPatchResponse(
        patched_code=patched_code,
        confidence=confidence,
        approach="Add the smallest guard needed before the failing operation.",
    )


def test_zero_division_error_fix_returns_guard_diff_and_confidence() -> None:
    patched = "def divide(a, b):\n    if b == 0:\n        raise ZeroDivisionError('division by zero')\n    return a / b"
    llm = FakeLLMClient([_patch_response(patched, confidence=0.82)])

    result = asyncio.run(PatcherAgent(llm).patch(_context(), _diagnosis()))

    assert isinstance(result, PatcherOutput)
    assert "+    if b == 0:" in result.unified_diff
    assert "+        raise ZeroDivisionError('division by zero')" in result.unified_diff
    assert result.confidence > 0.5
    assert llm.calls[0]["args"][0] == GROQ_PATCHER_MODEL
    assert GROQ_PATCHER_MODEL == "qwen/qwen3-32b"
    assert llm.calls[0]["kwargs"]["temperature"] == 0.1


def test_index_error_fix_adds_bounds_check() -> None:
    context = _context(
        error_node="def first(items):\n    return items[0]",
        function_signature="def first(items):",
        error_type="IndexError",
        error_message="list index out of range",
    )
    diagnosis = _diagnosis(
        theory="The function indexes an empty list without checking bounds.",
        fix_direction="Check the list has at least one item before accessing index 0.",
        generated_test=(
            "import pytest\n\n"
            "def test_empty_list_raises_index_error():\n"
            '    """Empty list access should raise IndexError."""\n'
            "    with pytest.raises(IndexError):\n"
            "        first([])\n"
        ),
    )
    patched = (
        "def first(items):\n"
        "    if not items:\n"
        "        raise IndexError('list index out of range')\n"
        "    return items[0]"
    )

    result = asyncio.run(PatcherAgent(FakeLLMClient([_patch_response(patched)])).patch(context, diagnosis))

    assert "+    if not items:" in result.unified_diff
    assert "IndexError('list index out of range')" in result.unified_diff


def test_signature_preservation_rejects_changed_signature() -> None:
    patched = "def divide(a, b, default=0):\n    return a / (b or default)"

    with pytest.raises(PatcherError, match="Signature changed"):
        asyncio.run(PatcherAgent(FakeLLMClient([_patch_response(patched)])).patch(_context(), _diagnosis()))


def test_syntax_validation_retries_once_then_raises() -> None:
    invalid_first = _patch_response("def divide(a, b):\n    if b == 0\n        return 0")
    invalid_second = _patch_response("def divide(a, b):\n    return a /")
    llm = FakeLLMClient([invalid_first, invalid_second])

    with pytest.raises(PatcherError, match="Invalid patched_code after retry"):
        asyncio.run(PatcherAgent(llm).patch(_context(), _diagnosis()))

    assert len(llm.calls) == 2


def test_diff_format_contains_unified_headers_and_hunk() -> None:
    patched = "def divide(a, b):\n    if b == 0:\n        raise ZeroDivisionError('division by zero')\n    return a / b"

    result = asyncio.run(PatcherAgent(FakeLLMClient([_patch_response(patched)])).patch(_context(), _diagnosis()))

    assert result.unified_diff.startswith("--- original.py\n+++ patched.py")
    assert "\n@@" in result.unified_diff


def test_integration_full_pipeline_input_to_patcher_with_mocked_llms() -> None:
    code = "def divide(a, b):\n    return a / b\n\ndivide(1, 0)"
    stderr = (
        'Traceback (most recent call last):\n  File "main.py", line 4, in <module>\n'
        '  File "main.py", line 2, in divide\n    return a / b\n'
        "ZeroDivisionError: division by zero"
    )
    sandbox = FakeSandbox(
        SandboxResult(exit_code=1, stdout="", stderr=stderr, timed_out=False, duration_s=0.01)
    )
    processed = asyncio.run(
        SmartInputHandler(sandbox=sandbox).handle(RawInput(code=code, filename="main.py"))
    )
    context = asyncio.run(ContextBuilder(sandbox=sandbox).build(processed))
    diagnosis = asyncio.run(
        DiagnoserAgent(FakeLLMClient([_diagnosis()])).diagnose(context)
    )
    patched = (
        "def divide(a, b):\n"
        "    if b == 0:\n"
        "        raise ZeroDivisionError('division by zero')\n"
        "    return a / b"
    )

    output = asyncio.run(PatcherAgent(FakeLLMClient([_patch_response(patched)])).patch(context, diagnosis))

    assert isinstance(output, PatcherOutput)
    assert output.unified_diff.startswith("--- original.py\n+++ patched.py")
    assert "+    if b == 0:" in output.unified_diff
