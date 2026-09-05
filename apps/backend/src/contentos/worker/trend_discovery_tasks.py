"""Daily Google Trends (BigQuery Public Dataset) discovery sync.

One bounded Celery task per day (existing beat): find the newest Türkiye
partition, skip when that refresh date is already persisted (idempotent),
otherwise read the top + rising sets, persist them as provenance-complete
search signals, derive the relevant-term intelligence signals, and record
the provider's durable status. Every failure is a typed, secret-free
summary; transient kinds (`rate_limited`, `degraded`) get a bounded Celery
retry with backoff, everything else waits for the next scheduled run.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import structlog
from celery import Celery

from contentos.integrations.base import ProviderError
from contentos.integrations.enums import ProviderName, ProviderState
from contentos.worker.runtime import WorkerRuntime

SYNC_GOOGLE_TRENDS_BIGQUERY_TASK = "contentos.trends.sync_google_trends_bigquery"
TREND_DISCOVERY_TASK_NAMES = (SYNC_GOOGLE_TRENDS_BIGQUERY_TASK,)

MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = 900
TRANSIENT_STATES = (ProviderState.RATE_LIMITED, ProviderState.DEGRADED)

RegistryFactory = Callable[[], Any]

_logger = structlog.get_logger("contentos.trends.worker")


class TrendDiscoveryUnavailableError(Exception):
    """The integration layer cannot be imported or constructed."""


def _default_registry_factory(runtime: WorkerRuntime) -> RegistryFactory:
    def build() -> Any:
        try:
            from contentos.integrations.registry import create_integration_registry
        except ImportError as error:  # the layer is optional at runtime
            raise TrendDiscoveryUnavailableError(type(error).__name__) from None
        return create_integration_registry(runtime.settings, runtime.create_session)

    return build


class TrendDiscoverySyncRunner:
    """The whole sync as one bounded, provider-error-tolerant step."""

    def __init__(self, runtime: WorkerRuntime, registry_factory: RegistryFactory) -> None:
        self._runtime = runtime
        self._registry_factory = registry_factory

    def sync(self, *, now: datetime | None = None) -> dict[str, Any]:
        moment = now if now is not None else datetime.now(UTC)
        name = ProviderName.GOOGLE_TRENDS_BIGQUERY
        summary: dict[str, Any] = {
            "provider": name.value,
            "state": None,
            "error_class": None,
            "refresh_date": None,
            "top_terms": 0,
            "rising_terms": 0,
            "signals_created": 0,
            "skipped": None,
            "retry": False,
        }
        try:
            registry = self._registry_factory()
        except TrendDiscoveryUnavailableError as error:
            summary["state"] = ProviderState.NOT_CONFIGURED.value
            summary["error_class"] = f"integrations_unavailable:{error}"
            return summary
        provider = registry.get(name)
        if not provider.configured():
            summary["state"] = ProviderState.NOT_CONFIGURED.value
            summary["skipped"] = "not_configured"
            return summary

        from contentos.integrations.observations import (
            record_trend_term_observations,
            trend_terms_synced_for,
        )
        from contentos.integrations.sessions import bind_session
        from contentos.intelligence.trend_discovery import record_trend_discoveries

        session = self._runtime.create_session()
        try:
            country = provider.country
            try:
                with bind_session(session):
                    latest = provider.latest_refresh_date(country)
                    if latest is not None and not trend_terms_synced_for(session, latest, country):
                        top = provider.top_terms(latest, country)
                        rising = provider.rising_terms(latest, country)
                    else:
                        top, rising = [], []
            except ProviderError as error:
                registry.record_provider_error(session, name, error)
                session.commit()
                summary["state"] = error.kind.value
                summary["error_class"] = error.error_class
                summary["retry"] = error.kind in TRANSIENT_STATES
                return summary
            except Exception as error:  # noqa: BLE001 - bounded classification
                error_class = f"{name.value}_{type(error).__name__}".lower()[:64]
                registry.record_error(session, name, error_class, kind=ProviderState.ERROR)
                session.commit()
                summary["state"] = ProviderState.ERROR.value
                summary["error_class"] = error_class
                return summary

            summary["state"] = ProviderState.HEALTHY.value
            if latest is None:
                registry.record_success(session, name, synced=False)
                session.commit()
                summary["skipped"] = "no_recent_partition"
                return summary
            summary["refresh_date"] = latest.isoformat()
            if not top and not rising and trend_terms_synced_for(session, latest, country):
                registry.record_success(session, name, synced=False)
                session.commit()
                summary["skipped"] = "already_synced"
                return summary
            observations = [*top, *rising]
            created = record_trend_term_observations(session, observations)
            outcome = record_trend_discoveries(session, observations, now=moment)
            registry.record_success(session, name, synced=True)
            session.commit()
            summary.update(
                {
                    "top_terms": len(top),
                    "rising_terms": len(rising),
                    "signals_created": created,
                    "discovery": outcome.projection(),
                }
            )
            _logger.info(
                "trend_discovery_synced",
                refresh_date=latest.isoformat(),
                top=len(top),
                rising=len(rising),
                matched=len(outcome.matched),
            )
            return summary
        finally:
            session.close()


def register_trend_discovery_tasks(
    app: Celery,
    runtime: WorkerRuntime,
    *,
    registry_factory: RegistryFactory | None = None,
) -> None:
    runner = TrendDiscoverySyncRunner(
        runtime,
        registry_factory if registry_factory is not None else _default_registry_factory(runtime),
    )

    def sync_google_trends_bigquery(self: Any) -> dict[str, Any]:
        try:
            summary = runner.sync()
        except Exception as error:  # noqa: BLE001 - a bounded failure summary, never a crash
            _logger.warning(
                "trend_discovery_task_failed",
                task=SYNC_GOOGLE_TRENDS_BIGQUERY_TASK,
                error_type=type(error).__name__,
            )
            return {"status": "failed", "error_type": type(error).__name__}
        retries = int(getattr(getattr(self, "request", None), "retries", 0) or 0)
        if summary.get("retry") and retries < MAX_RETRIES:
            countdown = RETRY_BACKOFF_SECONDS * (2**retries)
            _logger.info(
                "trend_discovery_retry_scheduled", countdown=countdown, attempt=retries + 1
            )
            raise self.retry(countdown=countdown)
        return summary

    app.task(
        name=SYNC_GOOGLE_TRENDS_BIGQUERY_TASK,
        bind=True,
        shared=False,
        acks_late=True,
        max_retries=MAX_RETRIES,
    )(sync_google_trends_bigquery)


def trend_discovery_beat_schedule(settings: Any) -> dict[str, dict[str, Any]]:
    """One daily run (UTC) after Google's usual refresh; idempotent per date."""
    from celery.schedules import crontab  # type: ignore[import-untyped]

    hour = int(getattr(settings, "google_trends_bigquery_sync_hour_utc", 15))
    return {
        "trend-discovery-google-bigquery": {
            "task": SYNC_GOOGLE_TRENDS_BIGQUERY_TASK,
            "schedule": crontab(hour=hour, minute=30),
        }
    }
