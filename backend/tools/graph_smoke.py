"""Live end-to-end smoke test of the full LangGraph pipeline.

Runs Input -> Context -> Diagnoser -> Patcher -> Validator (-> Reflector)* against
the real Groq API and the real hardened Docker sandbox.

Requires:
- Docker running, praman-setu-sandbox-python:latest built
- GROQ_API_KEY in .env

Run:  uv run python -m backend.tools.graph_smoke
"""
from __future__ import annotations

import asyncio

from backend.input_handler.models import RawInput
from backend.input_handler.service import SmartInputHandler
from backend.orchestrator.graph import build_graph
from backend.orchestrator.state import PipelineState

BUGGY_CODE = """def divide(a, b):
    return a / b

print(divide(10, 0))
"""


async def main() -> None:
    processed = await SmartInputHandler().handle(RawInput(code=BUGGY_CODE.strip(), filename="main.py"))
    print(f"[input]   status={processed.status} error={processed.error_type} line={processed.error_line}")

    final = await build_graph().ainvoke(PipelineState(raw_input=processed, language=processed.language))

    report = final.get("validator_report")
    print(f"[result]  retry_count={final.get('retry_count')} human_review={final.get('human_review_flag')}")
    if report is not None:
        print(f"[validator] overall_passed={report.overall_passed}")
        for name, gate in sorted(report.gate_results.items()):
            print(f"    {name}: passed={gate.passed}")

    patch = final.get("patcher_output")
    if patch is not None:
        print("\n[patched_code]\n" + patch.patched_code)


if __name__ == "__main__":
    asyncio.run(main())
