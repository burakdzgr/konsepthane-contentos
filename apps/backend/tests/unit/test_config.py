"""Tests for typed application settings."""

import pytest
from pydantic import ValidationError

from contentos import __version__
from contentos.core.config import Environment, LogLevel, Settings

CONTENTOS_ENVIRONMENT_VARIABLES = (
    "CONTENTOS_ENVIRONMENT",
    "CONTENTOS_SERVICE_NAME",
    "CONTENTOS_APPLICATION_VERSION",
    "CONTENTOS_LOG_LEVEL",
    "CONTENTOS_API_DOCS_ENABLED",
)


@pytest.fixture(autouse=True)
def clear_contentos_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep settings tests independent from the invoking shell."""
    for variable in CONTENTOS_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(variable, raising=False)


def test_default_local_settings() -> None:
    settings = Settings()

    assert settings.environment is Environment.LOCAL
    assert settings.service_name == "Konsepthane ContentOS"
    assert settings.application_version == __version__
    assert settings.log_level is LogLevel.INFO
    assert settings.api_docs_enabled is True


def test_contentos_environment_variable_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "Ignored Service")
    monkeypatch.setenv("CONTENTOS_ENVIRONMENT", "test")
    monkeypatch.setenv("CONTENTOS_SERVICE_NAME", "Configured ContentOS")
    monkeypatch.setenv("CONTENTOS_APPLICATION_VERSION", "1.2.3")
    monkeypatch.setenv("CONTENTOS_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("CONTENTOS_API_DOCS_ENABLED", "false")

    settings = Settings()

    assert settings.environment is Environment.TEST
    assert settings.service_name == "Configured ContentOS"
    assert settings.application_version == "1.2.3"
    assert settings.log_level is LogLevel.WARNING
    assert settings.api_docs_enabled is False


def test_valid_production_settings() -> None:
    settings = Settings(
        environment=Environment.PRODUCTION,
        service_name="Konsepthane ContentOS",
        application_version="1.0.0",
        log_level=LogLevel.INFO,
        api_docs_enabled=False,
    )

    assert settings.environment is Environment.PRODUCTION
    assert settings.api_docs_enabled is False


def test_invalid_environment_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="staging")  # type: ignore[arg-type]
