"""FastAPI entrypoint: lifespan, middleware, security and routing.

This module wires the components together but keeps the heavy lifting in their
own packages (``app.core``, ``app.services``, ``app.api``). Long-lived
resources (Redis pool, HTTP client pool, rate limiter, LangChain caches) are
created once in the ``lifespan`` context and torn down cleanly on shutdown so
in-flight work drains and sockets are released — essential for zero-downtime
rolling deploys.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.middleware import ObservabilityMiddleware
from app.api.routes import api_router
from app.core.config import get_settings
from app.core.resilience import CircuitOpenError
from app.observability import configure_logging, get_logger
from app.schemas import ErrorResponse
from app.services.cache import CacheManager
from app.services.llm import LLMService
from app.services.rate_limit import TokenBucketRateLimiter

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup/shutdown of pooled resources for the worker process."""
    settings = get_settings()
    configure_logging(settings)
    logger.info("startup_begin", service=settings.service_name, version=__version__)

    cache_manager = CacheManager(settings)
    llm_service = LLMService(settings)

    # Establish all upstream connections before accepting traffic.
    await cache_manager.connect()
    await llm_service.connect()

    rate_limiter = TokenBucketRateLimiter(
        client=cache_manager.client,
        capacity=settings.rate_limit_capacity,
        refill_per_second=settings.rate_limit_refill_per_second,
    )

    # Publish singletons for dependency injection.
    app.state.settings = settings
    app.state.cache_manager = cache_manager
    app.state.llm_service = llm_service
    app.state.rate_limiter = rate_limiter

    logger.info("startup_complete")
    try:
        yield
    finally:
        # Graceful drain: close pools so no socket is leaked on shutdown.
        logger.info("shutdown_begin")
        await llm_service.close()
        await cache_manager.close()
        logger.info("shutdown_complete")


def create_app() -> FastAPI:
    """Application factory — keeps construction testable and import-safe."""
    settings = get_settings()

    app = FastAPI(
        title="smol-brain gateway",
        version=__version__,
        description="Async, cached, rate-limited LLM gateway over vLLM.",
        lifespan=lifespan,
        # Hide schema docs in production to reduce attack surface.
        docs_url=None if settings.environment == "production" else "/docs",
        redoc_url=None,
        openapi_url=None if settings.environment == "production" else "/openapi.json",
    )

    # Order matters: CORS outermost, then our observability wrapper.
    app.add_middleware(ObservabilityMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=bool(settings.cors_allow_origins),
        allow_methods=["GET", "POST"],
        allow_headers=[settings.api_key_header, "Content-Type", "X-Request-ID"],
        max_age=600,
    )

    app.include_router(api_router)
    _register_exception_handlers(app)
    return app


def _register_exception_handlers(app: FastAPI) -> None:
    """Centralised, structured error handling for unhandled failures."""

    @app.exception_handler(CircuitOpenError)
    async def _circuit_open_handler(
        request: Request, exc: CircuitOpenError
    ) -> JSONResponse:
        # Upstream is unhealthy; shed load fast with a retryable status.
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=ErrorResponse(
                error="upstream_unavailable",
                detail="The inference backend is temporarily unavailable.",
                request_id=request.headers.get("X-Request-ID"),
            ).model_dump(),
            headers={"Retry-After": "5"},
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        # Never leak internal exception details to the caller.
        logger.error("unhandled_exception", error=str(exc), exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=ErrorResponse(
                error="internal_error",
                detail="An unexpected error occurred.",
                request_id=request.headers.get("X-Request-ID"),
            ).model_dump(),
        )


# Module-level ASGI app for Gunicorn/Uvicorn (``app.main:app``).
app = create_app()
