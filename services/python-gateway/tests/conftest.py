"""Shared pytest fixtures for the gateway test suite."""

from __future__ import annotations

import pytest


@pytest.fixture
async def fake_redis():
    """Provide an in-memory async Redis client (fakeredis).

    Used by cache and rate-limiter tests so they run without a real Redis
    server. The client is closed on teardown to avoid leaking connections.
    """
    from fakeredis.aioredis import FakeRedis

    client = FakeRedis()
    try:
        yield client
    finally:
        await client.aclose()
