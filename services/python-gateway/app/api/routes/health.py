"""Operational routes: liveness, readiness and Prometheus metrics."""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from app import __version__
from app.core.config import Settings
from app.observability import REGISTRY
from app.schemas import HealthResponse

router = APIRouter(tags=["ops"])


@router.get("/healthz", response_model=HealthResponse)
async def healthz(request: Request) -> HealthResponse:
    """Liveness probe: the process is up and the event loop responsive.

    Deliberately does NOT touch Redis/vLLM — a liveness failure triggers a
    pod *restart*, which a transient dependency outage should not.
    """
    settings: Settings = request.app.state.settings
    return HealthResponse(
        status="ok", service=settings.service_name, version=__version__
    )


@router.get("/readyz", response_model=HealthResponse)
async def readyz(request: Request) -> Response:
    """Readiness probe: are downstream dependencies usable?

    A failure here removes the pod from the load-balancer rotation without
    restarting it, so traffic is steered to healthy replicas.
    """
    settings: Settings = request.app.state.settings
    cache_ok = await request.app.state.cache_manager.healthy()
    vllm_ok = await request.app.state.llm_service.healthy()
    ready = cache_ok and vllm_ok
    payload = HealthResponse(
        status="ok" if ready else "degraded",
        service=settings.service_name,
        version=__version__,
        checks={"redis": cache_ok, "vllm": vllm_ok},
    )
    code = status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(content=payload.model_dump(), status_code=code)


@router.get("/metrics")
async def metrics() -> Response:
    """Expose Prometheus metrics in the text exposition format."""
    return Response(
        content=generate_latest(REGISTRY),
        media_type=CONTENT_TYPE_LATEST,
    )
