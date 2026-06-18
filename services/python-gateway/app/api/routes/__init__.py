"""HTTP route definitions, grouped by concern.

``api_router`` aggregates every sub-router so ``main.py`` only needs a single
``include_router`` call.
"""

from fastapi import APIRouter

from app.api.routes import chat, health

api_router = APIRouter()
api_router.include_router(chat.router)
api_router.include_router(health.router)

__all__ = ["api_router"]
