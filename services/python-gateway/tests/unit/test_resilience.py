"""Unit tests for the circuit breaker and retry policy."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.core.config import Settings
from app.core.resilience import (
    AsyncCircuitBreaker,
    CircuitOpenError,
    CircuitState,
    build_retryer,
)


async def _raise_connect_error() -> None:
    raise httpx.ConnectError("upstream down")


async def _succeed() -> str:
    return "ok"


# --- Circuit breaker ---------------------------------------------------------
async def test_breaker_starts_closed() -> None:
    breaker = AsyncCircuitBreaker(fail_max=3, reset_timeout_s=1.0)
    assert breaker.state is CircuitState.CLOSED


async def test_breaker_opens_after_threshold() -> None:
    breaker = AsyncCircuitBreaker(fail_max=2, reset_timeout_s=10.0)
    for _ in range(2):
        with pytest.raises(httpx.ConnectError):
            await breaker.call(_raise_connect_error)
    assert breaker.state is CircuitState.OPEN


async def test_open_breaker_fails_fast() -> None:
    breaker = AsyncCircuitBreaker(fail_max=1, reset_timeout_s=10.0)
    with pytest.raises(httpx.ConnectError):
        await breaker.call(_raise_connect_error)
    # While OPEN, the factory must not be invoked at all.
    with pytest.raises(CircuitOpenError):
        await breaker.call(_succeed)


async def test_breaker_half_opens_then_closes_on_success() -> None:
    breaker = AsyncCircuitBreaker(fail_max=1, reset_timeout_s=0.05)
    with pytest.raises(httpx.ConnectError):
        await breaker.call(_raise_connect_error)
    assert breaker.state is CircuitState.OPEN

    await asyncio.sleep(0.06)  # let the cool-down elapse
    result = await breaker.call(_succeed)  # probe succeeds
    assert result == "ok"
    assert breaker.state is CircuitState.CLOSED


async def test_breaker_reopens_on_half_open_failure() -> None:
    breaker = AsyncCircuitBreaker(fail_max=1, reset_timeout_s=0.05)
    with pytest.raises(httpx.ConnectError):
        await breaker.call(_raise_connect_error)

    await asyncio.sleep(0.06)
    with pytest.raises(httpx.ConnectError):
        await breaker.call(_raise_connect_error)  # probe fails
    assert breaker.state is CircuitState.OPEN


async def test_non_retryable_error_does_not_trip_breaker() -> None:
    breaker = AsyncCircuitBreaker(fail_max=1, reset_timeout_s=10.0)

    async def _value_error() -> None:
        raise ValueError("logic bug, not a transport fault")

    with pytest.raises(ValueError):
        await breaker.call(_value_error)
    assert breaker.state is CircuitState.CLOSED


# --- Retryer -----------------------------------------------------------------
async def test_retryer_recovers_after_transient_failures() -> None:
    settings = Settings(
        retry_max_attempts=3,
        retry_initial_backoff_s=0.001,
        retry_max_backoff_s=0.002,
    )
    retryer = build_retryer(settings)
    attempts = {"count": 0}

    async def _flaky() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise httpx.ConnectError("blip")
        return "done"

    result = None
    async for attempt in retryer:
        with attempt:
            result = await _flaky()

    assert result == "done"
    assert attempts["count"] == 3


async def test_retryer_reraises_after_exhausting_attempts() -> None:
    settings = Settings(
        retry_max_attempts=2,
        retry_initial_backoff_s=0.001,
        retry_max_backoff_s=0.002,
    )
    retryer = build_retryer(settings)

    with pytest.raises(httpx.ConnectError):
        async for attempt in retryer:
            with attempt:
                await _raise_connect_error()
