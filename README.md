# Praman Setu

Code generation + debug assistant — **5 agents · 6 deterministic tools · 1 hardened sandbox**.
See [FINAL_ARCHITECTURE.md](FINAL_ARCHITECTURE.md) for the full design.

This repo is the **project scaffold**: a runnable Docker dev environment. The
agent/tool/orchestrator layers are built on top of it incrementally.

## Stack

| Service   | What                                   | Port  | Auto-start |
|-----------|----------------------------------------|-------|------------|
| backend   | FastAPI + uvicorn (uv-managed deps)    | 8000  | yes        |
| frontend  | Vite dev server (React + TS)           | 5173  | yes        |
| sandbox   | Hardened Python 3.11 execution image   | —     | no (pool)  |

## Prerequisites

- Docker Desktop (with the WSL2 backend on Windows)
- A [Groq](https://console.groq.com) API key. Configure your Groq account with
  no billing method or strict spend limits if you want free-tier-only usage.

## Quick start

```bash
# 1. Configure secrets
cp .env.example .env          # then edit .env and set GROQ_API_KEY

# 2. Bring up backend + frontend (hot reload)
docker compose up --build

#   Frontend → http://localhost:5173
#   Backend  → http://localhost:8000/health
```

### Build the sandbox image

Not auto-started — it's spawned per-execution by the backend pool:

```bash
docker compose build sandbox
```

## Notes

- **Dependencies use `uv`**, not pip/venv. Edit [pyproject.toml](pyproject.toml),
  then `uv lock` locally to refresh `uv.lock` (commit it for reproducible builds).
- **Hot reload on Windows** relies on file-watch polling
  (`WATCHFILES_FORCE_POLLING`, Vite `usePolling`) — already configured.
- **Ollama from a container** is reachable at `http://host.docker.internal:11434/v1`,
  not `localhost`. See the comment in [.env.example](.env.example).
- **Docker socket**: the backend mounts `/var/run/docker.sock` so the sandbox pool
  can spawn containers. This is a dev convenience with real privilege; harden for
  production (remote/rootless daemon or gVisor — FINAL_ARCHITECTURE.md §4.3).

## Layout

```
backend/        FastAPI app (Dockerfile + main.py scaffold)
frontend/       Vite + React app
sandbox/        Dockerfile.python — hardened execution image
docker-compose.yml
pyproject.toml  uv-managed Python deps
```
