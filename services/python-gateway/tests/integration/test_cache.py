"""Integration tests for the Redis-backed cache manager.

We focus on the lifecycle/health logic. The optional semantic cache (which
pulls in ``redisvl``/embeddings) is intentionally left disabled here.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.services.cache import CacheManager


def test_client_property_raises_before_connect() -> None:
    manager = CacheManager(Settings(cache_enabled=False))
    with pytest.raises(RuntimeError):
        _ = manager.client


async def test_healthy_returns_true_with_live_client(fake_redis) -> None:
    manager = CacheManager(Settings(cache_enabled=False))
    manager._client = fake_redis  # inject in-memory client
    assert await manager.healthy() is True


async def test_healthy_returns_false_on_ping_failure() -> None:
    manager = CacheManager(Settings(cache_enabled=False))

    class _BrokenClient:
        async def ping(self) -> bool:
            raise ConnectionError("redis unreachable")

    manager._client = _BrokenClient()
    assert await manager.healthy() is False
