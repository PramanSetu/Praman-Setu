"""Tool 4 — the hardened execution sandbox (the chokepoint).

Every code execution in PatchMind funnels through here: the execution tracer,
the validation gates, and any user-code invocation.
"""
from backend.tools.sandbox.executor import SandboxResult
from backend.tools.sandbox.pool import SandboxPool, sandbox_pool

__all__ = ["SandboxPool", "SandboxResult", "sandbox_pool"]
