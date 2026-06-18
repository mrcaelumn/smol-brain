"""Integration tests for the Redis token-bucket rate limiter.

These exercise the actual Lua script against an in-memory Redis (fakeredis).
fakeredis evaluates Lua via ``lupa``; if that optional dependency is missing
the whole module is skipped rather than failing.
"""

from __future__ import annotations

import pytest

pytest.importorskip("lupa", reason="fakeredis Lua scripting requires lupa")

from app.services.rate_limit import TokenBucketRateLimiter  # noqa: E402


async def test_first_request_is_allowed(fake_redis) -> None:
    limiter = TokenBucketRateLimiter(fake_redis, capacity=5, refill_per_second=1.0)
    result = await limiter.acquire("client-a")
    assert result.allowed is True
    assert result.remaining <= 5


async def test_bucket_drains_and_blocks(fake_redis) -> None:
    # Negligible refill so the bucket cannot recover during the test.
    limiter = TokenBucketRateLimiter(
        fake_redis, capacity=2, refill_per_second=0.0001
    )
    assert (await limiter.acquire("client-b")).allowed is True
    assert (await limiter.acquire("client-b")).allowed is True

    blocked = await limiter.acquire("client-b")
    assert blocked.allowed is False
    assert blocked.retry_after_s > 0


async def test_buckets_are_isolated_per_identity(fake_redis) -> None:
    limiter = TokenBucketRateLimiter(
        fake_redis, capacity=1, refill_per_second=0.0001
    )
    assert (await limiter.acquire("alice")).allowed is True
    # Alice is now exhausted, but Bob has a fresh bucket.
    assert (await limiter.acquire("alice")).allowed is False
    assert (await limiter.acquire("bob")).allowed is True
