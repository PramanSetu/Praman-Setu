from __future__ import annotations

import asyncio
import json

from backend.tools.sandbox.executor import SandboxResult
from backend.tools.tracer import build_harness, trace_execution


class FakeSandbox:
    def __init__(self, result: SandboxResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    async def execute(self, language: str, code: str, cmd=None, timeout=None) -> SandboxResult:
        self.calls.append((language, code))
        return self.result


def _trace_stdout(snapshots: list[dict], crash: dict | None, *, user_stdout: str = "") -> str:
    payload = json.dumps({"snapshots": snapshots, "crash": crash})
    return f"{user_stdout}<<<PRAMANSETU_TRACE>>>\n{payload}\n<<<PRAMANSETU_END>>>\n"


def test_build_harness_embeds_user_source() -> None:
    harness = build_harness("print(missing)")

    assert "print(missing)" in harness
    assert "sys.settrace" in harness
    assert 'compile(_SRC, "user_code.py"' in harness or "compile(_SRC" in harness


def test_captures_variables_at_crash() -> None:
    snapshots = [
        {"line": 1, "locals": {}},
        {"line": 2, "locals": {"a": "1", "b": "0"}},
    ]
    crash = {
        "type": "ZeroDivisionError",
        "msg": "division by zero",
        "line": None,
        "traceback": 'Traceback...\n  File "user_code.py", line 2\nZeroDivisionError: division by zero',
    }
    sandbox = FakeSandbox(
        SandboxResult(
            exit_code=0,
            stdout=_trace_stdout(snapshots, crash, user_stdout="some output\n"),
            stderr="",
            timed_out=False,
            duration_s=0.2,
        )
    )

    result = asyncio.run(trace_execution("python", "def d(a,b):\n return a/b\nd(1,0)", sandbox))

    assert result.captured_variables is True
    assert result.crashed is True
    assert result.crash_locals == {"a": "1", "b": "0"}
    assert result.crash_line == 2
    assert "ZeroDivisionError" in result.raw_stderr
    assert result.stdout == "some output"


def test_clean_run_has_no_crash() -> None:
    sandbox = FakeSandbox(
        SandboxResult(
            exit_code=0,
            stdout=_trace_stdout([{"line": 1, "locals": {}}], None, user_stdout="hello\n"),
            stderr="",
            timed_out=False,
            duration_s=0.1,
        )
    )

    result = asyncio.run(trace_execution("python", "print('hello')", sandbox))

    assert result.captured_variables is True
    assert result.crashed is False
    assert result.crash_locals is None
    assert result.stdout == "hello"


def test_degraded_when_no_trace_payload() -> None:
    # e.g. a timeout or syntax error that prevented the harness from emitting.
    sandbox = FakeSandbox(
        SandboxResult(
            exit_code=1,
            stdout="",
            stderr="NameError: name 'missing' is not defined",
            timed_out=False,
            duration_s=0.05,
        )
    )

    result = asyncio.run(trace_execution("python", "print(missing)", sandbox))

    assert result.captured_variables is False
    assert result.crashed is True
    assert result.raw_stderr == "NameError: name 'missing' is not defined"
    assert result.snapshots == []


def test_degraded_timeout() -> None:
    sandbox = FakeSandbox(
        SandboxResult(
            exit_code=-1, stdout="", stderr="sandbox: timed out", timed_out=True, duration_s=3.0
        )
    )

    result = asyncio.run(trace_execution("python", "while True: pass", sandbox))

    assert result.timed_out is True
    assert result.crashed is True
    assert result.captured_variables is False
