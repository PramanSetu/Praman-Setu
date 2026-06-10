# PatchMind backend — FastAPI + uvicorn, dependencies managed by uv (no venv/pip).
# Uses the official uv image so `uv` is preinstalled.
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    # Windows + Docker bind mounts don't deliver native file events; poll instead
    # so `uvicorn --reload` actually picks up changes.
    WATCHFILES_FORCE_POLLING=true

WORKDIR /app

# --- Dependency layer (cached unless pyproject/lock change) ---
# Copy only the metadata first so Docker can cache the install layer.
COPY pyproject.toml ./
COPY uv.loc[k] ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync

# --- Application code ---
# In dev this is overlaid by the bind mount in docker-compose.yml, but copying it
# here keeps the image runnable standalone.
COPY backend/ ./backend/

EXPOSE 8000

# .venv is on PATH, so call uvicorn directly (no `uv run` re-check on each start).
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
