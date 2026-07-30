# Built on the Mac Studio itself (arm64). The development machine is Windows
# on x86, so there is no cross-platform build or registry in the loop for a
# single-node deployment. See docs/architecture/deployment.md section 9.
FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.5.14 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Dependencies first so that application edits do not invalidate this layer.
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev --no-install-project 2>/dev/null || uv sync --no-dev --no-install-project

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

ENV PATH="/app/.venv/bin:$PATH"

# Runs unprivileged. The image carries no shell tooling the application needs,
# and nothing here writes to the filesystem outside /tmp — except the document
# store, whose mountpoint is created here *owned by nexus* so that Docker's
# volume initialization copies that ownership onto the fresh `documents`
# volume. Without this the volume comes up root-owned and every upload dies
# with EACCES, because nothing else in a rootless service can chown it.
RUN useradd --create-home --uid 10001 nexus && chown -R nexus:nexus /app \
    && mkdir -p /var/lib/nexus/documents && chown -R nexus:nexus /var/lib/nexus
USER nexus

EXPOSE 8000

# Overridden per service in docker-compose.yml: one image serves the gateway
# and both admin entrances, differing only in which ASGI app is mounted.
CMD ["uvicorn", "app.infrastructure.main_gateway:app", "--host", "0.0.0.0", "--port", "8000"]
