"""Unit tests for metrics helpers and the Prometheus registry."""

from __future__ import annotations

from prometheus_client import generate_latest

from app.observability import REGISTRY, REQUEST_COUNT, status_class


def test_status_class_buckets() -> None:
    assert status_class(200) == "2xx"
    assert status_class(301) == "3xx"
    assert status_class(404) == "4xx"
    assert status_class(503) == "5xx"


def test_counter_increments() -> None:
    labels = ("GET", "/unit-test", "2xx")
    before = REQUEST_COUNT.labels(*labels)._value.get()
    REQUEST_COUNT.labels(*labels).inc()
    after = REQUEST_COUNT.labels(*labels)._value.get()
    assert after == before + 1


def test_registry_exposes_named_metrics() -> None:
    output = generate_latest(REGISTRY).decode()
    assert "gateway_requests_total" in output
    assert "gateway_request_latency_seconds" in output
    assert "gateway_circuit_state" in output
