"""Typed application settings."""

from enum import StrEnum
from typing import Literal

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
    # Which adapter backs StructuredGenerationProvider (ADR 0011). The
    # Subcontractor gateway relays prompts to licensed browser sessions
    # behind an API key; jobs are submitted and polled.
    ai_provider: Literal["openai", "subcontractor"] = "openai"
    subcontractor_base_url: str | None = Field(default=None, min_length=1)
    subcontractor_api_key: SecretStr | None = None
    subcontractor_model: str = Field(default="chatgpt", min_length=1)
    subcontractor_image_model: str = Field(default="chatgpt", min_length=1)
    subcontractor_timeout_seconds: float = Field(default=420.0, ge=10.0, le=1800.0)
    subcontractor_poll_interval_seconds: float = Field(default=5.0, ge=1.0, le=60.0)
    # Gateway ADMIN token: lets the live operations page read /api/status
    # (accounts, queue, running jobs) server-side; never exposed to browsers.
    subcontractor_admin_token: SecretStr | None = None

    @property
    def openai_text_provider_configured(self) -> bool:
        """Both values the OpenAI text adapter refuses to construct without."""
        return self.openai_api_key is not None and self.openai_model is not None

    @property
    def openai_image_provider_configured(self) -> bool:
        return self.openai_api_key is not None and self.openai_image_model is not None

    @property
    def subcontractor_configured(self) -> bool:
        return self.subcontractor_base_url is not None and self.subcontractor_api_key is not None

    @property
    def text_provider_configured(self) -> bool:
        """Can the selected adapter run a text/structured job right now?"""
        if self.ai_provider == "subcontractor":
            return self.subcontractor_configured
        return self.openai_text_provider_configured

    @property
    def image_provider_configured(self) -> bool:
        if self.ai_provider == "subcontractor":
            return self.subcontractor_configured
        return self.openai_image_provider_configured

    def ai_provider_required_env(self, *, image: bool = False) -> str:
        """The exact variables an operator must set for the selected adapter."""
        if self.ai_provider == "subcontractor":
            return "CONTENTOS_SUBCONTRACTOR_BASE_URL ve CONTENTOS_SUBCONTRACTOR_API_KEY"
        return (
            "CONTENTOS_OPENAI_API_KEY ve CONTENTOS_OPENAI_IMAGE_MODEL"
            if image
            else "CONTENTOS_OPENAI_API_KEY ve CONTENTOS_OPENAI_MODEL"
        )

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

    # --- external intelligence providers (agent C) ---
    # Every provider is optional: without its credentials it reports an honest
    # `not_configured` / `access_required` state and the rest of ContentOS
    # keeps working. Per-provider daily budgets and cache TTLs bound spend.
    semrush_api_key: SecretStr | None = None
    semrush_database: str = Field(default="tr", min_length=2, max_length=8)
    semrush_daily_budget: int = Field(default=200, ge=1, le=100_000)
    semrush_cache_hours: int = Field(default=72, ge=1, le=720)
    # Google service account: the JSON key content itself OR a path to the
    # key file (both accepted). Grant it Search Console property access and
    # GA4 property Viewer; the same account serves both Google providers.
    google_service_account_json: SecretStr | None = None
    gsc_site_url: str | None = Field(default=None, min_length=1)
    gsc_daily_budget: int = Field(default=500, ge=1, le=100_000)
    gsc_cache_hours: int = Field(default=12, ge=1, le=720)
    ga4_property_id: str | None = Field(default=None, min_length=1)
    # Comma-separated GA4 key event names; key events are reported ONLY
    # when configured (never invented for events Konsepthane does not have).
    ga4_key_events: str | None = Field(default=None, min_length=1)
    ga4_daily_budget: int = Field(default=500, ge=1, le=100_000)
    ga4_cache_hours: int = Field(default=12, ge=1, le=720)
    # Google Trends has no generally available official API; the adapter
    # only activates with an (alpha/allow-listed) API key. Never scraped.
    google_trends_api_key: SecretStr | None = None
    google_trends_api_url: str | None = Field(default=None, min_length=1)
    google_trends_daily_budget: int = Field(default=200, ge=1, le=100_000)
    google_trends_cache_hours: int = Field(default=24, ge=1, le=720)
    pinterest_access_token: SecretStr | None = None
    pinterest_region: str = Field(default="TR", min_length=2, max_length=8)
    pinterest_daily_budget: int = Field(default=200, ge=1, le=100_000)
    pinterest_cache_hours: int = Field(default=24, ge=1, le=720)
    # Google Trends — BigQuery Public Dataset (first-party trend discovery).
    # Reuses the Search Console / GA4 service-account key; the account needs
    # only "BigQuery Job User" on the query project (default: the key's own).
    google_cloud_project_id: str | None = Field(default=None, min_length=1)
    google_trends_bigquery_country: str = Field(default="TR", min_length=2, max_length=2)
    google_trends_bigquery_daily_budget: int = Field(default=20, ge=1, le=10_000)
    google_trends_bigquery_cache_hours: int = Field(default=24, ge=1, le=720)
    google_trends_bigquery_max_bytes_billed: int = Field(
        default=2_000_000_000, ge=10_000_000, le=1_000_000_000_000
    )
    google_trends_bigquery_sync_hour_utc: int = Field(default=15, ge=0, le=23)
    integrations_http_timeout_seconds: float = Field(default=20.0, ge=1.0, le=120.0)

    # --- performance loop (agent E) ---
    # Classifier thresholds (pure policy, snapshotted into every assessment
    # basis) and the Celery beat schedule for the daily Measure -> Learn loop.
    performance_min_impressions: int = Field(default=100, ge=1, le=1_000_000)
    performance_min_days: int = Field(default=7, ge=1, le=90)
    performance_decline_pct: float = Field(default=0.25, ge=0.01, le=1.0)
    performance_rise_pct: float = Field(default=0.25, ge=0.01, le=10.0)
    performance_volatility_pct: float = Field(default=0.5, ge=0.01, le=1.0)
    performance_schedule_enabled: bool = True
    performance_sync_hour_utc: int = Field(default=3, ge=0, le=23)
    performance_learn_hour_utc: int = Field(default=4, ge=0, le=23)
    performance_market_interval_hours: int = Field(default=24, ge=1, le=168)

    @field_validator(
        "openai_api_key",
        "openai_model",
        "openai_image_model",
        "subcontractor_base_url",
        "subcontractor_api_key",
        "subcontractor_admin_token",
        "publishing_api_url",
        "publishing_api_key",
        "semrush_api_key",
        "google_service_account_json",
        "gsc_site_url",
        "ga4_property_id",
        "ga4_key_events",
        "google_trends_api_key",
        "google_trends_api_url",
        "google_cloud_project_id",
        "pinterest_access_token",
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
