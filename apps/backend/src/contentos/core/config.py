"""Typed application settings."""

from enum import StrEnum

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from contentos import __version__


class Environment(StrEnum):
    """Supported runtime environments."""

    LOCAL = "local"
    TEST = "test"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    """Supported application log levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Settings(BaseSettings):
    """Validated ContentOS application settings."""

    model_config = SettingsConfigDict(
        env_prefix="CONTENTOS_",
        env_file=None,
        case_sensitive=False,
        extra="ignore",
        str_strip_whitespace=True,
    )

    environment: Environment = Environment.LOCAL
    service_name: str = Field(default="Konsepthane ContentOS", min_length=1)
    application_version: str = Field(default=__version__, min_length=1)
    log_level: LogLevel = LogLevel.INFO
    api_docs_enabled: bool = True
