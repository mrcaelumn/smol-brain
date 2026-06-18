"""Request and response validation schemas (Pydantic v2).

Validation is the gateway's first line of defence: malformed or abusive
payloads are rejected at the edge before any Redis or GPU resource is touched.
Field constraints double as lightweight input sanitisation (length caps,
enumerated roles, bounded generation parameters).
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Hard caps protect memory and the upstream from pathological inputs.
MAX_MESSAGE_LEN = 32_000
MAX_MESSAGES = 200


class Role(str, Enum):
    """Permitted chat roles."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(BaseModel):
    """A single turn in a chat conversation."""

    model_config = ConfigDict(extra="forbid")

    role: Role
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_LEN)


class ChatRequest(BaseModel):
    """Inbound chat-completion request.

    Generation parameters are optional; when omitted the server applies
    configured defaults. Bounds mirror sensible vLLM limits.
    """

    model_config = ConfigDict(extra="forbid")

    messages: list[ChatMessage] = Field(min_length=1, max_length=MAX_MESSAGES)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=32_768)
    top_p: float | None = Field(default=None, gt=0.0, le=1.0)
    stream: bool = False
    # Optional override of the served model; defaults to configured model.
    model: str | None = Field(default=None, max_length=256)


class Usage(BaseModel):
    """Token accounting for a completion."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatResponse(BaseModel):
    """Non-streaming chat-completion response."""

    model: str
    content: str
    cached: bool = Field(
        default=False,
        description="True if the answer was served from cache (no GPU compute).",
    )
    usage: Usage = Field(default_factory=Usage)


class HealthResponse(BaseModel):
    """Liveness/readiness probe payload."""

    status: Literal["ok", "degraded"]
    service: str
    version: str
    checks: dict[str, bool] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """RFC-7807-ish structured error body."""

    error: str
    detail: str | None = None
    request_id: str | None = None
