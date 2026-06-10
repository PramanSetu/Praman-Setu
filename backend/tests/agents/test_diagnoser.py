from __future__ import annotations

import asyncio

import pytest

from backend.agents.diagnoser import DiagnoserAgent, DiagnoserError
from backend.input_handler.models import DetectionMethod, LanguageDetection
from backend.orchestrator.state import ContextPackage, DiagnoserOutput, Hypothesis, ProcessedInput
from backend.tools.context_builder import ContextBuilder
from backend.tools.sandbox.executor import SandboxResult


class FakeLLMClient:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.calls: list[dict] = []

    async def complete(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeSandbox:
    def __init__(self, result: SandboxResult) -> None:
        self.result = result

    async def execute(self, language: str, code: str, cmd=None, timeout=None) -> SandboxResult:
        return self.result


def _context(
    *,
    error_type: str = "ZeroDivisionError",
    error_message: str = "division by zero",
    error_line: int = 2,
    error_node: str = "def divide(a, b):\n    return a / b",
    function_signature: str = "def divide(a, b):",
) -> ContextPackage:
    return ContextPackage(
        error_node=error_node,
        function_signature=function_signature,
        imports=["import pytest"],
        runtime_trace={
            "error_type": error_type,
            "error_message": error_message,
            "error_line": error_line,
            "raw_stderr": (
                f'Traceback (most recent call last):\n  File "main.py", line {error_line}\n'
                f"{error_type}: {error_message}"
            ),
        },
        language="python",
    )


def _output(
    *,
    generated_test: str = (
        "import pytest\n\n"
        "def test_divide_by_zero_reproduces_runtime_error():\n"
        '    """Reproduces the division by zero runtime failure."""\n'
        "    with pytest.raises(ZeroDivisionError):\n"
        "        divide(1, 0)\n"
    ),
    h1: float = 0.85,
    h2: float = 0.4,
    h3: float = 0.15,
    h1_theory: str = "The denominator can be zero and is used directly in division.",
) -> DiagnoserOutput:
    return DiagnoserOutput(
        root_cause="The function divides by an unchecked zero denominator.",
        hypotheses=[
            Hypothesis(
                id="H1",
                theory=h1_theory,
                confidence=h1,
                fix_direction="Validate the denominator before dividing.",
            ),
            Hypothesis(
                id="H2",
                theory="The caller may be passing invalid user input into the function.",
                confidence=h2,
                fix_direction="Sanitize caller input before invoking the function.",
            ),
            Hypothesis(
                id="H3",
                theory="A default value may unexpectedly resolve to zero.",
                confidence=h3,
                fix_direction="Audit defaults and handle zero as a special case.",
            ),
        ],
        generated_test=generated_test,
    )


def _processed_input(code: str, stderr: str) -> ProcessedInput:
    return ProcessedInput(
        language="python",
        detection=LanguageDetection(
            language="python",
            confidence=0.99,
            method=DetectionMethod.EXTENSION,
            reason="test fixture",
        ),
        filename="main.py",
        code=code,
        line_count=len(code.splitlines()),
        supplied_error_message=True,
        error_message="ZeroDivisionError: division by zero",
        error_type="ZeroDivisionError",
        error_line=2,
        raw_stderr=stderr,
        fast_path_eligible=False,
        execution=None,
        status="ready",
    )


def test_zero_division_error_returns_ranked_hypotheses_and_pytest() -> None:
    llm = FakeLLMClient([_output()])
    result = asyncio.run(DiagnoserAgent(llm).diagnose(_context()))

    assert len(result.hypotheses) == 3
    assert result.hypotheses[0].confidence >= result.hypotheses[1].confidence
    assert result.hypotheses[1].confidence >= result.hypotheses[2].confidence
    assert "pytest.raises(ZeroDivisionError)" in result.generated_test


def test_index_error_generates_index_reproduction_test() -> None:
    generated_test = (
        "import pytest\n\n"
        "def test_list_index_reproduces_index_error():\n"
        '    """Reproduces list access past the end of the list."""\n'
        "    items = []\n"
        "    with pytest.raises(IndexError):\n"
        "        items[0]\n"
    )
    result = asyncio.run(
        DiagnoserAgent(FakeLLMClient([_output(generated_test=generated_test)])).diagnose(
            _context(
                error_type="IndexError",
                error_message="list index out of range",
                error_node="def first(items):\n    return items[0]",
                function_signature="def first(items):",
            )
        )
    )

    assert "items[0]" in result.generated_test
    assert "pytest.raises(IndexError)" in result.generated_test


def test_name_error_h1_relates_to_undefined_variable() -> None:
    result = asyncio.run(
        DiagnoserAgent(
            FakeLLMClient(
                [
                    _output(
                        h1_theory="The code references an undefined variable named total.",
                        generated_test=(
                            "import pytest\n\n"
                            "def test_undefined_total_reproduces_name_error():\n"
                            '    """Reproduces the undefined variable lookup."""\n'
                            "    with pytest.raises(NameError):\n"
                            "        calculate()\n"
                        ),
                    )
                ]
            )
        ).diagnose(
            _context(
                error_type="NameError",
                error_message="name 'total' is not defined",
                error_node="def calculate():\n    return total + 1",
                function_signature="def calculate():",
            )
        )
    )

    assert "undefined variable" in result.hypotheses[0].theory


def test_invalid_llm_response_retries_once_then_raises() -> None:
    llm = FakeLLMClient([ValueError("malformed JSON"), ValueError("still malformed")])

    with pytest.raises(DiagnoserError):
        asyncio.run(DiagnoserAgent(llm).diagnose(_context()))

    assert len(llm.calls) == 2


def test_semantically_invalid_output_retries_once() -> None:
    invalid = _output().model_dump()
    invalid["generated_test"] = ""
    valid = _output()
    llm = FakeLLMClient([invalid, valid])

    result = asyncio.run(DiagnoserAgent(llm).diagnose(_context()))

    assert len(llm.calls) == 2
    assert "def test_" in result.generated_test


def test_confidence_ordering_is_sorted_and_ids_are_normalized() -> None:
    result = asyncio.run(
        DiagnoserAgent(FakeLLMClient([_output(h1=0.2, h2=0.9, h3=0.5)])).diagnose(_context())
    )

    assert [hypothesis.id for hypothesis in result.hypotheses] == ["H1", "H2", "H3"]
    assert [hypothesis.confidence for hypothesis in result.hypotheses] == [0.9, 0.5, 0.2]


def test_integration_with_real_context_builder_structurally_valid() -> None:
    code = "def divide(a, b):\n    return a / b\n\ndivide(1, 0)"
    stderr = (
        'Traceback (most recent call last):\n  File "main.py", line 4, in <module>\n'
        '  File "main.py", line 2, in divide\n    return a / b\n'
        "ZeroDivisionError: division by zero"
    )
    context = asyncio.run(
        ContextBuilder(
            sandbox=FakeSandbox(
                SandboxResult(
                    exit_code=1,
                    stdout="",
                    stderr=stderr,
                    timed_out=False,
                    duration_s=0.01,
                )
            )
        ).build(_processed_input(code, stderr))
    )

    result = asyncio.run(DiagnoserAgent(FakeLLMClient([_output()])).diagnose(context))

    assert isinstance(context, ContextPackage)
    assert len(result.hypotheses) == 3
    assert result.generated_test.strip()
