"""Unit tests for auth and rate-limit FastAPI dependencies."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.dependencies import (
    _client_identity,
    _constant_time_match,
    enforce_rate_limit,
    require_api_key,
)
from app.core.config import Settings
from app.services.rate_limit import RateLimitResult


def _fake_request(host: str = "203.0.113.7") -> SimpleNamespace:
    """A minimal stand-in for starlette.Request with a ``client.host``."""
    return SimpleNamespace(client=SimpleNamespace(host=host))


# --- Authentication ----------------------------------------------------------
async def test_auth_disabled_returns_anonymous() -> None:
    settings = Settings(api_keys=[])
    assert await require_api_key(settings=settings, x_api_key=None) == "anonymous"


async def test_auth_accepts_valid_key() -> None:
    settings = Settings(api_keys=["secret", "other"])
    assert await require_api_key(settings=settings, x_api_key="secret") == "secret"


async def test_auth_rejects_invalid_key() -> None:
    settings = Settings(api_keys=["secret"])
    with pytest.raises(HTTPException) as exc_info:
        await require_api_key(settings=settings, x_api_key="wrong")
    assert exc_info.value.status_code == 401


async def test_auth_rejects_missing_key() -> None:
    settings = Settings(api_keys=["secret"])
    with pytest.raises(HTTPException) as exc_info:
        await require_api_key(settings=settings, x_api_key=None)
    assert exc_info.value.status_code == 401


def test_constant_time_match() -> None:
    assert _constant_time_match("a", ["a", "b"]) is True
    assert _constant_time_match("z", ["a", "b"]) is False
    assert _constant_time_match("a", []) is False


# --- Identity derivation -----------------------------------------------------
def test_identity_uses_api_key_when_authenticated() -> None:
    assert _client_identity(_fake_request(), "mykey") == "key:mykey"


def test_identity_falls_back_to_ip_when_anonymous() -> None:
    assert _client_identity(_fake_request("10.0.0.1"), "anonymous") == "ip:10.0.0.1"


# --- Rate limiting -----------------------------------------------------------
class _AllowLimiter:
    async def acquire(self, identity: str, tokens: int = 1) -> RateLimitResult:
        return RateLimitResult(allowed=True, remaining=5.0, retry_after_s=0.0)


class _BlockLimiter:
    async def acquire(self, identity: str, tokens: int = 1) -> RateLimitResult:
        return RateLimitResult(allowed=False, remaining=0.0, retry_after_s=3.2)


async def test_rate_limit_passthrough_when_disabled() -> None:
    settings = Settings(rate_limit_enabled=False)
    result = await enforce_rate_limit(
        request=_fake_request(),
        settings=settings,
        api_key="k",
        limiter=_AllowLimiter(),
    )
    assert result == "k"


async def test_rate_limit_allows_within_budget() -> None:
    settings = Settings(rate_limit_enabled=True)
    result = await enforce_rate_limit(
        request=_fake_request(),
        settings=settings,
        api_key="k",
        limiter=_AllowLimiter(),
    )
    assert result == "k"


async def test_rate_limit_blocks_when_exhausted() -> None:
    settings = Settings(rate_limit_enabled=True)
    with pytest.raises(HTTPException) as exc_info:
        await enforce_rate_limit(
            request=_fake_request(),
            settings=settings,
            api_key="k",
            limiter=_BlockLimiter(),
        )
    assert exc_info.value.status_code == 429
    # 3.2s rounds to a 3s Retry-After hint.
    assert exc_info.value.headers["Retry-After"] == "3"
