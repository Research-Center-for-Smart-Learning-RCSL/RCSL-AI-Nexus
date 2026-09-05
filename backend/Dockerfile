# Built on the Mac Studio itself (arm64). The development machine is Windows
# on x86, so there is no cross-platform build or registry in the loop for a
# single-node deployment. See docs/architecture/deployment.md section 9.

# --- Stage 1: Build the Rust extension ---
FROM python:3.12-slim AS rust-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential pkg-config libssl-dev \
    && rm -rf /var/lib/apt/lists/*

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
ENV PATH="/root/.cargo/bin:$PATH"

RUN pip install --no-cache-dir maturin

WORKDIR /build
COPY native/ ./native/
RUN cd native && maturin build --release --out /wheels

# --- Stage 2: Application ---
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

# Install the Rust extension wheel built in stage 1.
COPY --from=rust-builder /wheels/*.whl /tmp/wheels/
RUN uv pip install /tmp/wheels/*.whl && rm -rf /tmp/wheels

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

# The Windows operator tools, so that /admin/client-tools serves the revision
# this image was built from rather than sending operators to a GitHub branch.
# They arrive through a named build context (`client_tools`, wired in
# docker-compose.yml) because their home is scripts/windows/codex-app at the
# repository root, which is outside this image's build context, and one copy of
# them is the point.
#
# `docker build ./backend` on its own will not resolve that context and will
# fail here. Build through Compose, which supplies it. The endpoint's 503 is for
# the different case of an image whose layout has moved, not for this one.
COPY --from=client_tools windows/codex-app ./client-tools/windows/codex-app

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
