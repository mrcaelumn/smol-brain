"""Observability: structured logging and Prometheus metrics.

This package re-exports the logging helpers and metric objects so callers can
import everything from a single namespace (``app.observability``) regardless of
which submodule a symbol physically lives in.
"""

from app.observability.logging import configure_logging, get_logger
from app.observability.metrics import (
    CACHE_EVENTS,
    CIRCUIT_STATE,
    IN_FLIGHT,
    RATE_LIMITED,
    REGISTRY,
    REQUEST_COUNT,
    REQUEST_LATENCY,
    UPSTREAM_ERRORS,
    status_class,
)

__all__ = [
    "CACHE_EVENTS",
    "CIRCUIT_STATE",
    "IN_FLIGHT",
    "RATE_LIMITED",
    "REGISTRY",
    "REQUEST_COUNT",
    "REQUEST_LATENCY",
    "UPSTREAM_ERRORS",
    "configure_logging",
    "get_logger",
    "status_class",
]
