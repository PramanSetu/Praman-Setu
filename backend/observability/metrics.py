"""Lightweight, JSON-compatible run metrics — no external infra.

LLM-call metrics are collected through a ``ContextVar`` so the per-node, freshly
constructed agents don't need to thread a collector around: a node opens a
``collect_llm_calls()`` scope, runs its agent, and reads back every call the
LLMClient recorded inside that scope. This keeps runs isolated (async-safe) while
the LLMClient itself stays a process-wide singleton with a warm connection pool.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from pydantic import BaseModel

# Rough per-stage budgets (ms). Provisional — tune from measured baselines.
BUDGETS_MS = {
    "context_builder_ms": 100,
    "diagnoser_ms": 1500,
    "patcher_ms": 2500,
    "validator_ms": 4000,
    "reflector_ms": 1500,
    "total_ms": 9000,
}


class LLMCallMetric(BaseModel):
    provider: str
    model: str
    latency_ms: float
    fallback_used: bool
    schema_name: str
    success: bool
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


_collector: ContextVar[list[LLMCallMetric] | None] = ContextVar("llm_metrics", default=None)


def record_llm_call(metric: LLMCallMetric) -> None:
    """Append a call metric to the active scope, if one is open (else no-op)."""
    sink = _collector.get()
    if sink is not None:
        sink.append(metric)


@contextmanager
def collect_llm_calls() -> Iterator[list[LLMCallMetric]]:
    """Open a collection scope; the yielded list fills as LLM calls complete."""
    sink: list[LLMCallMetric] = []
    token = _collector.set(sink)
    try:
        yield sink
    finally:
        _collector.reset(token)


def gate_timings(validator_report: Any) -> dict[str, float]:
    """Compact per-gate millisecond summary from a ValidatorReport (or {})."""
    if validator_report is None:
        return {}
    return {
        f"{name}_ms": round(gate.duration_s * 1000, 1)
        for name, gate in validator_report.gate_results.items()
    }


def summarize_llm_calls(calls: list[LLMCallMetric]) -> dict[str, Any]:
    return {
        "count": len(calls),
        "total_latency_ms": round(sum(c.latency_ms for c in calls), 1),
        "total_tokens": sum(c.total_tokens or 0 for c in calls),
        "fallback_used": any(c.fallback_used for c in calls),
    }


def check_budgets(node_timings: dict[str, float]) -> list[str]:
    warnings: list[str] = []
    for key, budget in BUDGETS_MS.items():
        value = node_timings.get(key)
        if value is not None and value > budget:
            warnings.append(f"{key}={value:.0f}ms exceeds budget {budget}ms")
    return warnings


def build_run_trace(final: dict, *, input_handler_ms: float, total_ms: float) -> dict[str, Any]:
    """Assemble the lightweight, JSON-compatible run trace."""
    node_timings = dict(final.get("node_timings", {}))
    node_timings["input_handler_ms"] = round(input_handler_ms, 1)
    node_timings["total_ms"] = round(total_ms, 1)
    calls: list[LLMCallMetric] = final.get("llm_calls", [])
    return {
        "node_timings": node_timings,
        "gate_timings": gate_timings(final.get("validator_report")),
        "context_metrics": final.get("context_metrics", {}),
        "llm": summarize_llm_calls(calls),
        "budget_warnings": check_budgets(node_timings),
    }
