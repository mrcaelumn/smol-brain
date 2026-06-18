"""FastAPI dependencies: shared singletons, authentication and rate limiting.

Heavyweight, pool-backed objects (Redis, the LLM service, the rate limiter)
are created once during the lifespan startup and stored on ``app.state``. The
dependency functions here simply hand those singletons to route handlers and
enforce cross-cutting policy (auth, throttling) before the handler runs.
"""

from __future__ import annotations

import hmac

from fastapi import Depends, Header, HTTPException, Request, status

from app.core.config import Settings, get_settings
from app.observability import RATE_LIMITED, get_logger
from app.services.cache import CacheManager
from app.services.llm import LLMService
from app.services.rate_limit import TokenBucketRateLimiter

logger = get_logger(__name__)


# --- Singleton accessors -----------------------------------------------------
def get_cache_manager(request: Request) -> CacheManager:
    """Return the process-wide ``CacheManager`` from application state."""
    return request.app.state.cache_manager


def get_llm_service(request: Request) -> LLMService:
    """Return the process-wide ``LLMService`` from application state."""
    return request.app.state.llm_service


def get_rate_limiter(request: Request) -> TokenBucketRateLimiter:
    """Return the process-wide rate limiter from application state."""
    return request.app.state.rate_limiter


# --- Authentication ----------------------------------------------------------
def _constant_time_match(candidate: str, valid_keys: list[str]) -> bool:
    """Compare ``candidate`` against valid keys in constant time.

    ``hmac.compare_digest`` avoids leaking key length / prefix information via
    timing side channels. We iterate all keys so the work is independent of
    which (if any) key matched.
    """
    matched = False
    for key in valid_keys:
        if hmac.compare_digest(candidate, key):
            matched = True
    return matched


async def require_api_key(
    settings: Settings = Depends(get_settings),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> str:
    """Validate the API key header.

    Returns the caller's identity (the key) for downstream use such as
    per-client rate limiting. When no keys are configured (local dev only),
    auth is skipped and a sentinel identity is returned.
    """
    if not settings.auth_enabled:
        return "anonymous"

    if not x_api_key or not _constant_time_match(x_api_key, settings.api_keys):
        # Do not echo the supplied key; log only the failure event.
        logger.warning("auth_failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
            headers={"WWW-Authenticate": settings.api_key_header},
        )
    return x_api_key


# --- Rate limiting -----------------------------------------------------------
def _client_identity(request: Request, api_key: str) -> str:
    """Derive a stable rate-limit identity for the caller.

    Authenticated callers are limited per API key. Anonymous (local) callers
    fall back to the connecting client host. We avoid trusting forwarded
    headers blindly — the load balancer should set the real client address.
    """
    if api_key != "anonymous":
        return f"key:{api_key}"
    client_host = request.client.host if request.client else "unknown"
    return f"ip:{client_host}"


async def enforce_rate_limit(
    request: Request,
    settings: Settings = Depends(get_settings),
    api_key: str = Depends(require_api_key),
    limiter: TokenBucketRateLimiter = Depends(get_rate_limiter),
) -> str:
    """Reject the request with 429 if the caller has exhausted their bucket."""
    if not settings.rate_limit_enabled:
        return api_key

    identity = _client_identity(request, api_key)
    result = await limiter.acquire(identity)
    if not result.allowed:
        RATE_LIMITED.inc()
        retry_after = max(1, int(round(result.retry_after_s)))
        logger.info("rate_limited", identity=identity, retry_after_s=retry_after)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Slow down.",
            headers={"Retry-After": str(retry_after)},
        )
    return api_key
