"""Real pipeline smoke test for Input Handler -> Context Builder -> Diagnoser -> Patcher.

Requires:
- Docker running
- praman-setu-sandbox-python:latest built
- GROQ_API_KEY in .env
- Optional local Ollama running for fallback
"""
from __future__ import annotations

import asyncio

from backend.agents.diagnoser import DiagnoserAgent
from backend.agents.patcher import PatcherAgent
from backend.input_handler.models import RawInput
from backend.input_handler.service import SmartInputHandler
from backend.llm.client import LLMClient
from backend.tools.context_builder import ContextBuilder


BUGGY_CODE = """def divide(a, b):
    return a / b

divide(1, 0)
"""


async def main() -> None:
    llm = LLMClient()

    processed = await SmartInputHandler().handle(
        RawInput(code=BUGGY_CODE.strip(), filename="main.py")
    )
    print("[1] ProcessedInput")
    print(f"error_type={processed.error_type!r}")
    print(f"error_message={processed.error_message!r}")
    print(f"error_line={processed.error_line!r}")

    context = await ContextBuilder().build(processed)
    print("\n[2] ContextPackage")
    print(f"function_signature={context.function_signature!r}")
    print(f"runtime_error_type={context.runtime_trace.get('error_type')!r}")
    print(f"runtime_error_line={context.runtime_trace.get('error_line')!r}")

    diagnosis = await DiagnoserAgent(llm).diagnose(context)
    print("\n[3] DiagnoserOutput")
    print(f"root_cause={diagnosis.root_cause}")
    for hypothesis in diagnosis.hypotheses:
        print(f"{hypothesis.id}: confidence={hypothesis.confidence} theory={hypothesis.theory}")
    print(f"generated_test_has_pytest={('def test_' in diagnosis.generated_test)!r}")

    patch = await PatcherAgent(llm).patch(context, diagnosis)
    print("\n[4] PatcherOutput")
    print(f"confidence={patch.confidence}")
    print(f"approach={patch.approach}")
    print("\nUnified diff:")
    print(patch.unified_diff)


if __name__ == "__main__":
    asyncio.run(main())
