"""Performance-loop worker tasks (Measure -> Learn -> Improve).

Provider syncs read through the integration registry (agent C's
`contentos.integrations`), which is imported LAZILY inside the task body
so this module — and the worker — imports even when the integration layer
is absent or broken. Every provider failure is caught, classified into a
bounded state (`not_configured`, `access_required`, `rate_limited`,
`degraded`, `error`), persisted through the registry's `record_error` /
`record_success`, and reported in the task summary; a task never crashes
on a provider, never writes a fabricated metric, and never publishes.
"""

import contextlib
import dataclasses
import uuid
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import structlog
from celery import Celery
from sqlalchemy.orm import Session

from contentos.performance.classifier import PerformancePolicy
from contentos.performance.enums import PerformanceProvider
from contentos.performance.history import HistoricalPerformanceService
from contentos.performance.models import PublishedContent
from contentos.performance.refresh import RefreshOpportunityService
from contentos.performance.service import PerformanceService, top_queries
from contentos.performance.suggestions import StrategySuggestionService
from contentos.worker.runtime import WorkerRuntime
from contentos.workflow.models import EditorialWorkItem

SYNC_SEARCH_CONSOLE_TASK = "contentos.performance.sync_search_console"
SYNC_ANALYTICS_TASK = "contentos.performance.sync_analytics"
REFRESH_MARKET_SIGNALS_TASK = "contentos.performance.refresh_market_signals"
ASSESS_TASK = "contentos.performance.assess"
DETECT_REFRESH_TASK = "contentos.performance.detect_refresh"
AGGREGATE_HISTORY_TASK = "contentos.performance.aggregate_history"
SUGGEST_STRATEGY_TASK = "contentos.performance.suggest_strategy"
SYNC_ALL_TASK = "contentos.performance.sync_all"

PERFORMANCE_TASK_NAMES = (
    SYNC_SEARCH_CONSOLE_TASK,
    SYNC_ANALYTICS_TASK,
    REFRESH_MARKET_SIGNALS_TASK,
    ASSESS_TASK,
    DETECT_REFRESH_TASK,
    AGGREGATE_HISTORY_TASK,
    SUGGEST_STRATEGY_TASK,
    SYNC_ALL_TASK,
)

SEARCH_CONSOLE_LOOKBACK_DAYS = 28
SEARCH_CONSOLE_LAG_DAYS = 2  # Search Console publishes data ~2 days late
ANALYTICS_LOOKBACK_DAYS = 28
MAX_CONTENTS_PER_RUN = 200
MAX_TOP_QUERIES = 20
MAX_KEYWORDS_PER_CONTENT = 3
DEFAULT_GEO = "TR"
ANALYTICS_METRICS = ["users", "sessions", "views", "engagement_rate", "key_events"]

PROVIDER_STATES = (
    "healthy",
    "not_configured",
    "access_required",
    "rate_limited",
    "degraded",
    "error",
)

RegistryFactory = Callable[[], Any]

_logger = structlog.get_logger("contentos.performance.worker")


class IntegrationsUnavailableError(Exception):
    """The integration layer cannot be imported or constructed."""


def _default_registry_factory(runtime: WorkerRuntime) -> RegistryFactory:
    def build() -> Any:
        try:
            from contentos.integrations.registry import create_integration_registry
        except ImportError as error:  # the layer is optional at runtime
            raise IntegrationsUnavailableError(type(error).__name__) from None
        return create_integration_registry(runtime.settings, runtime.create_session)

    return build


def _bound(session: Session) -> Any:
    """Bind the task session for the integration layer's durable cache and
    budget; a layer without that helper needs no binding."""
    try:
        from contentos.integrations.sessions import bind_session
    except ImportError:
        return contextlib.nullcontext()
    return bind_session(session)


def classify_provider_error(error: BaseException) -> tuple[str, str]:
    """(bounded state, sanitized error class) — never the provider message."""
    kind = getattr(error, "kind", None)
    kind_value = getattr(kind, "value", kind)
    if isinstance(kind_value, str) and kind_value in PROVIDER_STATES:
        state = kind_value
    else:
        name = type(error).__name__.lower()
        if "notconfigured" in name or "configuration" in name:
            state = "not_configured"
        elif "access" in name or "auth" in name or "permission" in name or "forbidden" in name:
            state = "access_required"
        elif "ratelimit" in name or "quota" in name or "budget" in name:
            state = "rate_limited"
        elif "timeout" in name:
            state = "degraded"
        else:
            state = "error"
    error_class = getattr(error, "error_class", None)
    return state, (
        str(error_class) if isinstance(error_class, str) and error_class else type(error).__name__
    )


def _provider_name(value: str) -> Any:
    try:
        from contentos.integrations.enums import ProviderName
    except ImportError:
        return value
    return ProviderName(value)


def _provider_state(value: str) -> Any:
    try:
        from contentos.integrations.enums import ProviderState
    except ImportError:
        return value
    return ProviderState(value)


def _persist_status(
    registry: Any, session: Session, provider_name: str, state: str, error_class: str | None
) -> None:
    """Persist the provider state THROUGH the registry (`record_error` /
    `record_success`); a registry without recorders leaves the task summary
    as the only record. Never raises."""
    try:
        if state == "healthy":
            success = getattr(registry, "record_success", None)
            if success is not None:
                success(session, _provider_name(provider_name))
        else:
            failure = getattr(registry, "record_error", None)
            if failure is not None:
                failure(
                    session,
                    _provider_name(provider_name),
                    error_class or "performance_sync_error",
                    kind=_provider_state(state),
                )
        session.commit()
    except Exception:  # noqa: BLE001 - status bookkeeping never breaks the sync
        session.rollback()
        _logger.warning("provider_status_persist_failed", provider=provider_name)


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _jsonable(getattr(value, field.name)) for field in dataclasses.fields(value)
        }
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_jsonable(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    inner = getattr(value, "value", None)
    if isinstance(inner, str):
        return inner
    return str(value)


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _int(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    return int(value) if isinstance(value, int | float) else 0


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    return float(value) if isinstance(value, int | float) else None


def _attr(row: Any, name: str) -> Any:
    if isinstance(row, dict):
        return row.get(name)
    return getattr(row, name, None)


def _provider(registry: Any, name: str) -> Any:
    getter = getattr(registry, "get", None)
    if getter is None:
        raise IntegrationsUnavailableError("registry has no get()")
    return getter(name)


def _path_of(url: str) -> str:
    parsed = urlparse(url)
    return parsed.path or "/"


def _unavailable(provider: str, error: BaseException) -> dict[str, Any]:
    return {
        "provider": provider,
        "state": "not_configured",
        "error_class": f"integrations_unavailable:{error}",
        "snapshots": 0,
        "contents": 0,
    }


class PerformanceSyncRunner:
    """Bounded, provider-error-tolerant steps; callable directly (sync_all)
    or one per task. Every step opens and closes its own session."""

    def __init__(self, runtime: WorkerRuntime, registry_factory: RegistryFactory) -> None:
        self._runtime = runtime
        self._registry_factory = registry_factory

    def _registry(self) -> Any:
        return self._registry_factory()

    def _provider_or_state(
        self, registry: Any, session: Session, name: str
    ) -> tuple[Any | None, dict[str, Any] | None]:
        try:
            return _provider(registry, name), None
        except Exception as error:  # noqa: BLE001 - bounded classification below
            state, error_class = classify_provider_error(error)
            _persist_status(registry, session, name, state, error_class)
            return None, {"provider": name, "state": state, "error_class": error_class}

    # --- search console / analytics (same shape) ----------------------------

    def sync_search_console(self, *, now: datetime | None = None) -> dict[str, Any]:
        moment = now if now is not None else datetime.now(UTC)
        end = moment.date() - timedelta(days=SEARCH_CONSOLE_LAG_DAYS)
        start = end - timedelta(days=SEARCH_CONSOLE_LOOKBACK_DAYS - 1)

        def fetch(provider: Any, content: PublishedContent) -> tuple[Any, Any]:
            assert content.canonical_url is not None
            daily = provider.search_analytics(
                start, end, ["date"], page_filter=content.canonical_url, row_limit=1000
            )
            queries = provider.search_analytics(
                start,
                end,
                ["query"],
                page_filter=content.canonical_url,
                row_limit=MAX_TOP_QUERIES,
            )
            return daily, queries

        def write(service: PerformanceService, content: PublishedContent, payload: Any) -> int:
            daily, queries = payload
            return _write_search_console(service, content, daily, queries, start, end, moment)

        return self._sync_per_content(PerformanceProvider.GOOGLE_SEARCH_CONSOLE.value, fetch, write)

    def sync_analytics(self, *, now: datetime | None = None) -> dict[str, Any]:
        moment = now if now is not None else datetime.now(UTC)
        end = moment.date() - timedelta(days=1)
        start = end - timedelta(days=ANALYTICS_LOOKBACK_DAYS - 1)

        def fetch(provider: Any, content: PublishedContent) -> Any:
            assert content.canonical_url is not None
            return provider.run_report(
                start,
                end,
                ["date"],
                list(ANALYTICS_METRICS),
                page_filter=_path_of(content.canonical_url),
            )

        def write(service: PerformanceService, content: PublishedContent, payload: Any) -> int:
            return _write_analytics(service, content, payload, start, end, moment)

        return self._sync_per_content(PerformanceProvider.GOOGLE_ANALYTICS.value, fetch, write)

    def _sync_per_content(
        self,
        name: str,
        fetch: Callable[[Any, PublishedContent], Any],
        write: Callable[[PerformanceService, PublishedContent, Any], int],
    ) -> dict[str, Any]:
        empty = {"snapshots": 0, "contents": 0, "skipped_without_url": 0}
        try:
            registry = self._registry()
        except IntegrationsUnavailableError as error:
            return {**_unavailable(name, error), **empty}
        snapshots = 0
        contents = 0
        skipped = 0
        session = self._runtime.create_session()
        try:
            provider, failure = self._provider_or_state(registry, session, name)
            if failure is not None or provider is None:
                return {**(failure or {}), **empty}
            outcome: dict[str, Any] = {"provider": name, "state": "healthy", "error_class": None}
            service = PerformanceService(session)
            for content in service.list_published()[:MAX_CONTENTS_PER_RUN]:
                if content.canonical_url is None:
                    skipped += 1  # "Yayın adresi bilinmiyor": nothing to ask a provider
                    continue
                contents += 1
                try:
                    with _bound(session):
                        payload = fetch(provider, content)
                except Exception as error:  # noqa: BLE001 - classified, never raised
                    state, error_class = classify_provider_error(error)
                    _persist_status(registry, session, name, state, error_class)
                    outcome = {"provider": name, "state": state, "error_class": error_class}
                    break
                snapshots += write(service, content, payload)
                session.commit()
            if outcome["state"] == "healthy" and contents > 0:
                _persist_status(registry, session, name, "healthy", None)
            session.commit()
        finally:
            session.close()
        return {
            **outcome,
            "snapshots": snapshots,
            "contents": contents,
            "skipped_without_url": skipped,
        }

    # --- market signals ----------------------------------------------------------

    def refresh_market_signals(self, *, now: datetime | None = None) -> dict[str, Any]:
        moment = now if now is not None else datetime.now(UTC)
        market_providers = (
            PerformanceProvider.SEMRUSH.value,
            PerformanceProvider.GOOGLE_TRENDS.value,
            PerformanceProvider.PINTEREST_TRENDS.value,
        )
        try:
            registry = self._registry()
        except IntegrationsUnavailableError as error:
            return {
                "providers": {name: _unavailable(name, error) for name in market_providers},
                "snapshots": 0,
                "contents": 0,
            }
        providers: dict[str, dict[str, Any]] = {}
        handles: dict[str, Any] = {}
        snapshots = 0
        contents = 0
        session = self._runtime.create_session()
        try:
            for provider_name in market_providers:
                handle, failure = self._provider_or_state(registry, session, provider_name)
                if failure is not None:
                    providers[provider_name] = {**failure, "snapshots": 0}
                else:
                    handles[provider_name] = handle
                    providers[provider_name] = {
                        "provider": provider_name,
                        "state": "healthy",
                        "error_class": None,
                        "snapshots": 0,
                    }
            service = PerformanceService(session)
            for content in service.list_published()[:MAX_CONTENTS_PER_RUN]:
                if not handles:
                    break
                keywords = _primary_keywords(service, content)
                if not keywords:
                    continue  # no REAL query yet: nothing to ask, nothing invented
                contents += 1
                geo = _market_of(session, content)
                for provider_name, handle in list(handles.items()):
                    provider = PerformanceProvider(provider_name)
                    if _has_today(service, content, provider, moment):
                        continue  # cache-aware: one observation per provider/day
                    try:
                        with _bound(session):
                            metrics = _market_metrics(provider_name, handle, keywords, geo)
                    except Exception as error:  # noqa: BLE001 - classified, never raised
                        state, error_class = classify_provider_error(error)
                        _persist_status(registry, session, provider_name, state, error_class)
                        providers[provider_name].update(
                            {"state": state, "error_class": error_class}
                        )
                        handles.pop(provider_name, None)
                        continue
                    if metrics is None:
                        continue
                    _, created = service.record_snapshot(
                        content.id,
                        provider,
                        period_start=moment.date(),
                        period_end=moment.date(),
                        metrics=metrics,
                        observed_at=moment,
                    )
                    if created:
                        snapshots += 1
                        providers[provider_name]["snapshots"] += 1
                session.commit()
            for provider_name in handles:
                if providers[provider_name]["snapshots"] > 0:
                    _persist_status(registry, session, provider_name, "healthy", None)
            session.commit()
        finally:
            session.close()
        return {"providers": providers, "snapshots": snapshots, "contents": contents}

    # --- learn / improve ------------------------------------------------------------

    def assess(self, *, now: datetime | None = None) -> dict[str, Any]:
        moment = now if now is not None else datetime.now(UTC)
        policy = PerformancePolicy.from_settings(self._runtime.settings)
        session = self._runtime.create_session()
        try:
            written = PerformanceService(session).assess_all(now=moment, policy=policy)
            session.commit()
        finally:
            session.close()
        return {"status": "completed", "assessments": len(written)}

    def detect_refresh(self, *, now: datetime | None = None) -> dict[str, Any]:
        moment = now if now is not None else datetime.now(UTC)
        session = self._runtime.create_session()
        try:
            proposed = RefreshOpportunityService(session).detect(now=moment)
            session.commit()
        finally:
            session.close()
        return {"status": "completed", "proposed": len(proposed)}

    def aggregate_history(self, *, now: datetime | None = None) -> dict[str, Any]:
        moment = now if now is not None else datetime.now(UTC)
        session = self._runtime.create_session()
        try:
            signals = HistoricalPerformanceService(session).aggregate(now=moment)
            session.commit()
        finally:
            session.close()
        return {"status": "completed", "signals": len(signals)}

    def suggest_strategy(self, *, now: datetime | None = None) -> dict[str, Any]:
        moment = now if now is not None else datetime.now(UTC)
        session = self._runtime.create_session()
        try:
            written = StrategySuggestionService(session).generate(now=moment)
            session.commit()
        finally:
            session.close()
        return {"status": "completed", "suggestions": len(written)}

    def sync_all(self, *, now: datetime | None = None) -> dict[str, Any]:
        """The operator's "sync now" chain, in order, in one process."""
        return {
            "search_console": self.sync_search_console(now=now),
            "analytics": self.sync_analytics(now=now),
            "market": self.refresh_market_signals(now=now),
            "assess": self.assess(now=now),
            "detect_refresh": self.detect_refresh(now=now),
            "aggregate_history": self.aggregate_history(now=now),
            "suggest_strategy": self.suggest_strategy(now=now),
        }


def _write_search_console(
    service: PerformanceService,
    content: PublishedContent,
    daily_rows: Iterable[Any],
    query_rows: Iterable[Any],
    start: date,
    end: date,
    moment: datetime,
) -> int:
    created_count = 0
    total_impressions = 0
    total_clicks = 0
    weighted_position = 0.0
    for row in daily_rows:
        day = _as_date(_attr(row, "date"))
        if day is None:
            continue
        impressions = _int(_attr(row, "impressions"))
        clicks = _int(_attr(row, "clicks"))
        position = _float(_attr(row, "position"))
        ctr = _float(_attr(row, "ctr"))
        total_impressions += impressions
        total_clicks += clicks
        if position is not None:
            weighted_position += position * impressions
        _, created = service.record_snapshot(
            content.id,
            PerformanceProvider.GOOGLE_SEARCH_CONSOLE,
            period_start=day,
            period_end=day,
            metrics={
                "impressions": impressions,
                "clicks": clicks,
                "ctr": ctr if ctr is not None else (clicks / impressions if impressions else None),
                "position": position,
            },
            observed_at=moment,
        )
        created_count += int(created)
    queries: list[dict[str, Any]] = [
        {
            "query": str(_attr(row, "query") or "").strip(),
            "clicks": _int(_attr(row, "clicks")),
            "impressions": _int(_attr(row, "impressions")),
            "position": _float(_attr(row, "position")),
        }
        for row in query_rows
        if str(_attr(row, "query") or "").strip()
    ]
    queries.sort(
        key=lambda entry: (-int(entry["clicks"]), -int(entry["impressions"]), str(entry["query"]))
    )
    if total_impressions > 0 or queries:
        _, created = service.record_snapshot(
            content.id,
            PerformanceProvider.GOOGLE_SEARCH_CONSOLE,
            period_start=start,
            period_end=end,
            metrics={
                "impressions": total_impressions,
                "clicks": total_clicks,
                "ctr": (total_clicks / total_impressions) if total_impressions else None,
                "position": (
                    round(weighted_position / total_impressions, 2) if total_impressions else None
                ),
                "top_queries": queries[:MAX_TOP_QUERIES],
            },
            observed_at=moment,
        )
        created_count += int(created)
    return created_count


def _write_analytics(
    service: PerformanceService,
    content: PublishedContent,
    rows: Iterable[Any],
    start: date,
    end: date,
    moment: datetime,
) -> int:
    created_count = 0
    totals = {"users": 0, "sessions": 0, "views": 0, "key_events": 0}
    engagement: list[float] = []
    for row in rows:
        day = _as_date(_attr(row, "date"))
        if day is None:
            continue
        metrics: dict[str, Any] = {
            "users": _int(_attr(row, "users")),
            "sessions": _int(_attr(row, "sessions")),
            "views": _int(_attr(row, "views")),
            "engagement_rate": _float(_attr(row, "engagement_rate")),
            "key_events": _int(_attr(row, "key_events")),
        }
        for key in totals:
            totals[key] += int(metrics[key] or 0)
        if metrics["engagement_rate"] is not None:
            engagement.append(float(metrics["engagement_rate"]))
        _, created = service.record_snapshot(
            content.id,
            PerformanceProvider.GOOGLE_ANALYTICS,
            period_start=day,
            period_end=day,
            metrics=metrics,
            observed_at=moment,
        )
        created_count += int(created)
    if any(totals.values()) or engagement:
        _, created = service.record_snapshot(
            content.id,
            PerformanceProvider.GOOGLE_ANALYTICS,
            period_start=start,
            period_end=end,
            metrics={
                **totals,
                "engagement_rate": (
                    round(sum(engagement) / len(engagement), 4) if engagement else None
                ),
            },
            observed_at=moment,
        )
        created_count += int(created)
    return created_count


def _primary_keywords(service: PerformanceService, content: PublishedContent) -> list[str]:
    queries = top_queries(
        service.snapshots_for(content.id, PerformanceProvider.GOOGLE_SEARCH_CONSOLE)
    )
    keywords: list[str] = []
    for entry in queries:
        query = str(entry.get("query", "")).strip()
        if query and query not in keywords:
            keywords.append(query)
        if len(keywords) >= MAX_KEYWORDS_PER_CONTENT:
            break
    return keywords


def _market_of(session: Session, content: PublishedContent) -> str:
    work_item = session.get(EditorialWorkItem, content.work_item_id)
    return work_item.market if work_item is not None else DEFAULT_GEO


def _has_today(
    service: PerformanceService,
    content: PublishedContent,
    provider: PerformanceProvider,
    moment: datetime,
) -> bool:
    today = moment.date()
    return any(
        row.period_start == today and row.period_end == today
        for row in service.snapshots_for(content.id, provider)
    )


def _market_metrics(
    provider_name: str, handle: Any, keywords: list[str], geo: str
) -> dict[str, Any] | None:
    if provider_name == PerformanceProvider.SEMRUSH.value:
        rows = [_jsonable(row) for row in (handle.keyword_overview(keywords) or [])]
        return {"keywords": rows} if rows else None
    if provider_name == PerformanceProvider.GOOGLE_TRENDS.value:
        summaries = [_jsonable(handle.summary(keyword, geo)) for keyword in keywords]
        summaries = [entry for entry in summaries if entry is not None]
        return {"terms": summaries} if summaries else None
    if provider_name == PerformanceProvider.PINTEREST_TRENDS.value:
        trends = [_jsonable(handle.keyword_trend(keyword, geo)) for keyword in keywords]
        trends = [entry for entry in trends if entry is not None]
        return {"keywords": trends} if trends else None
    return None


def register_performance_tasks(
    app: Celery,
    runtime: WorkerRuntime,
    *,
    registry_factory: RegistryFactory | None = None,
) -> None:
    """Explicitly register the performance tasks on ``app``."""
    runner = PerformanceSyncRunner(
        runtime,
        registry_factory if registry_factory is not None else _default_registry_factory(runtime),
    )

    def _guarded(step: Callable[[], dict[str, Any]], name: str) -> dict[str, Any]:
        try:
            return step()
        except Exception as error:  # noqa: BLE001 - a bounded failure summary, never a crash
            _logger.warning("performance_task_failed", task=name, error_type=type(error).__name__)
            return {"status": "failed", "error_type": type(error).__name__}

    def sync_search_console(self: Any) -> dict[str, Any]:
        return _guarded(runner.sync_search_console, SYNC_SEARCH_CONSOLE_TASK)

    def sync_analytics(self: Any) -> dict[str, Any]:
        return _guarded(runner.sync_analytics, SYNC_ANALYTICS_TASK)

    def refresh_market_signals(self: Any) -> dict[str, Any]:
        return _guarded(runner.refresh_market_signals, REFRESH_MARKET_SIGNALS_TASK)

    def assess(self: Any) -> dict[str, Any]:
        return _guarded(runner.assess, ASSESS_TASK)

    def detect_refresh(self: Any) -> dict[str, Any]:
        return _guarded(runner.detect_refresh, DETECT_REFRESH_TASK)

    def aggregate_history(self: Any) -> dict[str, Any]:
        return _guarded(runner.aggregate_history, AGGREGATE_HISTORY_TASK)

    def suggest_strategy(self: Any) -> dict[str, Any]:
        return _guarded(runner.suggest_strategy, SUGGEST_STRATEGY_TASK)

    def sync_all(self: Any) -> dict[str, Any]:
        return _guarded(runner.sync_all, SYNC_ALL_TASK)

    common_options: dict[str, Any] = {
        "bind": True,
        "shared": False,
        "acks_late": True,
        "max_retries": 0,
    }
    app.task(name=SYNC_SEARCH_CONSOLE_TASK, **common_options)(sync_search_console)
    app.task(name=SYNC_ANALYTICS_TASK, **common_options)(sync_analytics)
    app.task(name=REFRESH_MARKET_SIGNALS_TASK, **common_options)(refresh_market_signals)
    app.task(name=ASSESS_TASK, **common_options)(assess)
    app.task(name=DETECT_REFRESH_TASK, **common_options)(detect_refresh)
    app.task(name=AGGREGATE_HISTORY_TASK, **common_options)(aggregate_history)
    app.task(name=SUGGEST_STRATEGY_TASK, **common_options)(suggest_strategy)
    app.task(name=SYNC_ALL_TASK, **common_options)(sync_all)


def performance_beat_schedule(settings: Any) -> dict[str, dict[str, Any]]:
    """Celery beat entries (UTC): provider syncs first, learning after."""
    from celery.schedules import crontab  # type: ignore[import-untyped]

    sync_hour = int(getattr(settings, "performance_sync_hour_utc", 3))
    learn_hour = int(getattr(settings, "performance_learn_hour_utc", 4))
    market_hours = int(getattr(settings, "performance_market_interval_hours", 24))
    return {
        "performance-sync-search-console": {
            "task": SYNC_SEARCH_CONSOLE_TASK,
            "schedule": crontab(hour=sync_hour, minute=0),
        },
        "performance-sync-analytics": {
            "task": SYNC_ANALYTICS_TASK,
            "schedule": crontab(hour=sync_hour, minute=10),
        },
        "performance-refresh-market-signals": {
            "task": REFRESH_MARKET_SIGNALS_TASK,
            "schedule": timedelta(hours=market_hours),
        },
        "performance-assess": {
            "task": ASSESS_TASK,
            "schedule": crontab(hour=learn_hour, minute=0),
        },
        "performance-detect-refresh": {
            "task": DETECT_REFRESH_TASK,
            "schedule": crontab(hour=learn_hour, minute=10),
        },
        "performance-aggregate-history": {
            "task": AGGREGATE_HISTORY_TASK,
            "schedule": crontab(hour=learn_hour, minute=20),
        },
        "performance-suggest-strategy": {
            "task": SUGGEST_STRATEGY_TASK,
            "schedule": crontab(hour=learn_hour, minute=30),
        },
    }


def new_request_id() -> str:
    return f"perf-{uuid.uuid4()}"
