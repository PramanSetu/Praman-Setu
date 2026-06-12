"""Demo: iterative multi-bug fixing on a single file.

Run:  uv run python -m backend.tools.iterative_smoke
"""
from __future__ import annotations

import asyncio
from time import perf_counter

from backend.llm.client import llm_client
from backend.orchestrator.iterative import iterative_fix

# Three independent, unambiguous bugs that surface one after another at runtime.
CODE = '''GREETING = "Hello"


def greet(name):
    return GREETING + ", " + nam


def shout(text):
    return text.uppercase()


def repeat(text, times):
    return text * tims


print(greet("Asha"))
print(shout("hi"))
print(repeat("ab", 3))
'''


async def main() -> None:
    started = perf_counter()
    result = await iterative_fix(CODE, "demo.py", max_iterations=6)
    elapsed = (perf_counter() - started) * 1000

    print(
        f"status={result.status} bugs_fixed={result.bugs_fixed} "
        f"iterations={result.total_iterations} ({elapsed:.0f}ms)\n"
    )
    for step in result.steps:
        mark = "FIXED" if step.fixed else "STUCK"
        print(f"  [{step.iteration}] {mark}  {step.error_type} @ line {step.error_line}: {step.detail}")

    print("\n=== FINAL CODE ===")
    print(result.final_code)
    await llm_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
