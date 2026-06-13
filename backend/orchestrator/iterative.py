"""Iterative multi-bug fixing.

The single-bug graph fixes the first surfaced error. This wraps it in an outer
loop: fix a bug, splice the patch into the full module, re-run from the input
handler so the *next* error surfaces, and repeat until the code runs clean, gets
stuck (can't fix / no progress), or hits the iteration cap.

Proof model
───────────
A fix is accepted if EITHER a per-bug behavioral test proves it (``behavioral_test``)
OR the whole patched program now runs end-to-end without crashing (``runs_clean``) /
progresses past this crash (``runs_further``). The integration proof lets us fix
bugs whose behavior is awkward to unit-test (e.g. side-effecting print functions).

Note: the ContextPackage is rebuilt fresh each iteration. Carrying it forward is
unsafe — consecutive bugs are usually in *different* functions, so the function
source / signature / call graph are bug-specific, not module invariants.
"""
from __future__ import annotations

from typing import Any, Callable, Literal, Protocol

from pydantic import BaseModel

from backend.agents.patcher import PatcherAgent
from backend.input_handler.models import ProcessedInput, RawInput
from backend.input_handler.service import smart_input_handler
from backend.llm.client import llm_client
from backend.orchestrator.graph import build_graph
from backend.orchestrator.state import DiagnoserOutput, Hypothesis, PipelineState
from backend.tools.context_builder import context_builder
from backend.tools.validator import splice_patched_module

# (candidate_code, patch_target, root_cause) or None if no testless fix was produced.
TestlessFix = tuple[str, str, str]


class InputHandler(Protocol):
    async def handle(self, request: RawInput) -> ProcessedInput: ...


class Graph(Protocol):
    async def ainvoke(self, state: PipelineState) -> dict[str, Any]: ...


class TestlessFixer(Protocol):
    async def __call__(self, processed: ProcessedInput) -> TestlessFix | None: ...


class FixStep(BaseModel):
    iteration: int
    error_type: str | None
    error_line: int | None
    fixed: bool
    # How the fix was proven:
    #   "behavioral_test" — a generated test fails-on-original, passes-on-patched
    #   "runs_clean"      — whole program now runs end-to-end without crashing
    #   "runs_further"    — program progressed past this crash (new crash surfaced)
    #   ""                — not fixed
    proof: str = ""
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
    testless_fixer: TestlessFixer | None = None,
) -> IterativeResult:
    """Fix bugs one-at-a-time, re-running the pipeline after each splice.

    ``on_step`` is an optional callback invoked after each FixStep is recorded.
    ``testless_fixer`` is the fallback used when the graph produces no patch
    (e.g. the Diagnoser couldn't write a behavioral test); it patches directly
    from the error and is proven by integration. Injectable for tests.
    """
    if graph is None:
        graph = build_graph()
    fixer: TestlessFixer = testless_fixer or _testless_fix

    current_code = code
    steps: list[FixStep] = []
    bugs_fixed = 0
    status: Literal["clean", "stuck", "max_iterations", "timeout"] = "max_iterations"

    # The candidate run after each accepted fix doubles as the NEXT iteration's
    # input, so we run the handler once per iteration, not twice.
    processed = await handler.handle(RawInput(code=current_code, filename=filename))

    for iteration in range(1, max_iterations + 1):
        if processed.status == "execution_clean":
            status = "clean"
            break
        if processed.status == "execution_timeout":
            status = "timeout"
            _record(steps, on_step, _step(iteration, processed, fixed=False, detail="execution timed out"))
            break

        # Rebuild context fresh each iteration (context_package left None) — the next
        # bug is usually in a different function, so reuse would be stale.
        final = await graph.ainvoke(
            PipelineState(raw_input=processed, language=processed.language)
        )
        report = final.get("validator_report")
        patch = final.get("patcher_output")
        context = final.get("context_package")
        behavioral = bool(report and report.overall_passed)

        candidate: str | None = None
        target: str | None = None
        root = ""
        if patch and patch.patched_code and context:
            try:
                candidate = splice_patched_module(context, patch.patched_code, patch.patch_target_source)
                target = patch.patch_target
                root = _root_cause(final)
            except ValueError:
                candidate = None

        if candidate is None:
            # Graph produced no usable patch (Diagnoser asked for clarification /
            # dead-ended, or splice failed). Patch directly from the error and let
            # integration proof decide.
            fallback = await fixer(processed)
            if fallback is None:
                detail = (patch.blocked_reason if patch and patch.blocked_reason else "could not fix") or ""
                _record(steps, on_step, _step(iteration, processed, fixed=False, detail=detail))
                status = "stuck"
                break
            candidate, target, root = fallback
            behavioral = False

        if candidate.strip() == current_code.strip():  # no change — avoid spinning
            _record(steps, on_step, _step(iteration, processed, fixed=False, detail="patch made no change"))
            status = "stuck"
            break

        # INTEGRATION PROOF: run the whole candidate program. Accept the fix if a
        # per-bug test proved it OR the program now runs clean / progressed past
        # this crash. This run also feeds the next iteration.
        next_processed = await handler.handle(RawInput(code=candidate, filename=filename))
        runs_clean = next_processed.status == "execution_clean"
        same_bug = (
            next_processed.error_line == processed.error_line
            and next_processed.error_type == processed.error_type
        )
        progressed = runs_clean or not same_bug

        if not (behavioral or progressed):
            _record(steps, on_step, _step(iteration, processed, fixed=False, detail="patch did not get past the crash"))
            status = "stuck"
            break

        proof = "behavioral_test" if behavioral else ("runs_clean" if runs_clean else "runs_further")
        _record(
            steps, on_step,
            _step(iteration, processed, fixed=True, proof=proof, target=target, detail=root),
        )
        current_code = candidate
        bugs_fixed += 1
        processed = next_processed   # carry the candidate run forward

    return IterativeResult(
        status=status,
        bugs_fixed=bugs_fixed,
        total_iterations=len(steps),
        original_code=code,
        final_code=current_code,
        steps=steps,
    )


def _synth_diagnosis(processed: ProcessedInput) -> DiagnoserOutput:
    """A minimal diagnosis straight from the error — no behavioral test required.

    The trivial passing test imposes no contract; the Patcher fixes from the error
    + fix_direction, and integration proof verifies the whole program runs.
    """
    error_type = processed.error_type or "error"
    line = processed.error_line
    root = processed.error_message or f"{error_type} at line {line}"
    fix_dir = f"Fix the {error_type} at line {line} with the smallest correct change. {processed.error_message}".strip()
    return DiagnoserOutput(
        root_cause=root,
        hypotheses=[
            Hypothesis(id="H1", theory=root, confidence=0.7, fix_direction=fix_dir),
            Hypothesis(id="H2", theory="an alternative cause of the same error", confidence=0.2, fix_direction="consider a different cause"),
            Hypothesis(id="H3", theory="an unhandled edge case", confidence=0.1, fix_direction="handle the edge case"),
        ],
        generated_test="def test_runs():\n    assert True\n",
    )


async def _testless_fix(processed: ProcessedInput) -> TestlessFix | None:
    """Patch directly from the error (no Diagnoser test). Proven by integration."""
    try:
        ctx = await context_builder.build(processed)
        patch = await PatcherAgent(llm_client).patch(ctx, _synth_diagnosis(processed))
    except Exception:
        return None
    if not patch.patched_code:
        return None
    try:
        candidate = splice_patched_module(ctx, patch.patched_code, patch.patch_target_source)
    except ValueError:
        return None
    return candidate, patch.patch_target, _synth_diagnosis(processed).root_cause


def _step(iteration, processed, *, fixed, proof="", target=None, detail=""):
    return FixStep(
        iteration=iteration,
        error_type=processed.error_type,
        error_line=processed.error_line,
        fixed=fixed,
        proof=proof,
        patch_target=target,
        detail=detail[:300],
    )


def _record(steps: list[FixStep], on_step: Callable[[FixStep], None] | None, step: FixStep) -> None:
    steps.append(step)
    if on_step:
        on_step(step)


def _root_cause(final: dict) -> str:
    diag = final.get("diagnoser_output")
    return diag.root_cause if diag is not None else ""
