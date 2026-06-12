"""Iterative multi-bug fixing.

The single-bug graph fixes the first surfaced error. This wraps it in an outer
loop: fix a bug, splice the patch into the full module, re-run from the input
handler so the *next* error surfaces, and repeat until the code runs clean, gets
stuck (can't fix / no progress), or hits the iteration cap.

Stateful re-entry optimisation
───────────────────────────────
After a successful fix the ContextPackage from the previous iteration is carried
forward into the next PipelineState.  Because run_context_builder in graph.py has
a skip-guard (``if state.context_package is not None: return {}``), the tree-sitter
parse + stdlib AST enrichment are skipped entirely for subsequent iterations.  Only
the Input Handler re-run (unavoidable — must discover the next crash in the changed
code) and the LLM calls (unavoidable — different bug each time) remain.

The reused ContextPackage has its ``full_code`` updated to the newly-spliced code
and ``error_line`` / ``error_node`` / ``error_window_with_lines`` cleared so the
Diagnoser receives the fresh runtime trace from the new ProcessedInput rather than
stale window text.  All structural fields (imports, callers, callees, constants,
enclosing_class) are reused as-is — they are properties of the module structure,
not of the specific bug.
"""
from __future__ import annotations

from typing import Any, Callable, Literal, Protocol

from pydantic import BaseModel

from backend.input_handler.models import ProcessedInput, RawInput
from backend.input_handler.service import smart_input_handler
from backend.orchestrator.graph import build_graph
from backend.orchestrator.state import ContextPackage, PipelineState
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
    on_step: Callable[[FixStep], None] | None = None,
) -> IterativeResult:
    """Fix bugs one-at-a-time, re-running the pipeline after each splice.

    ``on_step`` is an optional callback invoked after each FixStep is recorded.
    The SSE endpoint in main.py uses it to emit steps as they complete.
    """
    if graph is None:
        graph = build_graph()

    current_code = code
    steps: list[FixStep] = []
    bugs_fixed = 0
    status: Literal["clean", "stuck", "max_iterations", "timeout"] = "max_iterations"

    # Carried across iterations — populated after the first successful fix.
    # None on the first iteration so the graph runs the full ContextBuilder.
    prior_context: ContextPackage | None = None

    for iteration in range(1, max_iterations + 1):
        processed = await handler.handle(RawInput(code=current_code, filename=filename))

        if processed.status == "execution_clean":
            status = "clean"
            break
        if processed.status == "execution_timeout":
            status = "timeout"
            step = _step(iteration, processed, fixed=False, detail="execution timed out")
            steps.append(step)
            if on_step:
                on_step(step)
            break

        # Re-use the prior ContextPackage when available (skip the tree-sitter
        # parse + AST enrichment — they are unchanged after a function-level splice).
        reused_context = _try_reuse_context(prior_context, processed, current_code)

        final = await graph.ainvoke(
            PipelineState(
                raw_input=processed,
                language=processed.language,
                context_package=reused_context,
            )
        )
        report = final.get("validator_report")
        patch = final.get("patcher_output")
        context = final.get("context_package")
        fixed = bool(report and report.overall_passed and patch and patch.patched_code and context)

        if not fixed:
            detail = (patch.blocked_reason if patch and patch.blocked_reason else "could not fix") or ""
            step = _step(iteration, processed, fixed=False, detail=detail)
            steps.append(step)
            if on_step:
                on_step(step)
            status = "stuck"
            break

        assert patch is not None and context is not None  # narrowed by `fixed`
        try:
            new_code = splice_patched_module(context, patch.patched_code, patch.patch_target_source)
        except ValueError as exc:
            step = _step(iteration, processed, fixed=False, detail=f"splice failed: {exc}")
            steps.append(step)
            if on_step:
                on_step(step)
            status = "stuck"
            break

        step = _step(
            iteration, processed, fixed=True, target=patch.patch_target, detail=_root_cause(final)
        )
        steps.append(step)
        if on_step:
            on_step(step)

        if new_code == current_code:  # no progress — avoid spinning
            status = "stuck"
            break

        current_code = new_code
        bugs_fixed += 1

        # Carry the context package forward; update full_code to the spliced module.
        # The skip-guard in run_context_builder will skip the parse next iteration.
        prior_context = context.model_copy(
            update={
                "full_code": new_code,
                # Clear error-specific fields — the Diagnoser will use the fresh
                # runtime_trace from the new ProcessedInput instead.
                "error_line": None,
                "error_node": "",
                "error_window_with_lines": "",
            }
        )

    return IterativeResult(
        status=status,
        bugs_fixed=bugs_fixed,
        total_iterations=len(steps),
        original_code=code,
        final_code=current_code,
        steps=steps,
    )


def _try_reuse_context(
    prior: ContextPackage | None,
    processed: ProcessedInput,
    new_code: str,
) -> ContextPackage | None:
    """Return a refreshed copy of `prior` suitable for the next iteration.

    Returns None on the first iteration (prior is None) so the ContextBuilder
    runs normally.  On subsequent iterations, updates full_code and clears
    error-specific fields so the Diagnoser reads from the fresh runtime_trace.
    """
    if prior is None:
        return None
    return prior.model_copy(
        update={
            "full_code": new_code,
            "error_line": processed.error_line,
            # Keep error_node/window empty — ContextBuilder skip-guard fires,
            # so these won't be re-populated.  The Diagnoser's primary evidence
            # comes from runtime_trace (injected via ProcessedInput), not the window.
            "error_node": "",
            "error_window_with_lines": "",
        }
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
