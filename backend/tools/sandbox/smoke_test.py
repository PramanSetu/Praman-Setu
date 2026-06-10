"""Manual isolation smoke test for the SandboxPool.

Requires Docker running and the image built:  docker compose build sandbox
Run with:  uv run python -m backend.tools.sandbox.smoke_test
"""
from __future__ import annotations

import asyncio

from backend.tools.sandbox.pool import sandbox_pool

CASES: list[tuple[str, str, str]] = [
    (
        "benign: prints + exits 0",
        "print('hello from sandbox')",
        "exit_code == 0 and 'hello' in stdout",
    ),
    (
        "network blocked (--network=none)",
        "import socket; socket.create_connection(('1.1.1.1', 53), timeout=3)",
        "exit_code != 0  (connection should fail)",
    ),
    (
        "read-only root filesystem",
        "open('/etc/passwd', 'w').write('x')",
        "exit_code != 0  (root fs is read-only)",
    ),
    (
        "writable tmpfs workspace",
        "open('/workspace/out.txt', 'w').write('ok'); print('wrote', open('/workspace/out.txt').read())",
        "exit_code == 0  (/workspace tmpfs is writable)",
    ),
    (
        "timeout kills runaway code",
        "while True: pass",
        "timed_out is True",
    ),
]


async def main() -> None:
    for title, code, expectation in CASES:
        timeout = 3 if "timeout" in title else 10
        result = await sandbox_pool.execute("python", code, timeout=timeout)
        print(f"\n=== {title} ===")
        print(f"  expect : {expectation}")
        print(f"  exit   : {result.exit_code}   timed_out={result.timed_out}   {result.duration_s}s")
        if result.stdout.strip():
            print(f"  stdout : {result.stdout.strip()[:200]}")
        if result.stderr.strip():
            print(f"  stderr : {result.stderr.strip()[:200]}")


if __name__ == "__main__":
    asyncio.run(main())
