"""Redis connection pooling and LangChain cache initialisation.

This module owns three things:

1. A shared **async Redis connection pool** (``redis.asyncio``) reused for
   rate limiting and health checks. Pooling is critical at scale — opening a
   socket per request would exhaust file descriptors and add latency.
2. The **LangChain exact-match cache** (``RedisCache``) wired into LangChain's
   global cache so identical prompts skip the GPU entirely.
3. An optional **semantic cache** (``RedisSemanticCache``) that reuses answers
   for *similar* prompts using vector similarity — a big cost saver for
   paraphrased queries, gated behind a config toggle.

A small wrapper class manages lifecycle so ``main.py`` can construct and tear
everything down cleanly inside the lifespan handler.
"""

from __future__ import annotations

import redis.asyncio as aioredis
from langchain_core.caches import BaseCache
from langchain_core.globals import set_llm_cache

from app.core.config import Settings
from app.observability import get_logger

logger = get_logger(__name__)


class CacheManager:
    """Owns the Redis pool and any LangChain caches for the process lifetime."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pool: aioredis.ConnectionPool | None = None
        self._client: aioredis.Redis | None = None
        self._llm_cache: BaseCache | None = None

    # --- Lifecycle -----------------------------------------------------------
    async def connect(self) -> None:
        """Create the connection pool and initialise LangChain caches."""
        redis_url = str(self._settings.redis_url)
        self._pool = aioredis.ConnectionPool.from_url(
            redis_url,
            max_connections=self._settings.redis_max_connections,
            socket_timeout=self._settings.redis_socket_timeout_s,
            socket_connect_timeout=self._settings.redis_socket_timeout_s,
            health_check_interval=30,
            decode_responses=False,
        )
        self._client = aioredis.Redis(connection_pool=self._pool)
        # Fail fast if Redis is unreachable at boot.
        await self._client.ping()
        logger.info(
            "redis_connected",
            max_connections=self._settings.redis_max_connections,
        )

        if self._settings.cache_enabled:
            self._init_llm_cache(redis_url)

    async def close(self) -> None:
        """Gracefully close the client and drain the pool."""
        if self._client is not None:
            await self._client.aclose()
        if self._pool is not None:
            await self._pool.aclose()
        logger.info("redis_closed")

    # --- Accessors -----------------------------------------------------------
    @property
    def client(self) -> aioredis.Redis:
        """Return the shared async Redis client.

        Raises if accessed before ``connect`` — a programming error we want to
        surface loudly rather than mask.
        """
        if self._client is None:
            raise RuntimeError("CacheManager.connect() has not been called.")
        return self._client

    async def healthy(self) -> bool:
        """Lightweight readiness probe for Redis."""
        try:
            return bool(await self.client.ping())
        except Exception as exc:  # noqa: BLE001 - report any failure as unhealthy
            logger.warning("redis_health_check_failed", error=str(exc))
            return False

    # --- Internal ------------------------------------------------------------
    def _init_llm_cache(self, redis_url: str) -> None:
        """Wire LangChain's global LLM cache (exact, and optionally semantic).

        Imports are local so that an operator who disables caching never pays
        the import cost of the optional semantic-cache dependency tree.
        """
        if self._settings.semantic_cache_enabled:
            from langchain_community.cache import RedisSemanticCache
            from langchain_openai import OpenAIEmbeddings

            embeddings = OpenAIEmbeddings(
                base_url=self._settings.embeddings_base_url,
                api_key=self._settings.embeddings_api_key,
                model=self._settings.embeddings_model,
                check_embedding_ctx_length=False,
            )
            self._llm_cache = RedisSemanticCache(
                redis_url=redis_url,
                embedding=embeddings,
                score_threshold=self._settings.semantic_cache_distance_threshold,
                ttl=self._settings.semantic_cache_ttl_s,
            )
            logger.info(
                "semantic_cache_enabled",
                model=self._settings.embeddings_model,
                threshold=self._settings.semantic_cache_distance_threshold,
            )
        else:
            from langchain_community.cache import RedisCache

            # RedisCache uses a synchronous client internally; that is fine
            # because cache reads/writes are tiny and happen off the hot GPU
            # path. We give it its own short-lived client with a strict TTL.
            import redis as sync_redis

            sync_client = sync_redis.Redis.from_url(redis_url)
            self._llm_cache = RedisCache(
                redis_=sync_client,
                ttl=self._settings.cache_ttl_s,
            )
            logger.info("exact_cache_enabled", ttl_s=self._settings.cache_ttl_s)

        set_llm_cache(self._llm_cache)
