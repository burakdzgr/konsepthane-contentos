# syntax=docker/dockerfile:1
# One backend image reused by the api, migrate, and worker services.

FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependency layer first so application edits do not invalidate it.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations
RUN uv sync --frozen --no-dev


FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

RUN groupadd --system contentos && useradd --system --gid contentos --no-create-home contentos

WORKDIR /app
COPY --from=builder --chown=contentos:contentos /app /app

USER contentos

EXPOSE 8000

CMD ["uvicorn", "contentos.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
