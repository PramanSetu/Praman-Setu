"""SandboxPool — the public entry point for sandboxed execution.

v1 implements the per-execution path: each call spawns a fresh hardened
container. The pre-warmed pool (`docker exec` into kept-warm containers, §4.2) is
a later optimization that can slot in behind this same `execute()` interface.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from backend.config import settings
from backend.tools.sandbox.executor import SandboxResult, run_in_container


@dataclass(frozen=True)
class LanguageSpec:
    image: str
    filename: str
    run_cmd: list[str]


# Only Python exists today; more images get added as adapters land.
LANGUAGES: dict[str, LanguageSpec] = {
    "python": LanguageSpec(
        image="praman-setu-sandbox-python:latest",
        filename="main.py",
        run_cmd=["python", "main.py"],
    ),
}


class UnsupportedLanguageError(ValueError):
    pass


class SandboxPool:
    async def execute(
        self,
        language: str,
        code: str,
        cmd: list[str] | None = None,
        timeout: int | None = None,
    ) -> SandboxResult:
        spec = LANGUAGES.get(language)
        if spec is None:
            raise UnsupportedLanguageError(
                f"no sandbox image for language={language!r} "
                f"(have: {', '.join(LANGUAGES)})"
            )

        # Docker SDK is blocking; keep the event loop free.
        return await asyncio.to_thread(
            run_in_container,
            image=spec.image,
            filename=spec.filename,
            code=code,
            cmd=cmd or spec.run_cmd,
            timeout=timeout or settings.sandbox_timeout,
        )


# Process-wide singleton (the pre-warmed pool will hold real state here later).
sandbox_pool = SandboxPool()
