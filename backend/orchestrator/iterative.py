"""Iterative multi-bug fixing.

The single-bug graph fixes the first surfaced error. This wraps it in an outer
loop: fix a bug, splice the patch into the full module, re-run from the input
handler so the *next* error surfaces, and repeat until the code runs clean, gets
stuck (can't fix / no progress), or hits the iteration cap.
"""
from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel

from backend.input_handler.models import ProcessedInput, RawInput
from backend.input_handler.service import smart_input_handler
from backend.orchestrator.graph import build_graph
from backend.orchestrator.state import PipelineState
from backend.tools.validator import splice_patched_module


class InputHandler(Protocol):
    async def handle(self, request: RawInput) -> ProcessedInput: ...


class Graph(Protocol):
    async def ainvoke(self, state: PipelineState) -> dict[str, Any]: ...


class FixStep(BaseModel):
    iteration: int
    error_type: str | None
    error_line: int | None
    fixed: bool
    patch_target: str | None = None
    detail: str = ""


class IterativeResult(BaseModel):
    status: Literal["clean", "stuck", "max_iterations", "timeout"]
    bugs_fixed: int
    total_iterations: int
    original_code: str
    final_code: str
    steps: list[FixStep]


async def iterative_fix(
    code: str,
    filename: str | None = None,
    *,
    max_iterations: int = 5,
    handler: InputHandler = smart_input_handler,
    graph: Graph | None = None,
) -> IterativeResult:
    if graph is None:
        graph = build_graph()

    current_code = code
    steps: list[FixStep] = []
    bugs_fixed = 0
    status: Literal["clean", "stuck", "max_iterations", "timeout"] = "max_iterations"

    for iteration in range(1, max_iterations + 1):
        processed = await handler.handle(RawInput(code=current_code, filename=filename))

        if processed.status == "execution_clean":
            status = "clean"
            break
        if processed.status == "execution_timeout":
            status = "timeout"
            steps.append(_step(iteration, processed, fixed=False, detail="execution timed out"))
            break

        final = await graph.ainvoke(
            PipelineState(raw_input=processed, language=processed.language)
        )
        report = final.get("validator_report")
        patch = final.get("patcher_output")
        context = final.get("context_package")
        fixed = bool(report and report.overall_passed and patch and patch.patched_code and context)

        if not fixed:
            detail = (patch.blocked_reason if patch and patch.blocked_reason else "could not fix") or ""
            steps.append(_step(iteration, processed, fixed=False, detail=detail))
            status = "stuck"
            break

        assert patch is not None and context is not None  # narrowed by `fixed`
        try:
            new_code = splice_patched_module(context, patch.patched_code, patch.patch_target_source)
        except ValueError as exc:
            steps.append(_step(iteration, processed, fixed=False, detail=f"splice failed: {exc}"))
            status = "stuck"
            break

        steps.append(
            _step(iteration, processed, fixed=True, target=patch.patch_target, detail=_root_cause(final))
        )

        if new_code == current_code:  # no progress — avoid spinning
            status = "stuck"
            break
        current_code = new_code
        bugs_fixed += 1

    return IterativeResult(
        status=status,
        bugs_fixed=bugs_fixed,
        total_iterations=len(steps),
        original_code=code,
        final_code=current_code,
        steps=steps,
    )


def _step(iteration, processed, *, fixed, target=None, detail=""):
    return FixStep(
        iteration=iteration,
        error_type=processed.error_type,
        error_line=processed.error_line,
        fixed=fixed,
        patch_target=target,
        detail=detail[:300],
    )


def _root_cause(final: dict) -> str:
    diag = final.get("diagnoser_output")
    return diag.root_cause if diag is not None else ""
