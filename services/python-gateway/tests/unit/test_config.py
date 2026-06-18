"""Unit tests for application configuration parsing and validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings


def test_defaults() -> None:
    settings = Settings()
    assert settings.service_name == "smol-brain-gateway"
    assert settings.environment == "production"
    assert settings.log_level == "INFO"
    assert settings.auth_enabled is False  # no API keys configured by default


def test_api_keys_comma_separated() -> None:
    """A CSV string is split into a clean list (whitespace trimmed)."""
    settings = Settings(api_keys="k1, k2 ,k3")
    assert settings.api_keys == ["k1", "k2", "k3"]
    assert settings.auth_enabled is True


def test_cors_origins_comma_separated() -> None:
    settings = Settings(cors_allow_origins="https://a.com, https://b.com")
    assert settings.cors_allow_origins == ["https://a.com", "https://b.com"]


def test_empty_csv_yields_empty_list() -> None:
    settings = Settings(api_keys="")
    assert settings.api_keys == []
    assert settings.auth_enabled is False


def test_env_vars_are_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression test for the NoDecode fix: CSV env vars must not be JSON-parsed.

    Without ``NoDecode`` pydantic-settings would try to JSON-decode the value
    and raise on a plain comma-separated string.
    """
    monkeypatch.setenv("GATEWAY_API_KEYS", "envkey1,envkey2")
    monkeypatch.setenv("GATEWAY_LOG_LEVEL", "DEBUG")
    settings = Settings()
    assert settings.api_keys == ["envkey1", "envkey2"]
    assert settings.log_level == "DEBUG"


def test_temperature_bounds() -> None:
    Settings(default_temperature=0.0)
    Settings(default_temperature=2.0)
    with pytest.raises(ValidationError):
        Settings(default_temperature=2.1)
    with pytest.raises(ValidationError):
        Settings(default_temperature=-0.1)


def test_max_tokens_bounds() -> None:
    with pytest.raises(ValidationError):
        Settings(default_max_tokens=0)


def test_invalid_log_level_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(log_level="TRACE")


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
