"""ASGI middleware for request context, structured access logs and metrics.

A single middleware handles three concerns that must wrap every request:

* assigning/propagating a request id (echoed via ``X-Request-ID``),
* recording Prometheus latency/count/in-flight metrics,
* emitting a structured access log line — without any request body content.
"""

from __future__ import annotations

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.observability import (
    IN_FLIGHT,
    REQUEST_COUNT,
    REQUEST_LATENCY,
    get_logger,
    status_class,
)

logger = get_logger(__name__)

# Paths excluded from access logging to avoid flooding logs with probe noise.
_QUIET_PATHS = frozenset({"/healthz", "/readyz", "/metrics"})


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Bind request context and emit metrics/logs around each request."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        # Bind to contextvars so every log line in this request carries the id.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        # Use the route template (e.g. "/v1/chat") rather than the raw path to
        # keep metric label cardinality bounded.
        metric_path = request.url.path
        is_quiet = metric_path in _QUIET_PATHS

        start = time.perf_counter()
        IN_FLIGHT.inc()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            elapsed = time.perf_counter() - start
            IN_FLIGHT.dec()
            cls = status_class(status_code)
            labels = (request.method, metric_path, cls)
            REQUEST_LATENCY.labels(*labels).observe(elapsed)
            REQUEST_COUNT.labels(*labels).inc()
            if not is_quiet:
                logger.info(
                    "request_completed",
                    status_code=status_code,
                    duration_ms=round(elapsed * 1000, 2),
                )
