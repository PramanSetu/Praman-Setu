"""Praman Setu backend entrypoint.

Minimal runnable FastAPI app. The agent/tool/orchestrator layers from
FINAL_ARCHITECTURE.md are built on top of this scaffold in subsequent steps.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.input_handler import ProcessedInput, RawInput, smart_input_handler
from backend.input_handler.detector import UnsupportedLanguageError
from backend.orchestrator.graph import build_graph
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
async def analyze(payload: RawInput) -> dict[str, object]:
    """Full pipeline: Input -> Context -> Diagnoser -> Patcher -> Validator (-> Reflector)*."""
    try:
        processed = await smart_input_handler.handle(payload)
    except UnsupportedLanguageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    state = PipelineState(raw_input=processed, language=processed.language)
    final = await _PIPELINE.ainvoke(state)

    return {
        "status": processed.status,
        "diagnoser_output": final.get("diagnoser_output"),
        "patcher_output": final.get("patcher_output"),
        "validator_report": final.get("validator_report"),
        "retry_count": final.get("retry_count", 0),
        "human_review_flag": final.get("human_review_flag", False),
    }
