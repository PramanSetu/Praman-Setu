"""Performance benchmark over the realistic cases — quick numbers after a change.

Runs each case through the full live graph and prints per-stage timings, retry
count, and token usage, plus any budget warnings.

Requires: Docker running, sandbox image built, GROQ_API_KEY in .env.
Run:  uv run python -m backend.tools.perf_smoke
"""
from __future__ import annotations

import asyncio
from time import perf_counter

from backend.input_handler.models import RawInput
from backend.input_handler.service import smart_input_handler
from backend.llm.client import llm_client
from backend.observability.metrics import build_run_trace
from backend.orchestrator.graph import build_graph
from backend.orchestrator.state import PipelineState
from backend.tools.realistic_smoke import CASES


async def main() -> None:
    graph = build_graph()
    totals: list[float] = []
    passes = 0
    try:
        for case in CASES:
            started = perf_counter()
            processed = await smart_input_handler.handle(
                RawInput(code=case.code, filename=case.filename)
            )
            input_handler_ms = (perf_counter() - started) * 1000
            final = await graph.ainvoke(
                PipelineState(raw_input=processed, language=processed.language)
            )
            total_ms = (perf_counter() - started) * 1000

            trace = build_run_trace(
                final, input_handler_ms=input_handler_ms, total_ms=total_ms
            )
            nt = trace["node_timings"]
            report = final.get("validator_report")
            passed = bool(report and report.overall_passed)
            passes += int(passed)
            totals.append(total_ms)

            print(
                f"[{case.name[:38]:38}] passed={passed!s:5} "
                f"total={nt['total_ms']:6.0f}ms  "
                f"diag={nt.get('diagnoser_ms', 0):5.0f}  "
                f"patch={nt.get('patcher_ms', 0):5.0f}  "
                f"val={nt.get('validator_ms', 0):5.0f}  "
                f"retry={final.get('retry_count', 0)}  "
                f"tok={trace['llm']['total_tokens']}"
            )
            for warning in trace["budget_warnings"]:
                print(f"    ! {warning}")
    finally:
        await llm_client.aclose()

    avg = sum(totals) / len(totals) if totals else 0
    print(f"\nSUMMARY: {passes}/{len(CASES)} passed | avg total {avg:.0f}ms")


if __name__ == "__main__":
    asyncio.run(main())
