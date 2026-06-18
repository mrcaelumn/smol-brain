"""Inference routes: the chat-completion endpoint."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.responses import Response

from app.api.dependencies import enforce_rate_limit, get_llm_service
from app.core.resilience import CircuitOpenError
from app.schemas import ChatRequest, ChatResponse, ErrorResponse
from app.services.llm import LLMService

router = APIRouter(tags=["inference"])


@router.post(
    "/v1/chat",
    response_model=ChatResponse,
    responses={401: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
)
async def chat(
    request: ChatRequest,
    _identity: str = Depends(enforce_rate_limit),
    llm: LLMService = Depends(get_llm_service),
) -> Response:
    """Chat completion endpoint.

    Honours ``stream`` to return Server-Sent Events for low TTFT, otherwise
    returns a buffered JSON response (which can be served from cache).
    """
    if request.stream:

        async def event_source() -> AsyncIterator[bytes]:
            try:
                async for token in llm.astream(request):
                    # SSE framing: one ``data:`` event per token chunk.
                    yield f"data: {token}\n\n".encode()
                yield b"data: [DONE]\n\n"
            except CircuitOpenError:
                yield b"event: error\ndata: upstream unavailable\n\n"

        return StreamingResponse(
            event_source(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    result = await llm.acomplete(request)
    return JSONResponse(content=result.model_dump())
