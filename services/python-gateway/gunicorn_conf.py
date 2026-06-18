"""Gunicorn configuration for the smol-brain gateway.

Gunicorn acts as a robust process manager (pre-fork master) supervising
multiple Uvicorn async workers. Each worker runs its own event loop and owns
its own Redis/HTTP connection pools and circuit breaker.

Sizing guidance for an I/O-bound async gateway: because workers spend almost
all their time awaiting the GPU upstream, ``workers = 2 * CPU + 1`` is a sane
default. The real concurrency lever is per-worker async tasks (effectively
unbounded by the event loop), gated by the connection-pool limits in config.
"""

from __future__ import annotations

import multiprocessing
import os


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# --- Socket ------------------------------------------------------------------
bind = os.environ.get("GATEWAY_BIND", "0.0.0.0:8080")

# --- Worker processes --------------------------------------------------------
workers = _int_env("GATEWAY_WORKERS", multiprocessing.cpu_count() * 2 + 1)
worker_class = "uvicorn.workers.UvicornWorker"
# Recycle workers periodically to bound memory growth; jitter avoids a
# thundering-herd restart across all workers at once.
max_requests = _int_env("GATEWAY_MAX_REQUESTS", 10_000)
max_requests_jitter = _int_env("GATEWAY_MAX_REQUESTS_JITTER", 1_000)

# --- Timeouts ----------------------------------------------------------------
# Streaming generations are long-lived; keep the worker timeout generous and
# rely on the upstream httpx read timeout for true hangs.
timeout = _int_env("GATEWAY_WORKER_TIMEOUT", 180)
graceful_timeout = _int_env("GATEWAY_GRACEFUL_TIMEOUT", 30)
keepalive = _int_env("GATEWAY_KEEPALIVE", 5)

# --- Logging -----------------------------------------------------------------
# App logs are JSON via structlog; let access logs flow to stdout too.
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GATEWAY_LOG_LEVEL", "info").lower()
