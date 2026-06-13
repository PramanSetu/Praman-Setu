"""Praman Setu backend entrypoint.

Startup sequence (FastAPI lifespan):
  1. Warm the container pool  — N idle hardened containers ready for exec calls.
  2. Open the SQLite checkpoint store — persists every LangGraph node transition.
  3. Compile the pipeline graph with the checkpointer attached.
  4. On shutdown: drain containers, close LLM client.

Per-request:
  - /api/analyze  — single-bug pipeline; config carries a UUID thread_id so the
                    checkpoint store can resume the run on LLM timeout.
  - /api/fix      — iterative multi-bug loop; stream=true returns SSE events.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from time import perf_counter
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from backend.config import settings
from backend.input_handler import ProcessedInput, RawInput, smart_input_handler
from backend.input_handler.detector import UnsupportedLanguageError
from backend.llm.client import llm_client
from backend.observability.metrics import build_run_trace
from backend.orchestrator.graph import build_graph
from backend.orchestrator.iterative import IterativeResult, iterative_fix
from backend.orchestrator.repair_v2 import RepairV2Result, repair_v2
from backend.orchestrator.state import PipelineState
from backend.tools.sandbox.pool import sandbox_pool


# ---------------------------------------------------------------------------
# Application state — populated in lifespan, consumed by route handlers
# ---------------------------------------------------------------------------

class _AppState:
    pipeline = None          # compiled LangGraph (with checkpointer)
    checkpointer = None      # AsyncSqliteSaver context manager handle


_state = _AppState()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    import logging
    log = logging.getLogger(__name__)

    # 1. Pre-warm the container pool.
    try:
        await sandbox_pool.warm()
    except Exception as exc:  # noqa: BLE001
        log.warning("Sandbox pool warm-up failed (%s) — falling back to cold-path spawning.", exc)

    # 2. Open SQLite checkpoint store for LangGraph pipeline state persistence.
    #    Falls back gracefully if the package isn't installed yet.
    checkpointer_cm = None
    try:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver  # type: ignore[import]
        checkpointer_cm = AsyncSqliteSaver.from_conn_string("./pipeline_checkpoints.db")
        _state.checkpointer = await checkpointer_cm.__aenter__()
        log.info("LangGraph checkpoint store opened (pipeline_checkpoints.db).")
    except ImportError:
        log.warning(
            "langgraph-checkpoint-sqlite not installed — checkpointing disabled. "
            "Run: uv add langgraph-checkpoint-sqlite"
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Checkpoint store failed to open (%s) — checkpointing disabled.", exc)

    # 3. Compile the pipeline graph (once, shared across all requests).
    _state.pipeline = build_graph(checkpointer=_state.checkpointer)
    log.info(
        "Pipeline graph compiled (checkpointing=%s).",
        "enabled" if _state.checkpointer else "disabled",
    )

    yield

    # Shutdown — drain containers, close checkpoint store, close LLM client.
    await sandbox_pool.drain()
    if checkpointer_cm is not None:
        try:
            await checkpointer_cm.__aexit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass
    await llm_client.aclose()


app = FastAPI(title="Praman Setu", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pipeline():
    """Return the compiled graph, falling back to a fresh compile if lifespan
    wasn't run (e.g. direct test imports)."""
    if _state.pipeline is None:
        _state.pipeline = build_graph()
    return _state.pipeline


def _thread_config() -> dict:
    """Per-request LangGraph config carrying a unique thread_id.

    Required by the checkpointer to namespace each pipeline run's state.
    Safe to call even when checkpointing is disabled — LangGraph ignores
    the configurable dict when there's no checkpointer.
    """
    return {"configurable": {"thread_id": str(uuid.uuid4())}}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
def root() -> dict[str, str]:
    return {"service": "Praman Setu backend", "version": "0.1.0", "status": "up"}


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "default_provider": settings.default_llm_provider,
        "groq_configured": bool(settings.groq_api_key),
        "sandbox_timeout": settings.sandbox_timeout,
        "sandbox_pool_warmed": sandbox_pool._warmed,
        "sandbox_pool_idle": len(sandbox_pool._idle),
        "checkpointing": _state.checkpointer is not None,
    }


@app.post("/api/input/handle")
async def handle_input(payload: RawInput) -> ProcessedInput:
    try:
        return await smart_input_handler.handle(payload)
    except UnsupportedLanguageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/analyze")
async def analyze(payload: RawInput, debug: bool = False) -> dict[str, object]:
    """Full single-bug pipeline: Input → Context → Diagnoser → Patcher → Validator (→ Reflector)*.

    Pass ``?debug=true`` to include the lightweight performance trace.
    Each request runs under a unique thread_id so the checkpoint store can
    resume the run if an LLM node times out mid-pipeline.
    """
    started = perf_counter()
    try:
        processed = await smart_input_handler.handle(payload)
    except UnsupportedLanguageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    input_handler_ms = (perf_counter() - started) * 1000

    state = PipelineState(raw_input=processed, language=processed.language)
    final = await _pipeline().ainvoke(state, config=_thread_config())
    total_ms = (perf_counter() - started) * 1000

    response: dict[str, object] = {
        "status": processed.status,
        "diagnoser_output": final.get("diagnoser_output"),
        "patcher_output": final.get("patcher_output"),
        "validator_report": final.get("validator_report"),
        "retry_count": final.get("retry_count", 0),
        "human_review_flag": final.get("human_review_flag", False),
        "hypothesis_used": final.get("hypothesis_used", "H1"),
        "patch_history": final.get("patch_history", []),
        "validation_history": final.get("validation_history", []),
        "patcher_prompts": final.get("patcher_prompts", []),
    }
    if debug:
        response["trace"] = build_run_trace(
            final, input_handler_ms=input_handler_ms, total_ms=total_ms
        )
    return response


@app.post("/api/repair-v2")
async def repair_v2_endpoint(payload: RawInput, max_passes: int = 3) -> RepairV2Result:
    """Primary pasted-file repair path: bug ledger -> exact edits -> full-file validation."""
    try:
        return await repair_v2(payload.code, payload.filename, max_passes=max_passes)
    except UnsupportedLanguageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/fix")
async def fix(
    payload: RawInput,
    max_iterations: int = 5,
    stream: bool = False,
    strategy: str = "repair_v2",
) -> object:
    """Fix pasted Python code.

    Default ``strategy=repair_v2`` uses the whole-file BugLedger + exact-edit
    repair path. Use ``strategy=iterative`` or ``stream=true`` for the legacy
    single-bug iterative graph.

    ``stream=false`` (default): returns the full ``IterativeResult`` JSON when done.
    ``stream=true``: returns a Server-Sent Events stream.  Each SSE event is one
    ``FixStep`` emitted as soon as that bug is resolved.  The final event is the
    complete ``IterativeResult``::

        data: {"type": "step",  "step":   {...}}\\n\\n   # one per fixed bug
        data: {"type": "done",  "result": {...}}\\n\\n   # final summary
    """
    try:
        if strategy == "repair_v2" and not stream:
            return await repair_v2(
                payload.code,
                payload.filename,
                max_passes=max(1, min(max_iterations, 5)),
            )
        if stream:
            return StreamingResponse(
                _fix_sse_stream(payload, max_iterations),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",   # prevent nginx from buffering SSE
                },
            )
        return await iterative_fix(
            payload.code,
            payload.filename,
            max_iterations=max_iterations,
            graph=_pipeline(),
        )
    except UnsupportedLanguageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _fix_sse_stream(
    payload: RawInput, max_iterations: int
) -> AsyncGenerator[str, None]:
    """Yield SSE events for each completed FixStep, then the final IterativeResult."""
    import json

    completed_steps: list = []

    def _on_step(step) -> None:
        completed_steps.append(step)

    # iterative_fix is fully async; we run it to completion and emit
    # buffered events.  For true per-step streaming, iterative_fix would
    # need to become an async generator — tracked for Phase 2.
    result = await iterative_fix(
        payload.code,
        payload.filename,
        max_iterations=max_iterations,
        graph=_pipeline(),
        on_step=_on_step,
    )

    for step in result.steps:
        data = json.dumps({"type": "step", "step": step.model_dump()})
        yield f"data: {data}\n\n"

    final_data = json.dumps({"type": "done", "result": result.model_dump()})
    yield f"data: {final_data}\n\n"
