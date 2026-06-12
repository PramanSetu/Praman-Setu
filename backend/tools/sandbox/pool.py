"""SandboxPool — the public entry point for sandboxed execution.

Two concrete implementations share the same ``execute()`` interface:

  WarmContainerPool  (default, production):
    Maintains a pool of idle hardened containers that are kept alive between calls.
    Acquires a container, execs the bootstrap, resets the workspace, returns it.
    Per-call overhead: ~50–100 ms (exec + workspace reset), vs 700–2000 ms for the
    cold path (docker run + docker rm per call).
    Pool is warmed at application startup via ``warm()`` and drained at shutdown via
    ``drain()``.  Call both from the FastAPI ``lifespan`` context manager.

  SandboxPool  (cold path / fallback / unit tests):
    Spawns and destroys one container per ``execute()`` call.  No state between calls.
    Retained so unit tests and one-off scripts work without warming.
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque

import docker

from backend.config import settings
from backend.tools.sandbox.executor import (
    SandboxResult,
    exec_in_warm_container,
    reset_container_workspace,
    run_in_container,
    spawn_idle_container,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Language → image/filename/command mapping
# ---------------------------------------------------------------------------

from dataclasses import dataclass


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


# ---------------------------------------------------------------------------
# Cold path (one container per call — fallback / unit tests)
# ---------------------------------------------------------------------------

class SandboxPool:
    """Spawn-and-destroy sandbox.  Zero warm-up cost; high per-call latency."""

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
        return await asyncio.to_thread(
            run_in_container,
            image=spec.image,
            filename=spec.filename,
            code=code,
            cmd=cmd or spec.run_cmd,
            timeout=timeout or settings.sandbox_timeout,
        )


# ---------------------------------------------------------------------------
# Warm path — pre-warmed container pool (production default)
# ---------------------------------------------------------------------------

class WarmContainerPool:
    """Pool of idle hardened containers.

    Containers are spawned once at startup (``warm()``) and kept alive between
    requests.  Each ``execute()`` call acquires one container via exec (no docker
    run), runs the code, resets the /workspace tmpfs, and returns the container
    to the idle queue.

    Overflow: if all containers are busy, a temporary cold-path container is
    spawned for that call and destroyed afterward — same behaviour as the old
    SandboxPool, just for the extra burst.

    Thread safety: uses ``asyncio.Lock`` for the idle queue and an
    ``asyncio.Semaphore`` to cap total concurrency.
    """

    def __init__(self, pool_size: int = 4, keepalive_s: int = 3600) -> None:
        self._pool_size = pool_size
        self._keepalive_s = keepalive_s
        self._idle: deque = deque()
        self._sem: asyncio.Semaphore | None = None   # created in warm() (needs loop)
        self._lock: asyncio.Lock | None = None
        self._warmed = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def warm(self, language: str = "python") -> None:
        """Spawn ``pool_size`` idle containers.  Call once from FastAPI lifespan."""
        self._sem = asyncio.Semaphore(self._pool_size * 2)   # allow burst overhead
        self._lock = asyncio.Lock()

        spec = LANGUAGES.get(language)
        if spec is None:
            raise UnsupportedLanguageError(f"no sandbox image for language={language!r}")

        logger.info("Warming sandbox pool (%d containers, image=%s)…", self._pool_size, spec.image)
        containers = await asyncio.gather(
            *[
                asyncio.to_thread(spawn_idle_container, spec.image, self._keepalive_s)
                for _ in range(self._pool_size)
            ],
            return_exceptions=True,
        )
        for i, result in enumerate(containers):
            if isinstance(result, Exception):
                logger.warning("Failed to warm container slot %d: %s", i, result)
            else:
                self._idle.append(result)

        self._warmed = True
        logger.info("Sandbox pool ready (%d/%d containers warmed).", len(self._idle), self._pool_size)

    async def drain(self) -> None:
        """Destroy all idle containers.  Call from FastAPI lifespan shutdown."""
        if self._lock is None:
            return
        async with self._lock:
            while self._idle:
                c = self._idle.popleft()
                try:
                    await asyncio.to_thread(c.remove, force=True)
                except docker.errors.APIError:
                    pass
        logger.info("Sandbox pool drained.")

    # ------------------------------------------------------------------
    # Public execute() — same signature as SandboxPool
    # ------------------------------------------------------------------

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

        # Fall back to cold path if pool was never warmed (tests / scripts).
        if not self._warmed:
            return await asyncio.to_thread(
                run_in_container,
                image=spec.image,
                filename=spec.filename,
                code=code,
                cmd=cmd or spec.run_cmd,
                timeout=timeout or settings.sandbox_timeout,
            )

        assert self._sem is not None and self._lock is not None
        async with self._sem:
            container = await self._acquire(spec)
            use_warm = container is not None

            if not use_warm:
                # Overflow: no idle container — cold-path fallback for this call.
                return await asyncio.to_thread(
                    run_in_container,
                    image=spec.image,
                    filename=spec.filename,
                    code=code,
                    cmd=cmd or spec.run_cmd,
                    timeout=timeout or settings.sandbox_timeout,
                )

            try:
                result = await asyncio.to_thread(
                    exec_in_warm_container,
                    container,
                    spec.filename,
                    code,
                    cmd or spec.run_cmd,
                    timeout or settings.sandbox_timeout,
                )
            except Exception:
                # Container may have crashed; discard it rather than returning it.
                try:
                    await asyncio.to_thread(container.remove, force=True)
                except docker.errors.APIError:
                    pass
                # Replenish: spawn a replacement in the background.
                asyncio.create_task(self._replenish(spec))
                raise
            else:
                await self._release(container)
            return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _acquire(self, spec: LanguageSpec):
        """Pop one idle container.  Returns None if pool is empty (overflow)."""
        assert self._lock is not None
        async with self._lock:
            if self._idle:
                return self._idle.popleft()
        return None

    async def _release(self, container) -> None:
        """Reset the workspace and return the container to the idle queue."""
        assert self._lock is not None
        # Workspace reset is a fast rm -rf on tmpfs — done in a thread.
        await asyncio.to_thread(reset_container_workspace, container)
        async with self._lock:
            if len(self._idle) < self._pool_size:
                self._idle.append(container)
            else:
                # Pool is full (e.g. overflow container being returned) — discard.
                try:
                    await asyncio.to_thread(container.remove, force=True)
                except docker.errors.APIError:
                    pass

    async def _replenish(self, spec: LanguageSpec) -> None:
        """Spawn a replacement container after one is discarded (background task)."""
        try:
            c = await asyncio.to_thread(spawn_idle_container, spec.image, self._keepalive_s)
            assert self._lock is not None
            async with self._lock:
                if len(self._idle) < self._pool_size:
                    self._idle.append(c)
                else:
                    await asyncio.to_thread(c.remove, force=True)
        except Exception as exc:
            logger.warning("Failed to replenish sandbox pool slot: %s", exc)


# ---------------------------------------------------------------------------
# Process-wide singleton
# ---------------------------------------------------------------------------

# WarmContainerPool is the default.  It starts in the un-warmed state and
# falls back to the cold path until ``warm()`` is called from the FastAPI
# lifespan.  Unit tests and scripts never call ``warm()``, so they continue
# to use the cold path transparently.
sandbox_pool = WarmContainerPool(pool_size=4)
