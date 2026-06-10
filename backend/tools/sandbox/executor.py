"""Low-level container execution under the hardening flags from §4.1.

The strategy: start a hardened, idle container with the user's code passed in as a
base64 env var, then `exec` a tiny bootstrap that decodes the code into the tmpfs
workspace and runs it. We avoid the Docker copy API (`put_archive`) because the
daemon rejects it on a read-only-rootfs container; the container's *own* process,
however, can freely write to a tmpfs mount. No host bind-mount is used, so this
works whether the backend runs on the host or inside its own container with
docker.sock mounted. The container is always destroyed afterward.
"""
from __future__ import annotations

import base64
import concurrent.futures
import shlex
import time

import docker
from docker.models.containers import Container
from pydantic import BaseModel

# Resolved lazily so importing this module never requires a running daemon.
_client: docker.DockerClient | None = None


def get_client() -> docker.DockerClient:
    global _client
    if _client is None:
        _client = docker.from_env()
    return _client


class SandboxResult(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_s: float


# Hardening applied to every spawned container (§4.1). The writable areas are
# tmpfs (RAM, wiped on exit); the root filesystem is read-only.
_TMPFS = {
    "/tmp": "rw,exec,size=64m,mode=1777",
    "/workspace": "rw,exec,size=128m,mode=1777",
}


def _hardening_kwargs() -> dict:
    return dict(
        network_mode="none",                      # no network → no exfiltration
        read_only=True,                           # immutable root filesystem
        cap_drop=["ALL"],                         # drop all Linux capabilities
        security_opt=["no-new-privileges"],
        user="1000:1000",                         # non-root (matches sandboxuser)
        mem_limit="512m",
        memswap_limit="512m",                     # == mem_limit ⇒ swap disabled
        nano_cpus=1_000_000_000,                  # 1.0 CPU
        pids_limit=64,                            # no fork bombs
        ulimits=[docker.types.Ulimit(name="nofile", soft=64, hard=64)],
        tmpfs=_TMPFS,
        working_dir="/workspace",
    )


def _bootstrap(filename: str, cmd: list[str]) -> list[str]:
    """Shell that materializes the code from the env var, then runs the command.

    The container process writes to /workspace (tmpfs) — allowed under a read-only
    root — so no external copy API is needed.
    """
    script = (
        f'printf "%s" "$PRAMAN_SETU_CODE_B64" | base64 -d > /workspace/{filename} && '
        f"exec {shlex.join(cmd)}"
    )
    return ["sh", "-c", script]


def run_in_container(
    image: str,
    filename: str,
    code: str,
    cmd: list[str],
    timeout: int,
) -> SandboxResult:
    """Execute `code` in a fresh hardened container and return captured output."""
    client = get_client()
    started = time.monotonic()

    code_b64 = base64.b64encode(code.encode("utf-8")).decode("ascii")

    # Keepalive command holds the namespaces open while we exec the bootstrap.
    container: Container = client.containers.run(
        image,
        command=["sleep", str(timeout + 10)],
        detach=True,
        environment={"PRAMAN_SETU_CODE_B64": code_b64},
        **_hardening_kwargs(),
    )

    try:
        timed_out = False
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(
                container.exec_run,
                _bootstrap(filename, cmd),
                demux=True,
                workdir="/workspace",
            )
            try:
                result = future.result(timeout=timeout)
                exit_code = result.exit_code
                raw_out, raw_err = result.output  # demux=True ⇒ (stdout, stderr)
            except concurrent.futures.TimeoutError:
                container.kill()  # unblocks the exec call so the thread can finish
                timed_out = True
                exit_code, raw_out, raw_err = -1, b"", b"sandbox: timed out"

        return SandboxResult(
            exit_code=exit_code,
            stdout=(raw_out or b"").decode("utf-8", errors="replace"),
            stderr=(raw_err or b"").decode("utf-8", errors="replace"),
            timed_out=timed_out,
            duration_s=round(time.monotonic() - started, 3),
        )
    finally:
        try:
            container.remove(force=True)
        except docker.errors.APIError:
            pass
