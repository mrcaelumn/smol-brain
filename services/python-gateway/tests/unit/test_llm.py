"""Unit tests for the LLM service facade.

The real ``ChatOpenAI`` model construction is bypassed by patching
``_build_model`` so these tests stay fast and offline while still exercising
the resilience path, message conversion and usage extraction.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.core.config import Settings
from app.schemas import ChatMessage, ChatRequest, Role
from app.services.llm import LLMService, _to_langchain_messages


def _request(content: str = "hi", **kwargs: object) -> ChatRequest:
    return ChatRequest(messages=[ChatMessage(role=Role.USER, content=content)], **kwargs)


# --- Pure helpers ------------------------------------------------------------
def test_role_to_message_mapping() -> None:
    messages = [
        ChatMessage(role=Role.SYSTEM, content="sys"),
        ChatMessage(role=Role.USER, content="usr"),
        ChatMessage(role=Role.ASSISTANT, content="ast"),
    ]
    converted = _to_langchain_messages(messages)
    assert isinstance(converted[0], SystemMessage)
    assert isinstance(converted[1], HumanMessage)
    assert isinstance(converted[2], AIMessage)
    assert converted[1].content == "usr"


def test_extract_usage_reads_metadata() -> None:
    message = AIMessage(
        content="x",
        usage_metadata={"input_tokens": 5, "output_tokens": 7, "total_tokens": 12},
    )
    usage = LLMService._extract_usage(message)
    assert usage.prompt_tokens == 5
    assert usage.completion_tokens == 7
    assert usage.total_tokens == 12


def test_extract_usage_handles_missing_metadata() -> None:
    message = AIMessage(content="x")
    usage = LLMService._extract_usage(message)
    assert usage.total_tokens == 0


# --- Inference paths ---------------------------------------------------------
async def test_acomplete_builds_response(monkeypatch: pytest.MonkeyPatch) -> None:
    service = LLMService(Settings(model_name="my-model", retry_max_attempts=1))

    class _FakeModel:
        async def ainvoke(self, _messages: object) -> AIMessage:
            return AIMessage(
                content="hello there",
                usage_metadata={"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
            )

    monkeypatch.setattr(
        service, "_build_model", lambda request, *, streaming: _FakeModel()
    )

    response = await service.acomplete(_request())
    assert response.content == "hello there"
    assert response.model == "my-model"
    assert response.usage.total_tokens == 3
    assert response.cached is False


async def test_acomplete_retries_transient_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = LLMService(
        Settings(
            retry_max_attempts=3,
            retry_initial_backoff_s=0.001,
            retry_max_backoff_s=0.002,
        )
    )
    calls = {"n": 0}

    class _FlakyModel:
        async def ainvoke(self, _messages: object) -> AIMessage:
            calls["n"] += 1
            if calls["n"] < 2:
                raise httpx.ConnectError("blip")
            return AIMessage(content="recovered")

    monkeypatch.setattr(
        service, "_build_model", lambda request, *, streaming: _FlakyModel()
    )

    response = await service.acomplete(_request())
    assert response.content == "recovered"
    assert calls["n"] == 2


async def test_astream_yields_token_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    service = LLMService(Settings())

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class _StreamModel:
        def astream(self, _messages: object) -> AsyncIterator[_Chunk]:
            async def _gen() -> AsyncIterator[_Chunk]:
                for token in ("He", "llo", ""):  # empty chunk must be skipped
                    yield _Chunk(token)

            return _gen()

    monkeypatch.setattr(
        service, "_build_model", lambda request, *, streaming: _StreamModel()
    )

    tokens = [tok async for tok in service.astream(_request(stream=True))]
    assert tokens == ["He", "llo"]


async def test_healthy_false_when_not_connected() -> None:
    service = LLMService(Settings())
    assert await service.healthy() is False
