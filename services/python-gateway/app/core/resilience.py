"""Resilience primitives for the upstream vLLM connection.

Two patterns are combined:

* **Exponential backoff retry** (via ``tenacity``) absorbs transient blips —
  a momentary connection reset or a single ``503`` while vLLM reschedules.
* **Circuit breaker** prevents retry storms from hammering an upstream that is
  genuinely unhealthy (e.g. GPU OOM / thrashing). When the failure threshold is
  crossed the circuit *opens* and requests fail fast for a cool-down window,
  then *half-opens* to probe recovery with a single trial request.
"""

from __future__ import annotations

import asyncio
import time
from enum import IntEnum

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import Settings
from app.observability import CIRCUIT_STATE, UPSTREAM_ERRORS, get_logger

logger = get_logger(__name__)


class CircuitState(IntEnum):
    """Circuit breaker states (values match the ``gateway_circuit_state`` gauge)."""

    CLOSED = 0
    OPEN = 1
    HALF_OPEN = 2


class CircuitOpenError(RuntimeError):
    """Raised when a call is short-circuited because the breaker is open."""


# Exceptions considered "transient" and therefore worth retrying / counting
# toward the breaker. Deterministic 4xx errors are intentionally excluded.
RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
    httpx.PoolTimeout,
)


class AsyncCircuitBreaker:
    """A minimal, thread-safe-per-event-loop async circuit breaker.

    The implementation is intentionally dependency-free and uses an
    ``asyncio.Lock`` to serialise state transitions, which is sufficient for a
    single-process worker. Each Gunicorn worker owns its own breaker instance.
    """

    def __init__(self, fail_max: int, reset_timeout_s: float) -> None:
        self._fail_max = fail_max
        self._reset_timeout_s = reset_timeout_s
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at = 0.0
        self._lock = asyncio.Lock()
        CIRCUIT_STATE.set(self._state)

    @property
    def state(self) -> CircuitState:
        return self._state

    async def _transition(self, new_state: CircuitState) -> None:
        if new_state != self._state:
            logger.info(
                "circuit_breaker_transition",
                from_state=self._state.name,
                to_state=new_state.name,
            )
        self._state = new_state
        CIRCUIT_STATE.set(new_state)

    async def _before_call(self) -> None:
        """Decide whether a call may proceed, mutating state as required."""
        async with self._lock:
            if self._state is CircuitState.OPEN:
                elapsed = time.monotonic() - self._opened_at
                if elapsed >= self._reset_timeout_s:
                    # Cool-down elapsed: allow a single probe request.
                    await self._transition(CircuitState.HALF_OPEN)
                else:
                    UPSTREAM_ERRORS.labels(kind="circuit_open").inc()
                    raise CircuitOpenError(
                        "Upstream circuit is open; failing fast."
                    )

    async def _on_success(self) -> None:
        async with self._lock:
            self._failure_count = 0
            if self._state is not CircuitState.CLOSED:
                await self._transition(CircuitState.CLOSED)

    async def _on_failure(self) -> None:
        async with self._lock:
            self._failure_count += 1
            # A failed probe in HALF_OPEN, or crossing the threshold while
            # CLOSED, opens (or re-opens) the circuit.
            if (
                self._state is CircuitState.HALF_OPEN
                or self._failure_count >= self._fail_max
            ):
                self._opened_at = time.monotonic()
                await self._transition(CircuitState.OPEN)

    async def call(self, awaitable_factory):
        """Execute ``awaitable_factory()`` under breaker protection.

        ``awaitable_factory`` is a zero-arg callable returning a coroutine, so
        the breaker can invoke it fresh on each (post-retry) attempt.
        """
        await self._before_call()
        try:
            result = await awaitable_factory()
        except RETRYABLE_EXCEPTIONS:
            await self._on_failure()
            raise
        except Exception:
            # Non-retryable errors (e.g. client 4xx) shouldn't trip the breaker.
            raise
        else:
            await self._on_success()
            return result


def build_retryer(settings: Settings) -> AsyncRetrying:
    """Create a configured ``tenacity`` async retry controller."""
    return AsyncRetrying(
        stop=stop_after_attempt(settings.retry_max_attempts),
        wait=wait_exponential(
            multiplier=settings.retry_initial_backoff_s,
            max=settings.retry_max_backoff_s,
        ),
        retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
        reraise=True,
    )
