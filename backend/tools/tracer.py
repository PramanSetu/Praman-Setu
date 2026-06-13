"""Execution tracer — Context Builder Subtask A (§2.2), run inside the sandbox.

Wraps user code in a ``sys.settrace`` harness that records the local variables at
each executed line plus the crash state, giving the Diagnoser *observed* values
instead of speculation. The harness ``compile()``s the user source under the
virtual filename ``user_code.py`` and ``exec``s it, so traced frames report the
user's own line numbers (no offset arithmetic) and syntax errors surface with a
real ``lineno``.

This is the system's single user-code execution: the Smart Input Handler calls it
once, and the Context Builder consumes the result rather than re-running.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from backend.tools.sandbox.executor import SandboxResult

# Unique sentinels so user stdout can't be confused with the trace payload.
_TRACE_START = "<<<PRAMANSETU_TRACE>>>"
_TRACE_END = "<<<PRAMANSETU_END>>>"
_USER_SOURCE_TOKEN = "__USER_SOURCE_JSON__"
_MAX_SNAPSHOTS_KEPT = 25  # most recent line events; the crash sits at the tail

_HARNESS_TEMPLATE = '''import sys, json, traceback
from collections import deque

_USER_FILE = "user_code.py"
_TRACE = deque(maxlen=300)


def _tracer(frame, event, arg):
    if frame.f_code.co_filename != _USER_FILE:
        return None  # don't descend into the harness or imported libraries
    if event == "line":
        snap = {}
        for _k, _v in list(frame.f_locals.items()):
            try:
                snap[_k] = repr(_v)[:200]
            except Exception:
                snap[_k] = "<unrepresentable>"
        _TRACE.append({"line": frame.f_lineno, "locals": snap})
    return _tracer


_SRC = __USER_SOURCE_JSON__
_crash = None
_compiled = None
try:
    _compiled = compile(_SRC, _USER_FILE, "exec")
except SyntaxError as _e:
    _crash = {
        "type": "SyntaxError",
        "msg": str(_e),
        "line": _e.lineno,
        "traceback": traceback.format_exc(),
    }

if _compiled is not None:
    # Stub input() so headless execution proceeds past interactive reads instead
    # of EOFError. "1" is numeric-parseable (int(input()) works), non-zero, non-empty.
    _globals = {"__name__": "__main__", "__file__": _USER_FILE, "input": lambda *a, **k: "1"}
    sys.settrace(_tracer)
    try:
        exec(_compiled, _globals)
    except BaseException as _e:
        _crash = {
            "type": type(_e).__name__,
            "msg": str(_e),
            "line": None,
            "traceback": traceback.format_exc(),
        }
    finally:
        sys.settrace(None)

print("%s")
print(json.dumps({"snapshots": list(_TRACE), "crash": _crash}))
print("%s")
''' % (_TRACE_START, _TRACE_END)


class SandboxExecutor(Protocol):
    async def execute(
        self,
        language: str,
        code: str,
        cmd: list[str] | None = None,
        timeout: int | None = None,
    ) -> SandboxResult: ...


@dataclass(frozen=True)
class TraceResult:
    """Outcome of one traced execution."""

    stdout: str
    raw_stderr: str
    timed_out: bool
    duration_s: float
    exit_code: int
    crashed: bool
    captured_variables: bool
    crash_locals: dict[str, str] | None
    crash_line: int | None
    snapshots: list[dict[str, Any]] = field(default_factory=list)


def build_harness(code: str) -> str:
    return _HARNESS_TEMPLATE.replace(_USER_SOURCE_TOKEN, json.dumps(code))


def _parse_trace_stdout(stdout: str) -> tuple[str, dict[str, Any]] | None:
    if _TRACE_START not in stdout or _TRACE_END not in stdout:
        return None
    user_stdout, rest = stdout.split(_TRACE_START, 1)
    payload = rest.split(_TRACE_END, 1)[0].strip()
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return user_stdout.rstrip("\n"), data


async def trace_execution(
    language: str,
    code: str,
    sandbox: SandboxExecutor,
) -> TraceResult:
    """Run ``code`` once under the tracer harness and return captured evidence."""
    result = await sandbox.execute(language, build_harness(code))
    parsed = _parse_trace_stdout(result.stdout)

    if parsed is None:
        # Degraded: harness never emitted a payload (e.g. timeout, or a fake
        # sandbox in tests). Fall back to raw exit code / stderr.
        crashed = result.timed_out or result.exit_code != 0
        return TraceResult(
            stdout=result.stdout,
            raw_stderr=result.stderr,
            timed_out=result.timed_out,
            duration_s=result.duration_s,
            exit_code=result.exit_code,
            crashed=crashed,
            captured_variables=False,
            crash_locals=None,
            crash_line=None,
            snapshots=[],
        )

    user_stdout, data = parsed
    snapshots: list[dict[str, Any]] = data.get("snapshots") or []
    trimmed = snapshots[-_MAX_SNAPSHOTS_KEPT:]
    crash = data.get("crash")
    crashed = crash is not None

    crash_locals: dict[str, str] | None = None
    crash_line: int | None = None
    raw_stderr = ""
    if crash is not None:
        raw_stderr = crash.get("traceback") or f"{crash.get('type')}: {crash.get('msg')}"
        crash_line = crash.get("line")
        if snapshots:
            crash_locals = snapshots[-1].get("locals")
            if crash_line is None:
                crash_line = snapshots[-1].get("line")

    return TraceResult(
        stdout=user_stdout,
        raw_stderr=raw_stderr,
        timed_out=result.timed_out,
        duration_s=result.duration_s,
        exit_code=0 if not crashed else 1,
        crashed=crashed,
        captured_variables=True,
        crash_locals=crash_locals,
        crash_line=crash_line,
        snapshots=trimmed,
    )
