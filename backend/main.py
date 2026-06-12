"""Praman Setu backend entrypoint.

Minimal runnable FastAPI app. The agent/tool/orchestrator layers from
FINAL_ARCHITECTURE.md are built on top of this scaffold in subsequent steps.
"""
from __future__ import annotations

from time import perf_counter

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.input_handler import ProcessedInput, RawInput, smart_input_handler
from backend.input_handler.detector import UnsupportedLanguageError
from backend.llm.client import llm_client
from backend.observability.metrics import build_run_trace
from backend.orchestrator.graph import build_graph
from backend.orchestrator.iterative import IterativeResult, iterative_fix
from backend.orchestrator.state import PipelineState

app = FastAPI(title="Praman Setu", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Compiled once; the graph is stateless across requests.
_PIPELINE = build_graph()


@app.on_event("shutdown")
async def _close_llm_client() -> None:
    await llm_client.aclose()


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
    }


@app.post("/api/input/handle")
async def handle_input(payload: RawInput) -> ProcessedInput:
    try:
        return await smart_input_handler.handle(payload)
    except UnsupportedLanguageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/analyze")
async def analyze(payload: RawInput, debug: bool = False) -> dict[str, object]:
    """Full pipeline: Input -> Context -> Diagnoser -> Patcher -> Validator (-> Reflector)*.

    Pass ``?debug=true`` to include the lightweight performance trace.
    """
    started = perf_counter()
    try:
        processed = await smart_input_handler.handle(payload)
    except UnsupportedLanguageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    input_handler_ms = (perf_counter() - started) * 1000

    state = PipelineState(raw_input=processed, language=processed.language)
    final = await _PIPELINE.ainvoke(state)
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


@app.post("/api/fix")
async def fix(payload: RawInput, max_iterations: int = 5) -> IterativeResult:
    """Iteratively fix multiple bugs: fix one, re-run, repeat until clean or stuck."""
    try:
        return await iterative_fix(
            payload.code, payload.filename, max_iterations=max_iterations
        )
    except UnsupportedLanguageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
