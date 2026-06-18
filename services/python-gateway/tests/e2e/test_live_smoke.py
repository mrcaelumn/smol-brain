"""End-to-end smoke tests against a running gateway.

These are skipped unless ``GATEWAY_E2E_URL`` points at a live gateway (e.g. the
docker-compose stack). Run with, for example::

    GATEWAY_E2E_URL=http://localhost:8080 \
    GATEWAY_E2E_API_KEY=your-key \
    pytest tests/e2e -v
"""

from __future__ import annotations

import os

import httpx
import pytest

BASE_URL = os.environ.get("GATEWAY_E2E_URL")
API_KEY = os.environ.get("GATEWAY_E2E_API_KEY", "")

pytestmark = pytest.mark.skipif(
    not BASE_URL, reason="set GATEWAY_E2E_URL to run end-to-end tests"
)


def test_healthz_live() -> None:
    response = httpx.get(f"{BASE_URL}/healthz", timeout=5.0)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_chat_live() -> None:
    headers = {"X-API-Key": API_KEY} if API_KEY else {}
    response = httpx.post(
        f"{BASE_URL}/v1/chat",
        headers=headers,
        json={"messages": [{"role": "user", "content": "Say hi in one word."}]},
        timeout=60.0,
    )
    assert response.status_code == 200
    assert response.json()["content"]
