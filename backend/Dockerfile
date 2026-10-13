# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
WORKDIR /app

FROM base AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Development image: adds dev dependencies, source is bind mounted by compose.
FROM builder AS dev
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen
ENV PATH=/opt/venv/bin:$PATH
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 libpq5 curl \
    && rm -rf /var/lib/apt/lists/*
CMD ["./start.sh"]

FROM base AS runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder --chown=app:app /app /app
ENV PATH=/opt/venv/bin:$PATH \
    MALLOC_ARENA_MAX=2
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT:-8000}/api/v1/health" || exit 1
CMD ["./start.sh"]
