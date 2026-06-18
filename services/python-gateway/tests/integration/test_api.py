"""Integration tests for the HTTP API via Starlette's TestClient.

The app is constructed with ``create_app`` and its singletons on ``app.state``
are replaced with lightweight stubs. The TestClient is used *without* a
``with`` block so the real lifespan (which would connect to Redis/vLLM) never
runs — exactly the seam we want for fast, hermetic HTTP tests.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import enforce_rate_limit, get_llm_service
from app.core.config import Settings
from app.core.resilience import CircuitOpenError
from app.main import create_app
from app.schemas import ChatRequest, ChatResponse, Usage


class StubLLM:
    """A stand-in LLM service returning deterministic output."""

    async def acomplete(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            model="stub", content="pong", cached=False, usage=Usage(total_tokens=2)
        )

    async def astream(self, request: ChatRequest) -> AsyncIterator[str]:
        for token in ("pi", "ng"):
            yield token

    async def healthy(self) -> bool:
        return True


class StubHealth:
    def __init__(self, healthy: bool) -> None:
        self._healthy = healthy

    async def healthy(self) -> bool:
        return self._healthy


def _build_client(
    *,
    llm: object | None = None,
    cache_healthy: bool = True,
    vllm_healthy: bool = True,
) -> TestClient:
    app = create_app()
    app.state.settings = Settings(environment="local")
    app.state.cache_manager = StubHealth(cache_healthy)
    app.state.llm_service = llm or StubHealth(vllm_healthy)
    app.state.rate_limiter = SimpleNamespace()
    app.dependency_overrides[enforce_rate_limit] = lambda: "tester"
    app.dependency_overrides[get_llm_service] = lambda: llm or StubLLM()
    return TestClient(app)


@pytest.fixture
def client() -> TestClient:
    return _build_client(llm=StubLLM())


# --- Ops endpoints -----------------------------------------------------------
def test_healthz_ok(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readyz_ok_when_dependencies_healthy() -> None:
    client = _build_client(llm=StubLLM(), cache_healthy=True, vllm_healthy=True)
    response = client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"redis": True, "vllm": True}


def test_readyz_degraded_when_dependency_down() -> None:
    # Redis reports unhealthy while the (stub) LLM service is fine.
    client = _build_client(llm=StubLLM(), cache_healthy=False)
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


def test_metrics_endpoint(client: TestClient) -> None:
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "gateway_requests_total" in response.text


def test_request_id_header_is_echoed(client: TestClient) -> None:
    response = client.get("/healthz")
    assert "x-request-id" in {k.lower() for k in response.headers}


# --- Chat endpoint -----------------------------------------------------------
def test_chat_non_streaming(client: TestClient) -> None:
    response = client.post(
        "/v1/chat",
        json={"messages": [{"role": "user", "content": "ping"}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "pong"
    assert body["cached"] is False


def test_chat_streaming(client: TestClient) -> None:
    response = client.post(
        "/v1/chat",
        json={"messages": [{"role": "user", "content": "ping"}], "stream": True},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "data: pi" in response.text
    assert "[DONE]" in response.text


def test_chat_rejects_empty_messages(client: TestClient) -> None:
    response = client.post("/v1/chat", json={"messages": []})
    assert response.status_code == 422


def test_chat_rejects_unknown_field(client: TestClient) -> None:
    response = client.post(
        "/v1/chat",
        json={"messages": [{"role": "user", "content": "x"}], "bogus": 1},
    )
    assert response.status_code == 422


def test_chat_circuit_open_returns_503() -> None:
    class OpenLLM:
        async def acomplete(self, request: ChatRequest) -> ChatResponse:
            raise CircuitOpenError("upstream open")

    client = _build_client(llm=OpenLLM())
    response = client.post(
        "/v1/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 503
    assert response.json()["error"] == "upstream_unavailable"
    assert response.headers["Retry-After"] == "5"
