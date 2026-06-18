"""Centralised application configuration.

All runtime configuration is loaded from environment variables (or an optional
``.env`` file) via Pydantic ``BaseSettings``. This keeps the twelve-factor
contract intact: the same image runs in every environment, behaviour is driven
purely by configuration, and secrets never live in code.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, RedisDsn, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application settings.

    Values are validated at startup; an invalid configuration fails fast rather
    than surfacing as a confusing runtime error under load.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="GATEWAY_",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Service metadata ----------------------------------------------------
    service_name: str = "smol-brain-gateway"
    environment: Literal["local", "dev", "staging", "production"] = "production"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # --- vLLM upstream -------------------------------------------------------
    # Internal cluster URL of the vLLM OpenAI-compatible server (sidecar or
    # dedicated GPU pool). Keep this on the private network — never public.
    vllm_base_url: str = "http://smol-brain:8000/v1"
    # vLLM ignores the key, but the OpenAI client requires a non-empty value.
    vllm_api_key: str = "not-needed"
    model_name: str = "Qwen/Qwen3.5-2B"

    # Generation defaults (callers may override within validated bounds).
    default_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    default_max_tokens: int = Field(default=1024, ge=1, le=32_768)

    # --- Upstream HTTP client / connection pooling ---------------------------
    http_max_connections: int = Field(default=1000, ge=1)
    http_max_keepalive_connections: int = Field(default=200, ge=1)
    http_connect_timeout_s: float = Field(default=5.0, gt=0)
    # Long read timeout: token generation streams can run for many seconds.
    http_read_timeout_s: float = Field(default=120.0, gt=0)

    # --- Redis ---------------------------------------------------------------
    redis_url: RedisDsn = Field(default="redis://redis:6379/0")
    redis_max_connections: int = Field(default=200, ge=1)
    redis_socket_timeout_s: float = Field(default=2.0, gt=0)

    # --- Caching -------------------------------------------------------------
    cache_enabled: bool = True
    # TTL for exact-match LLM response cache. Bounds memory growth.
    cache_ttl_s: int = Field(default=3600, ge=1)

    semantic_cache_enabled: bool = False
    # Cosine-distance threshold below which a cached answer is reused.
    semantic_cache_distance_threshold: float = Field(default=0.1, ge=0.0, le=1.0)
    semantic_cache_ttl_s: int = Field(default=3600, ge=1)
    # OpenAI-compatible embeddings endpoint (e.g. a small embedding model served
    # by vLLM or TEI). Used only when semantic caching is enabled.
    embeddings_base_url: str = "http://smol-brain:8000/v1"
    embeddings_api_key: str = "not-needed"
    embeddings_model: str = "intfloat/e5-small-v2"

    # --- Rate limiting (token bucket, per API key) ---------------------------
    rate_limit_enabled: bool = True
    rate_limit_capacity: int = Field(default=120, ge=1)  # bucket size (burst)
    rate_limit_refill_per_second: float = Field(default=2.0, gt=0)  # steady rate

    # --- Resilience (circuit breaker + retry) --------------------------------
    retry_max_attempts: int = Field(default=3, ge=1)
    retry_initial_backoff_s: float = Field(default=0.25, gt=0)
    retry_max_backoff_s: float = Field(default=4.0, gt=0)
    circuit_breaker_fail_max: int = Field(default=5, ge=1)
    circuit_breaker_reset_timeout_s: float = Field(default=30.0, gt=0)

    # --- Security ------------------------------------------------------------
    # Comma-separated list of accepted API keys. MUST be supplied in
    # production; an empty list disables auth (only acceptable for local dev).
    # ``NoDecode`` disables pydantic-settings' default JSON parsing so the
    # validator below can accept a plain comma-separated string from the env.
    api_keys: Annotated[list[str], NoDecode] = Field(default_factory=list)
    api_key_header: str = "X-API-Key"
    # Comma-separated list of allowed CORS origins. Defaults to none (locked
    # down). Use explicit origins in production rather than "*".
    cors_allow_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    @field_validator("api_keys", "cors_allow_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Allow comma-separated env strings to populate list fields."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def auth_enabled(self) -> bool:
        """Auth is active whenever at least one API key is configured."""
        return bool(self.api_keys)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached ``Settings`` instance.

    ``lru_cache`` guarantees the environment is parsed exactly once, so the
    same immutable configuration object is shared across all workers' tasks.
    """
    return Settings()
