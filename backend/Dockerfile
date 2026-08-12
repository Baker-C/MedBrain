# Lean serve container: the FastAPI query side only — no extraction bulk (Build-Spec §9).
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Put the synced venv on PATH so uvicorn is called directly rather than through
# `uv run`, which would sit between the container and its process as an extra parent.
ENV PATH="/app/.venv/bin:$PATH"

COPY . .

EXPOSE 8000
# Shell form so $PORT expands — Render injects the port to bind, and the exec form
# would hand uvicorn the literal string "$PORT". `exec` then replaces the shell, so
# uvicorn is PID 1 and receives the SIGTERM Render sends to drain a deploy.
CMD exec uvicorn api.app:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}
