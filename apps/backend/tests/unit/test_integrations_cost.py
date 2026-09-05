"""Cost control (durable cache + budget), Retry-After parsing, observations,
and the 0033 migration shape."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from integrations_fixtures import NOW, FixedClock
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from contentos.db.base import Base
from contentos.integrations.base import ProviderError, sanitize_error_class
from contentos.integrations.budget import BudgetedClient, DatabaseRequestBudget
from contentos.integrations.cache import DatabaseResponseCache, cache_key
from contentos.integrations.dto import KeywordMetrics, PinterestKeywordTrend, TrendSummary
from contentos.integrations.enums import ProviderName, ProviderState
from contentos.integrations.http import parse_retry_after
from contentos.integrations.models import ProviderCacheEntry, ProviderRequestLog
from contentos.integrations.observations import (
    freshness_for,
    record_keyword_metrics,
    record_pinterest_trend,
    record_trend_summary,
)
from contentos.integrations.sessions import bind_session, make_session_scope
from contentos.signals.models import SearchSignal

MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "versions"


def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_sanitize_error_class_is_bounded_and_safe() -> None:
    assert sanitize_error_class("semrush", "HTTP 401") == "semrush_http_401"
    assert sanitize_error_class("gsc", "a" * 100).startswith("gsc_")
    assert len(sanitize_error_class("gsc", "a" * 100)) == 64
    assert sanitize_error_class("x", "sk-SECRET/../key") == "x_sk_secret_key"


def test_parse_retry_after_accepts_seconds_and_http_dates() -> None:
    assert parse_retry_after("7", now=NOW) == 7.0
    assert parse_retry_after(None, now=NOW) is None
    assert parse_retry_after("garbage", now=NOW) is None
    later = (NOW + timedelta(seconds=90)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    parsed = parse_retry_after(later, now=NOW)
    assert parsed is not None and 89.0 <= parsed <= 91.0


def test_database_cache_and_budget_round_trip_and_expire() -> None:
    factory = session_factory()
    clock = FixedClock()
    scope = make_session_scope(factory)
    client = BudgetedClient(
        ProviderName.SEMRUSH,
        daily_budget=2,
        cache_ttl=timedelta(hours=1),
        cache=DatabaseResponseCache(scope),
        budget=DatabaseRequestBudget(scope),
        clock=clock,
    )
    calls: list[int] = []

    def fetch() -> dict[str, object]:
        calls.append(1)
        return {"rows": [{"Keyword": "parti"}]}

    assert client.cached(("phrase", "parti"), fetch) == {"rows": [{"Keyword": "parti"}]}
    assert client.cached(("phrase", "parti"), fetch) == {"rows": [{"Keyword": "parti"}]}
    assert calls == [1]
    assert client.requests_today() == 1
    with factory() as session:
        rows = session.execute(select(ProviderCacheEntry)).scalars().all()
        assert len(rows) == 1 and rows[0].provider == "semrush"
        assert rows[0].cache_key == cache_key("semrush", "phrase", "parti")
        log = session.execute(select(ProviderRequestLog)).scalar_one()
        assert log.request_count == 1 and log.day == NOW.date()

    clock.advance(hours=2)  # expired → refetch, second budget unit
    client.cached(("phrase", "parti"), fetch)
    assert calls == [1, 1]
    assert client.requests_today() == 2
    with pytest.raises(ProviderError) as info:
        client.cached(("phrase", "other"), fetch)
    assert info.value.kind is ProviderState.RATE_LIMITED
    assert calls == [1, 1]

    clock.advance(days=1)  # a new UTC day resets the counter
    assert client.requests_today() == 0
    client.cached(("phrase", "other"), fetch)
    assert calls == [1, 1, 1]


def test_bound_session_is_used_and_not_committed_by_the_store() -> None:
    factory = session_factory()
    scope = make_session_scope(factory)
    budget = DatabaseRequestBudget(scope)
    with factory() as session:
        with bind_session(session):
            assert budget.consume("semrush", day=NOW.date(), limit=5) == 1
            assert budget.consume("semrush", day=NOW.date(), limit=5) == 2
        session.rollback()
    with factory() as session:
        assert session.execute(select(ProviderRequestLog)).scalar_one_or_none() is None


def test_observations_persist_provenance_and_stay_idempotent() -> None:
    factory = session_factory()
    observed = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)
    metrics = [
        KeywordMetrics(
            keyword="doğum günü pastası",
            database="tr",
            search_volume=12100,
            keyword_difficulty=38.5,
            cpc=0.45,
            competition=None,
            intent="informational",
            observed_at=observed,
        ),
        KeywordMetrics(
            keyword="bilinmeyen",
            database="tr",
            search_volume=None,
            keyword_difficulty=None,
            cpc=None,
            competition=None,
            intent=None,
            observed_at=observed,
        ),
    ]
    with factory() as session:
        assert record_keyword_metrics(session, metrics) == 1
        assert record_keyword_metrics(session, metrics) == 0
        assert record_trend_summary(
            session,
            TrendSummary(
                term="doğum günü pastası",
                geo="TR",
                direction="rising",
                seasonality_hint="peak_month_06",
                observed_at=observed,
            ),
        )
        assert not record_trend_summary(
            session,
            TrendSummary(
                term="x", geo="TR", direction="unknown", seasonality_hint=None, observed_at=observed
            ),
        )
        assert record_pinterest_trend(
            session,
            PinterestKeywordTrend(
                keyword="doğum günü pastası",
                region="TR",
                weekly_points=[],
                growth_pct_wow=12.5,
                growth_pct_yoy=None,
                observed_at=observed,
            ),
        )
        assert not record_pinterest_trend(
            session,
            PinterestKeywordTrend(
                keyword="boş",
                region="TR",
                weekly_points=[],
                growth_pct_wow=None,
                growth_pct_yoy=None,
                observed_at=observed,
            ),
        )
        session.commit()

        signals = session.execute(select(SearchSignal)).scalars().all()
        assert len(signals) == 3
        by_provider = {signal.provider: signal for signal in signals}
        volume = by_provider["semrush"]
        assert volume.signal_type.value == "search_volume"
        assert volume.value["value"] == 12100
        assert volume.value["unit"] == "searches_per_month"
        assert "competition" not in volume.value["metrics"]
        assert volume.market == "TR" and volume.locale == "tr-TR"
        trend = by_provider["google_trends"]
        assert trend.signal_type.value == "trend"
        assert trend.value["relative"] is True
        assert trend.value["observation"] == "rising"
        pin = by_provider["pinterest_trends"]
        assert pin.value["scale"] == "pct_growth_wow"
        assert freshness_for(session, ProviderName.SEMRUSH, "doğum günü pastası") == observed
        assert freshness_for(session, "semrush", "bilinmeyen") is None


def test_0033_migration_creates_tables_with_bounded_state() -> None:
    source = (MIGRATION / "0033_create_integrations.py").read_text(encoding="utf-8")
    assert 'revision: str = "0033"' in source
    assert 'down_revision: str | None = "0032"' in source
    for table in ("integration_status", "provider_request_log", "provider_cache"):
        assert f'"{table}"' in source
    assert "ck_integration_status_state" in source
    assert "uq_provider_request_log_day" in source
    assert "uq_provider_cache_key" in source
    # No secret column ever: the cache key is a digest, the status a state.
    for forbidden in ("api_key", "access_token", "secret"):
        assert forbidden not in source
