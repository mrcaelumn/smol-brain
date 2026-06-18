"""Unit tests for Pydantic request/response schemas (input validation)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import ChatMessage, ChatRequest, ChatResponse, Role, Usage


def test_valid_minimal_request() -> None:
    req = ChatRequest(messages=[ChatMessage(role=Role.USER, content="hi")])
    assert req.stream is False
    assert req.temperature is None
    assert req.model is None


def test_empty_messages_rejected() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(messages=[])


def test_too_many_messages_rejected() -> None:
    messages = [ChatMessage(role=Role.USER, content="x") for _ in range(201)]
    with pytest.raises(ValidationError):
        ChatRequest(messages=messages)


def test_empty_content_rejected() -> None:
    with pytest.raises(ValidationError):
        ChatMessage(role=Role.USER, content="")


def test_extra_field_forbidden_on_request() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(
            messages=[ChatMessage(role=Role.USER, content="x")],
            unexpected="boom",
        )


def test_extra_field_forbidden_on_message() -> None:
    with pytest.raises(ValidationError):
        ChatMessage(role=Role.USER, content="x", name="nope")


def test_temperature_out_of_range_rejected() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(
            messages=[ChatMessage(role=Role.USER, content="x")],
            temperature=2.5,
        )


def test_top_p_zero_rejected() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(
            messages=[ChatMessage(role=Role.USER, content="x")],
            top_p=0.0,
        )


def test_max_tokens_above_cap_rejected() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(
            messages=[ChatMessage(role=Role.USER, content="x")],
            max_tokens=40_000,
        )


def test_invalid_role_rejected() -> None:
    with pytest.raises(ValidationError):
        ChatMessage(role="root", content="x")


def test_usage_defaults_to_zero() -> None:
    usage = Usage()
    assert usage.prompt_tokens == 0
    assert usage.completion_tokens == 0
    assert usage.total_tokens == 0


def test_response_serialization_shape() -> None:
    resp = ChatResponse(model="m", content="hello")
    dumped = resp.model_dump()
    assert dumped["model"] == "m"
    assert dumped["cached"] is False
    assert dumped["usage"]["total_tokens"] == 0
