from __future__ import annotations

from backend.agents.property_tester import PropertyTesterAgent, _parse_failures
from backend.tools.sandbox.executor import SandboxResult


def test_parse_failures_extracts_test_and_reason() -> None:
    output = (
        "main.py::test_ok PASSED\n"
        "FAILED main.py::test_find_max_member - AssertionError: assert 0 in [-5, -2]\n"
        "1 failed, 1 passed\n"
    )
    issues = _parse_failures(output)
    assert len(issues) == 1
    assert issues[0].test == "test_find_max_member"
    assert "assert 0 in [-5, -2]" in issues[0].detail


def test_parse_failures_empty_when_all_pass() -> None:
    assert _parse_failures("2 passed in 0.1s") == []


class _LLM:
    def __init__(self, tests: str = "", raises: bool = False) -> None:
        self.tests = tests
        self.raises = raises

    async def complete(self, *args, **kwargs):
        if self.raises:
            raise RuntimeError("llm down")
        return {"tests": self.tests}


def _runner(stdout: str, exit_code: int = 1, timed_out: bool = False):
    async def run(code: str, tests: str) -> SandboxResult:
        return SandboxResult(exit_code=exit_code, stdout=stdout, stderr="", timed_out=timed_out, duration_s=0.01)

    return run


async def test_probe_reports_proven_bugs() -> None:
    agent = PropertyTesterAgent(_LLM(tests="def test_x():\n    assert False\n"))  # type: ignore[arg-type]
    report = await agent.probe("code", _runner("FAILED main.py::test_x - AssertionError: nope", exit_code=1))
    assert report.status == "proven_bugs"
    assert report.proven_issues[0].test == "test_x"


async def test_probe_all_passed() -> None:
    agent = PropertyTesterAgent(_LLM(tests="def test_x():\n    assert True\n"))  # type: ignore[arg-type]
    report = await agent.probe("code", _runner("1 passed", exit_code=0))
    assert report.status == "all_passed"
    assert report.proven_issues == []


async def test_probe_no_tests_when_empty() -> None:
    agent = PropertyTesterAgent(_LLM(tests="   "))  # type: ignore[arg-type]
    report = await agent.probe("code", _runner("", exit_code=0))
    assert report.status == "no_tests"


async def test_probe_unavailable_on_llm_failure() -> None:
    agent = PropertyTesterAgent(_LLM(raises=True))  # type: ignore[arg-type]
    report = await agent.probe("code", _runner("", exit_code=0))
    assert report.status == "unavailable"


async def test_probe_unavailable_on_timeout() -> None:
    agent = PropertyTesterAgent(_LLM(tests="def test_x():\n    assert True\n"))  # type: ignore[arg-type]
    report = await agent.probe("code", _runner("", exit_code=0, timed_out=True))
    assert report.status == "unavailable"
