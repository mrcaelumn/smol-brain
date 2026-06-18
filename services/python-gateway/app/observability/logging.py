"""Structured logging configuration.

Logging is emitted as line-delimited JSON so it can be shipped to ELK/Loki
without a parsing stage.

Security note: we deliberately never log prompt or completion content. Only
structural metadata (token counts, latencies, cache outcomes) is recorded.
"""

from __future__ import annotations

import logging
import sys

import structlog

from app.core.config import Settings


def configure_logging(settings: Settings) -> None:
    """Configure structlog + stdlib logging to emit JSON to stdout."""
    log_level = getattr(logging, settings.log_level, logging.INFO)

    # Route stdlib logging (uvicorn, httpx, etc.) through stdout at the level.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(*args: object, **kwargs: object) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger."""
    return structlog.get_logger(*args, **kwargs)
