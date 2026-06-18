"""LangChain ChatOpenAI client targeting the vLLM OpenAI-compatible server.

We use ``langchain_openai.ChatOpenAI`` rather than the ``VLLM`` class because
vLLM exposes an OpenAI-compatible HTTP API; pointing ``ChatOpenAI`` at the
internal ``/v1`` URL gives us streaming, async, and LangChain's global cache
integration for free, while keeping the GPU process decoupled behind a network
boundary (the recommended sidecar/cluster topology).

All upstream calls funnel through the shared resilience layer: a tenacity
retryer wrapped by an async circuit breaker. A shared ``httpx.AsyncClient``
with a tuned connection pool backs the client so we reuse keep-alive sockets
to vLLM under heavy concurrency.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.core.config import Settings
from app.core.resilience import AsyncCircuitBreaker, build_retryer
from app.observability import UPSTREAM_ERRORS, get_logger
from app.schemas import ChatMessage, ChatRequest, ChatResponse, Role, Usage

logger = get_logger(__name__)

# Map our validated wire roles to LangChain message classes.
_ROLE_TO_MESSAGE = {
    Role.SYSTEM: SystemMessage,
    Role.USER: HumanMessage,
    Role.ASSISTANT: AIMessage,
}


def _to_langchain_messages(messages: list[ChatMessage]) -> list[BaseMessage]:
    """Convert validated request messages into LangChain message objects."""
    return [_ROLE_TO_MESSAGE[m.role](content=m.content) for m in messages]


class LLMService:
    """Async facade over the vLLM-backed LangChain chat model."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._http_client: httpx.AsyncClient | None = None
        self._breaker = AsyncCircuitBreaker(
            fail_max=settings.circuit_breaker_fail_max,
            reset_timeout_s=settings.circuit_breaker_reset_timeout_s,
        )
        self._retryer = build_retryer(settings)

    # --- Lifecycle -----------------------------------------------------------
    async def connect(self) -> None:
        """Create the pooled HTTP client shared by all LLM invocations."""
        limits = httpx.Limits(
            max_connections=self._settings.http_max_connections,
            max_keepalive_connections=self._settings.http_max_keepalive_connections,
        )
        timeout = httpx.Timeout(
            connect=self._settings.http_connect_timeout_s,
            read=self._settings.http_read_timeout_s,
            write=self._settings.http_read_timeout_s,
            pool=self._settings.http_connect_timeout_s,
        )
        self._http_client = httpx.AsyncClient(limits=limits, timeout=timeout)
        logger.info(
            "http_client_initialised",
            max_connections=self._settings.http_max_connections,
        )

    async def close(self) -> None:
        """Drain and close the shared HTTP client."""
        if self._http_client is not None:
            await self._http_client.aclose()
        logger.info("http_client_closed")

    async def healthy(self) -> bool:
        """Readiness check: confirm the vLLM models endpoint responds."""
        if self._http_client is None:
            return False
        try:
            url = f"{self._settings.vllm_base_url.rstrip('/')}/models"
            resp = await self._http_client.get(
                url,
                headers={"Authorization": f"Bearer {self._settings.vllm_api_key}"},
            )
            return resp.status_code == httpx.codes.OK
        except httpx.HTTPError as exc:
            logger.warning("vllm_health_check_failed", error=str(exc))
            return False

    # --- Model construction --------------------------------------------------
    def _build_model(self, request: ChatRequest, *, streaming: bool) -> ChatOpenAI:
        """Construct a per-request ChatOpenAI bound to our pooled HTTP client.

        Constructing a thin model object per request is cheap (no sockets are
        opened — the heavyweight ``httpx.AsyncClient`` is injected and reused)
        and lets callers override generation parameters safely within bounds
        already validated by Pydantic.
        """
        return ChatOpenAI(
            model=request.model or self._settings.model_name,
            base_url=self._settings.vllm_base_url,
            api_key=self._settings.vllm_api_key,
            temperature=(
                request.temperature
                if request.temperature is not None
                else self._settings.default_temperature
            ),
            max_tokens=(
                request.max_tokens
                if request.max_tokens is not None
                else self._settings.default_max_tokens
            ),
            top_p=request.top_p,
            streaming=streaming,
            http_async_client=self._http_client,
            # The LLM cache is global; non-streaming calls consult it
            # automatically. Streaming bypasses the cache by design (TTFT).
            cache=not streaming,
            max_retries=0,  # retries are handled by our tenacity layer
        )

    # --- Inference -----------------------------------------------------------
    async def acomplete(self, request: ChatRequest) -> ChatResponse:
        """Run a non-streaming completion with retries + circuit breaking."""
        model = self._build_model(request, streaming=False)
        messages = _to_langchain_messages(request.messages)

        async def _invoke() -> AIMessage:
            return await model.ainvoke(messages)

        result = await self._call_with_resilience(_invoke)

        usage = self._extract_usage(result)
        return ChatResponse(
            model=request.model or self._settings.model_name,
            content=str(result.content),
            cached=False,  # set True by the route if served from cache
            usage=usage,
        )

    async def astream(self, request: ChatRequest) -> AsyncIterator[str]:
        """Stream completion tokens to minimise Time-To-First-Token.

        The circuit breaker guards the *establishment* of the stream; once the
        first chunk flows we yield directly. Transient connection failures
        before the stream opens are retried by the resilience layer.
        """
        model = self._build_model(request, streaming=True)
        messages = _to_langchain_messages(request.messages)

        async def _open_stream() -> AsyncIterator[BaseMessage]:
            return model.astream(messages)

        stream = await self._call_with_resilience(_open_stream)
        async for chunk in stream:
            content = getattr(chunk, "content", "")
            if content:
                yield str(content)

    # --- Internals -----------------------------------------------------------
    async def _call_with_resilience(self, factory):
        """Execute ``factory`` through tenacity retries wrapped by the breaker."""
        try:
            async for attempt in self._retryer:
                with attempt:
                    return await self._breaker.call(factory)
        except httpx.TimeoutException:
            UPSTREAM_ERRORS.labels(kind="timeout").inc()
            raise
        except httpx.ConnectError:
            UPSTREAM_ERRORS.labels(kind="connection").inc()
            raise
        except httpx.HTTPStatusError:
            UPSTREAM_ERRORS.labels(kind="http_status").inc()
            raise

    @staticmethod
    def _extract_usage(message: AIMessage) -> Usage:
        """Pull token usage from a LangChain response if the backend reports it."""
        metadata = getattr(message, "usage_metadata", None) or {}
        return Usage(
            prompt_tokens=int(metadata.get("input_tokens", 0)),
            completion_tokens=int(metadata.get("output_tokens", 0)),
            total_tokens=int(metadata.get("total_tokens", 0)),
        )
