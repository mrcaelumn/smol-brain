"""Distributed token-bucket rate limiter backed by Redis.

The algorithm is implemented as a single atomic Lua script executed on the
Redis server. Atomicity matters: with hundreds of concurrent workers, a
read-modify-write done in Python would race and leak capacity. Running the
whole check-and-decrement inside Redis guarantees correctness cluster-wide and
costs exactly one round-trip per request.

Each client (identified by API key, falling back to client IP) gets its own
bucket. Buckets are refilled lazily based on elapsed wall-clock time, so idle
clients accrue burst capacity up to ``capacity`` and no background sweeper is
needed. A TTL on the bucket key reclaims memory for clients that go silent.
"""

from __future__ import annotations

import time

import redis.asyncio as aioredis

# KEYS[1] = bucket key
# ARGV[1] = capacity (max tokens)         ARGV[2] = refill rate (tokens/sec)
# ARGV[3] = now (seconds, float)          ARGV[4] = requested tokens
# ARGV[5] = key TTL (seconds)
# Returns: {allowed (1|0), remaining_tokens, retry_after_seconds}
_TOKEN_BUCKET_LUA = """
local capacity   = tonumber(ARGV[1])
local refill     = tonumber(ARGV[2])
local now        = tonumber(ARGV[3])
local requested  = tonumber(ARGV[4])
local ttl        = tonumber(ARGV[5])

local bucket = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(bucket[1])
local ts     = tonumber(bucket[2])

if tokens == nil then
    tokens = capacity
    ts = now
end

-- Lazily refill based on elapsed time, capped at capacity.
local elapsed = math.max(0, now - ts)
tokens = math.min(capacity, tokens + (elapsed * refill))

local allowed = 0
local retry_after = 0
if tokens >= requested then
    allowed = 1
    tokens = tokens - requested
else
    -- Time until enough tokens accumulate for this request.
    retry_after = (requested - tokens) / refill
end

redis.call('HMSET', KEYS[1], 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', KEYS[1], ttl)

return { allowed, tokens, retry_after }
"""


class RateLimitResult:
    """Outcome of a single rate-limit check."""

    __slots__ = ("allowed", "remaining", "retry_after_s")

    def __init__(self, allowed: bool, remaining: float, retry_after_s: float) -> None:
        self.allowed = allowed
        self.remaining = remaining
        self.retry_after_s = retry_after_s


class TokenBucketRateLimiter:
    """Async token-bucket limiter using a server-side atomic Lua script."""

    def __init__(
        self,
        client: aioredis.Redis,
        capacity: int,
        refill_per_second: float,
        key_prefix: str = "rl",
    ) -> None:
        self._client = client
        self._capacity = capacity
        self._refill = refill_per_second
        self._prefix = key_prefix
        # ``register_script`` uses EVALSHA with automatic fallback to EVAL.
        self._script = client.register_script(_TOKEN_BUCKET_LUA)
        # Reclaim a bucket once a full refill cycle of idleness has passed.
        self._ttl = max(60, int(capacity / refill_per_second) + 60)

    async def acquire(self, identity: str, tokens: int = 1) -> RateLimitResult:
        """Attempt to consume ``tokens`` from ``identity``'s bucket."""
        key = f"{self._prefix}:{identity}"
        allowed, remaining, retry_after = await self._script(
            keys=[key],
            args=[
                self._capacity,
                self._refill,
                time.time(),
                tokens,
                self._ttl,
            ],
        )
        return RateLimitResult(
            allowed=bool(allowed),
            remaining=float(remaining),
            retry_after_s=float(retry_after),
        )
