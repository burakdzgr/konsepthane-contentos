"""Typed application settings."""

from enum import StrEnum

from pydantic import Field, SecretStr, field_validator
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
    # ContentOS-owned database only; never point this at a Konsepthane database.
    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://contentos:contentos@localhost:5432/contentos"
    )
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_pool_timeout_seconds: int = Field(default=30, ge=1, le=300)
    db_connect_timeout_seconds: int = Field(default=10, ge=1, le=60)

    @field_validator("database_url")
    @classmethod
    def _require_psycopg_postgresql_url(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith("postgresql+psycopg://"):
            raise ValueError("database_url must use the postgresql+psycopg:// scheme")
        return value
