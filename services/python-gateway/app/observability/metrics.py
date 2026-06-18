"""Prometheus metrics definitions.

Metrics are registered once at import time against a dedicated registry, which
keeps gateway metrics isolated from any library defaults and makes them easy to
reset in tests. The registry is exported via the ``/metrics`` endpoint.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

# A dedicated registry keeps gateway metrics isolated and testable.
REGISTRY = CollectorRegistry(auto_describe=True)

# --- HTTP-level metrics ------------------------------------------------------
REQUEST_LATENCY = Histogram(
    "gateway_request_latency_seconds",
    "End-to-end request latency in seconds.",
    labelnames=("method", "path", "status_class"),
    # Buckets tuned for LLM workloads (sub-ms cache hits .. multi-second gen).
    buckets=(0.005, 0.025, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
    registry=REGISTRY,
)
REQUEST_COUNT = Counter(
    "gateway_requests_total",
    "Total HTTP requests by method, path and status class.",
    labelnames=("method", "path", "status_class"),
    registry=REGISTRY,
)
IN_FLIGHT = Gauge(
    "gateway_in_flight_requests",
    "Number of requests currently being processed.",
    registry=REGISTRY,
)

# --- Domain metrics ----------------------------------------------------------
CACHE_EVENTS = Counter(
    "gateway_cache_events_total",
    "Cache lookups by layer and outcome.",
    labelnames=("layer", "outcome"),  # layer: exact|semantic, outcome: hit|miss
    registry=REGISTRY,
)
RATE_LIMITED = Counter(
    "gateway_rate_limited_total",
    "Requests rejected by the rate limiter.",
    registry=REGISTRY,
)
UPSTREAM_ERRORS = Counter(
    "gateway_upstream_errors_total",
    "Errors talking to the vLLM upstream, by category.",
    labelnames=("kind",),  # timeout|connection|http_status|circuit_open
    registry=REGISTRY,
)
CIRCUIT_STATE = Gauge(
    "gateway_circuit_state",
    "Upstream circuit breaker state (0=closed, 1=open, 2=half_open).",
    registry=REGISTRY,
)


def status_class(status_code: int) -> str:
    """Bucket an HTTP status code into a low-cardinality class label."""
    return f"{status_code // 100}xx"
