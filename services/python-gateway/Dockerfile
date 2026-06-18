# syntax=docker/dockerfile:1.7
# =============================================================================
# smol-brain gateway — multi-stage build
#   Stage 1 (builder): compile/install dependencies into an isolated venv.
#   Stage 2 (runtime):  copy only the venv + app, run as a non-root user.
# This keeps the final image small (no build toolchain) and hardened.
# =============================================================================

# ----------------------------------------------------------------------------
# Stage 1: builder
# ----------------------------------------------------------------------------
FROM python:3.12-slim AS builder

# Fail fast, no .pyc, unbuffered stdout, isolated venv on PATH.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /build

# Build deps only needed to compile wheels; not carried into runtime.
RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv "$VIRTUAL_ENV"

# Install dependencies first for optimal layer caching.
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip \
    && pip install -r requirements.txt

# ----------------------------------------------------------------------------
# Stage 2: runtime
# ----------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    GATEWAY_BIND=0.0.0.0:8080

# curl is used by the container healthcheck only.
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/* \
    # Create an unprivileged user/group to run the service.
    && groupadd --system --gid 10001 appuser \
    && useradd --system --uid 10001 --gid appuser --no-create-home appuser

WORKDIR /app

# Copy the pre-built virtualenv and application source.
COPY --from=builder /opt/venv /opt/venv
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser gunicorn_conf.py ./

USER appuser

EXPOSE 8080

# Liveness check mirrors the Kubernetes probe for parity in local/compose runs.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8080/healthz || exit 1

# Gunicorn master supervises Uvicorn async workers.
ENTRYPOINT ["gunicorn", "app.main:app", "-c", "gunicorn_conf.py"]
