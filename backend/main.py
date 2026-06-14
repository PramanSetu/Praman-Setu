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

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Any, AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.agents.critic import CriticAgent, CritiqueReport
from backend.agents.explainer import ExplainerAgent, RepairExplanation
from backend.config import settings
from backend.input_handler import ProcessedInput, RawInput, smart_input_handler
from backend.input_handler.detector import UnsupportedLanguageError
from backend.llm.client import llm_client
from backend.observability.metrics import build_run_trace
from backend.orchestrator.graph import build_graph
from backend.orchestrator.iterative import iterative_fix
from backend.orchestrator.repair_v2 import RepairV2Result, repair_v2
from backend.orchestrator.state import PipelineState
from backend.tools.sandbox.pool import sandbox_pool


# ---------------------------------------------------------------------------
# Application state — populated in lifespan, consumed by route handlers
# ---------------------------------------------------------------------------

class _AppState:
    pipeline: Any = None          # compiled LangGraph (with checkpointer)
    checkpointer: Any = None      # AsyncSqliteSaver context manager handle


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
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],  # Vite dev server
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


class RepairV2Response(BaseModel):
    result: RepairV2Result
    explanation: RepairExplanation | None = None
    critique: CritiqueReport | None = None


@app.post("/api/repair-v2")
async def repair_v2_endpoint(
    payload: RawInput, max_passes: int = 3, explain: bool = True, critique: bool = True
) -> RepairV2Response:
    """Primary pasted-file repair path: bug ledger -> AST unit splice -> full-file validation.

    With ``explain=true`` (default) a human-readable narrative is attached.
    With ``critique=true`` (default) a semantic review (root-cause / intent /
    confidence) is attached, whose ``needs_human_review`` is the authoritative
    flag list.
    """
    try:
        result = await repair_v2(payload.code, payload.filename, max_passes=max_passes)
    except UnsupportedLanguageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Explainer and Critic are independent — run them concurrently (one round-trip).
    exp_task = asyncio.ensure_future(ExplainerAgent(llm_client).explain(result)) if explain else None
    crit_task = asyncio.ensure_future(CriticAgent(llm_client).review(result)) if critique else None
    explanation = await exp_task if exp_task is not None else None
    critique_report = await crit_task if crit_task is not None else None
    return RepairV2Response(result=result, explanation=explanation, critique=critique_report)


@app.post("/api/repair-v2/stream")
async def repair_v2_stream_endpoint(
    payload: RawInput,
    max_passes: int = 3,
    explain: bool = True,
    critique: bool = True,
) -> StreamingResponse:
    """Stream the primary repair path as Server-Sent Events.

    This is the UI-friendly endpoint for live repair progress. The repair agent
    still returns structured JSON after each LLM call, so this streams pipeline
    milestones and code snapshots rather than raw model tokens.
    """
    return StreamingResponse(
        _repair_v2_sse_stream(
            payload,
            max_passes=max(1, min(max_passes, 5)),
            explain=explain,
            critique=critique,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


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


async def _repair_v2_sse_stream(
    payload: RawInput,
    *,
    max_passes: int,
    explain: bool,
    critique: bool,
) -> AsyncGenerator[str, None]:
    queue: asyncio.Queue[tuple[str | None, dict[str, Any] | None]] = asyncio.Queue()

    async def publish(event_type: str, data: dict[str, Any]) -> None:
        await queue.put((event_type, data))

    async def run() -> None:
        try:
            result = await repair_v2(
                payload.code,
                payload.filename,
                max_passes=max_passes,
                on_event=publish,
            )

            explanation: RepairExplanation | None = None
            critique_report: CritiqueReport | None = None
            exp_task = asyncio.ensure_future(ExplainerAgent(llm_client).explain(result)) if explain else None
            crit_task = asyncio.ensure_future(CriticAgent(llm_client).review(result)) if critique else None

            tasks: set[asyncio.Task] = set()
            task_names: dict[asyncio.Task, str] = {}
            if exp_task is not None:
                tasks.add(exp_task)
                task_names[exp_task] = "explanation"
                await publish("phase", {"stage": "Explainer Agent", "status": "running"})
            if crit_task is not None:
                tasks.add(crit_task)
                task_names[crit_task] = "critique"
                await publish("phase", {"stage": "Critic Agent", "status": "running"})

            while tasks:
                done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    name = task_names[task]
                    if name == "explanation":
                        explanation = task.result()
                        await publish("explanation", {"explanation": explanation.model_dump(mode="json")})
                    else:
                        critique_report = task.result()
                        await publish("critique", {"critique": critique_report.model_dump(mode="json")})

            await publish(
                "done",
                {
                    "result": result.model_dump(mode="json"),
                    "explanation": explanation.model_dump(mode="json") if explanation else None,
                    "critique": critique_report.model_dump(mode="json") if critique_report else None,
                },
            )
        except UnsupportedLanguageError as exc:
            await publish("error", {"message": str(exc), "status_code": 400})
        except Exception as exc:  # noqa: BLE001
            await publish("error", {"message": str(exc), "status_code": 500})
        finally:
            await queue.put((None, None))

    task = asyncio.create_task(run())
    try:
        while True:
            event_type, data = await queue.get()
            if event_type is None:
                break
            yield _sse_event(event_type, data or {})
    finally:
        if not task.done():
            task.cancel()


def _sse_event(event_type: str, data: dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, default=str)}\n\n"


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
