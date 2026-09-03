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
    auth_session_ttl_hours: int = Field(default=12, ge=1, le=168)
    # ContentOS-owned media byte store only; never a Konsepthane path.
    media_store_root: str = Field(default="./data/media-store", min_length=1)
    redis_broker_url: SecretStr = SecretStr("redis://localhost:6379/0")
    redis_result_url: SecretStr = SecretStr("redis://localhost:6379/1")
    celery_default_queue: str = Field(default="contentos.default", min_length=1)
    celery_task_always_eager: bool = False
    celery_broker_connection_retry_on_startup: bool = True
    celery_broker_connection_timeout_seconds: int = Field(default=10, ge=1, le=60)
    celery_result_expires_seconds: int = Field(default=3600, ge=60, le=86400)
    fetch_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)
    fetch_read_timeout_seconds: int = Field(default=10, ge=1, le=120)
    fetch_max_body_bytes: int = Field(default=5_242_880, ge=1024, le=52_428_800)
    fetch_max_redirects: int = Field(default=5, ge=0, le=10)
    fetch_min_host_interval_seconds: float = Field(default=1.0, ge=0.0, le=60.0)
    fetch_user_agent: str = Field(
        default="Konsepthane-ContentOS/0.1 (+https://konsepthane.net)", min_length=1
    )
    # OpenAI configuration is needed ONLY when constructing the OpenAI
    # adapter; every non-OpenAI feature works without it. Provider and
    # model are configuration, never domain constants.
    # Daily provider-spend guard: durable AI attempts allowed per UTC day
    # across all purposes. None disables the guard explicitly.
    ai_daily_attempt_budget: int | None = Field(default=500, ge=1, le=100_000)
    openai_api_key: SecretStr | None = None
    openai_model: str | None = Field(default=None, min_length=1)
    openai_timeout_seconds: float = Field(default=60.0, ge=1.0, le=600.0)
    openai_image_model: str | None = Field(default=None, min_length=1)
    openai_image_timeout_seconds: float = Field(default=120.0, ge=1.0, le=600.0)
    # Autonomous intake orchestration bounds (per-run and per-source).
    # Every limit is a hard cap the orchestrator can only stay under;
    # remaining candidates persist durably for a later run.
    intake_prefilter_batch_size: int = Field(default=1000, ge=10, le=10_000)
    intake_fetch_batch_size: int = Field(default=8, ge=1, le=50)
    intake_max_fetches_per_run: int = Field(default=40, ge=1, le=1000)
    intake_daily_fetch_budget_per_source: int = Field(default=150, ge=1, le=5000)
    intake_max_promotions_per_run: int = Field(default=20, ge=1, le=200)
    intake_step_interval_seconds: int = Field(default=15, ge=5, le=600)
    # The Publishing API is the ONLY path toward Konsepthane production.
    # Deliberately default-None: there is no default endpoint, and the
    # HTTP transport refuses to construct without both values.
    publishing_api_url: str | None = Field(default=None, min_length=1)
    publishing_api_key: SecretStr | None = None
    publishing_timeout_seconds: float = Field(default=30.0, ge=1.0, le=600.0)

    @field_validator(
        "openai_api_key",
        "openai_model",
        "openai_image_model",
        "publishing_api_url",
        "publishing_api_key",
        mode="before",
    )
    @classmethod
    def _empty_env_means_unset(cls, value: object) -> object:
        # Compose passes optional vars through as "" when the host env
        # does not set them; an empty string is "not configured", never
        # a value (min_length=1 would otherwise reject construction).
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @field_validator("database_url")
    @classmethod
    def _require_psycopg_postgresql_url(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith("postgresql+psycopg://"):
            raise ValueError("database_url must use the postgresql+psycopg:// scheme")
        return value

    @field_validator("redis_broker_url", "redis_result_url")
    @classmethod
    def _require_redis_url(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith(("redis://", "rediss://")):
            raise ValueError("Redis URLs must use the redis:// or rediss:// scheme")
        return value
