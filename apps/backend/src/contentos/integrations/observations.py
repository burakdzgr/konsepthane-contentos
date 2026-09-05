"""Persist provider observations as provenance-complete SearchSignal rows.

Semrush volumes become `search_volume` signals; Google Trends and Pinterest
observations become `trend` signals whose value says `relative: true`.
Every value names the provider, the metric basis and the observation
time; UNKNOWN metrics are omitted (never 0). Idempotent through the
existing exact-observation hash. The caller commits.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime, time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from contentos.integrations.dto import (
    KeywordMetrics,
    PinterestKeywordTrend,
    TrendSummary,
    TrendTermObservation,
)
from contentos.integrations.enums import ProviderName
from contentos.signals.enums import SearchSignalType
from contentos.signals.models import SearchSignal
from contentos.signals.service import MAX_SUBJECT_LENGTH, _observation_hash

MARKET_LOCALES = {"TR": "tr-TR", "US": "en-US", "GB": "en-GB", "DE": "de-DE", "FR": "fr-FR"}
TREND_TERM_PROVIDER = ProviderName.GOOGLE_TRENDS_BIGQUERY.value
MAX_REGIONS_PERSISTED = 30


def record_keyword_metrics(session: Session, metrics: Sequence[KeywordMetrics]) -> int:
    """Append one `search_volume` signal per keyword with a KNOWN volume."""
    created = 0
    for metric in metrics:
        if metric.search_volume is None:
            continue  # UNKNOWN is never persisted as a number
        market = metric.database.upper()[:2] if len(metric.database) >= 2 else "TR"
        extra: dict[str, Any] = {}
        if metric.keyword_difficulty is not None:
            extra["keyword_difficulty"] = metric.keyword_difficulty
        if metric.cpc is not None:
            extra["cpc"] = metric.cpc
        if metric.competition is not None:
            extra["competition"] = metric.competition
        if metric.intent is not None:
            extra["intent"] = metric.intent
        value: dict[str, Any] = {
            "value": metric.search_volume,
            "unit": "searches_per_month",
            "basis": f"semrush phrase_these database={metric.database}",
            "period": "monthly",
            "provider": metric.provider,
            "metrics": extra,
            "observed_at": metric.observed_at.isoformat(),
        }
        if _append(
            session,
            signal_type=SearchSignalType.SEARCH_VOLUME,
            subject=metric.keyword,
            market=market,
            provider=metric.provider,
            value=value,
            observed_at=metric.observed_at,
        ):
            created += 1
    return created


def record_trend_summary(session: Session, summary: TrendSummary) -> bool:
    if summary.direction == "unknown":
        return False
    value: dict[str, Any] = {
        "observation": summary.direction,
        "scale": "relative_interest_0_100",
        "basis": f"google_trends interest_over_time geo={summary.geo} last12_vs_prev12",
        "period": "weekly",
        "provider": summary.provider,
        "relative": True,
        "observed_at": summary.observed_at.isoformat(),
    }
    if summary.seasonality_hint is not None:
        value["seasonality_hint"] = summary.seasonality_hint
    return _append(
        session,
        signal_type=SearchSignalType.TREND,
        subject=summary.term,
        market=summary.geo.upper()[:2],
        provider=summary.provider,
        value=value,
        observed_at=summary.observed_at,
    )


def record_pinterest_trend(session: Session, trend: PinterestKeywordTrend) -> bool:
    growth = trend.growth_pct_wow if trend.growth_pct_wow is not None else trend.growth_pct_yoy
    if growth is None:
        return False
    metrics: dict[str, Any] = {}
    if trend.growth_pct_wow is not None:
        metrics["growth_pct_wow"] = trend.growth_pct_wow
    if trend.growth_pct_yoy is not None:
        metrics["growth_pct_yoy"] = trend.growth_pct_yoy
    value: dict[str, Any] = {
        "observation": growth,
        "scale": "pct_growth_wow" if trend.growth_pct_wow is not None else "pct_growth_yoy",
        "basis": f"pinterest trends region={trend.region}",
        "period": "weekly",
        "provider": trend.provider,
        "relative": True,
        "metrics": metrics,
        "observed_at": trend.observed_at.isoformat(),
    }
    return _append(
        session,
        signal_type=SearchSignalType.TREND,
        subject=trend.keyword,
        market=trend.region.upper()[:2],
        provider=trend.provider,
        value=value,
        observed_at=trend.observed_at,
    )


def refresh_moment(refresh_date: date) -> datetime:
    """The dataset's refresh date as the observation instant (UTC midnight):
    the observation identity is the partition, not the sync time."""
    return datetime.combine(refresh_date, time.min, tzinfo=UTC)


def record_trend_term_observations(
    session: Session, observations: Sequence[TrendTermObservation]
) -> int:
    """Append one `trend` signal per (refresh date, country, term, type)
    from Google's public top/rising sets. The value carries the dataset,
    table, refresh date, rank/score/gain the dataset supplied (UNKNOWN ones
    omitted, never 0) and the per-region rows; re-running the same refresh
    date is idempotent through the observation hash."""
    created = 0
    for observation in observations:
        refresh = observation.refresh_date.isoformat()
        metrics: dict[str, Any] = {}
        if observation.rank is not None:
            metrics["rank"] = observation.rank
        if observation.latest_score is not None:
            metrics["latest_score"] = observation.latest_score
        if observation.peak_score is not None:
            metrics["peak_score"] = observation.peak_score
        if observation.percent_gain is not None:
            metrics["percent_gain"] = observation.percent_gain
        if observation.weeks_with_score is not None:
            metrics["weeks_with_score"] = observation.weeks_with_score
        value: dict[str, Any] = {
            "observation": observation.trend_type,
            "scale": "google_trends_public_dataset_rank",
            "basis": (
                f"{observation.dataset}.{observation.table} "
                f"country={observation.country_code} refresh_date={refresh}"
            ),
            "period": "daily_refresh",
            "provider": observation.provider,
            "relative": True,
            "dataset": observation.dataset,
            "table": observation.table,
            "query_version": observation.query_version,
            "trend_type": observation.trend_type,
            "country_code": observation.country_code,
            "refresh_date": refresh,
            "region_count": observation.region_count,
            "regions": [
                {
                    "code": region.region_code,
                    "name": region.region_name,
                    "rank": region.rank,
                    "latest_score": region.latest_score,
                    "percent_gain": region.percent_gain,
                }
                for region in observation.regions[:MAX_REGIONS_PERSISTED]
            ],
            **metrics,
        }
        if observation.first_week is not None:
            value["first_week"] = observation.first_week.isoformat()
        if observation.last_week is not None:
            value["last_week"] = observation.last_week.isoformat()
        moment = refresh_moment(observation.refresh_date)
        if _append(
            session,
            signal_type=SearchSignalType.TREND,
            subject=observation.term,
            market=observation.country_code,
            provider=observation.provider,
            value=value,
            observed_at=moment,
            as_of=moment,
        ):
            created += 1
    return created


def trend_terms_synced_for(session: Session, refresh_date: date, country: str) -> bool:
    """Has this refresh date already been persisted for the country?"""
    moment = refresh_moment(refresh_date)
    market = country.upper()[:2]
    found = session.execute(
        select(SearchSignal.id)
        .where(
            SearchSignal.provider == TREND_TERM_PROVIDER,
            SearchSignal.signal_type == SearchSignalType.TREND,
            SearchSignal.market == market,
            SearchSignal.as_of == moment,
        )
        .limit(1)
    ).scalar_one_or_none()
    return found is not None


def recent_trend_term_rows(
    session: Session, country: str, *, since: datetime, limit: int = 2000
) -> list[SearchSignal]:
    """Persisted top/rising rows for the country newer than `since`, newest
    refresh first (for the opportunity engine's discovery lookup)."""
    market = country.upper()[:2]
    return list(
        session.scalars(
            select(SearchSignal)
            .where(
                SearchSignal.provider == TREND_TERM_PROVIDER,
                SearchSignal.signal_type == SearchSignalType.TREND,
                SearchSignal.market == market,
                SearchSignal.observed_at >= since,
            )
            .order_by(SearchSignal.observed_at.desc(), SearchSignal.subject, SearchSignal.id)
            .limit(limit)
        )
    )


def freshness_for(session: Session, provider: ProviderName | str, subject: str) -> datetime | None:
    """Newest observation time for one provider+subject, or None (UNKNOWN)."""
    name = provider.value if isinstance(provider, ProviderName) else provider
    cleaned = " ".join(subject.split())
    if not cleaned:
        return None
    value = session.execute(
        select(func.max(SearchSignal.observed_at)).where(
            SearchSignal.provider == name,
            SearchSignal.subject == cleaned,
        )
    ).scalar_one_or_none()
    if value is None:
        return None
    # SQLite hands back naive timestamps; the column is timezone-aware UTC.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _append(
    session: Session,
    *,
    signal_type: SearchSignalType,
    subject: str,
    market: str,
    provider: str,
    value: dict[str, Any],
    observed_at: datetime,
    as_of: datetime | None = None,
) -> bool:
    cleaned_subject = " ".join(subject.split())[:MAX_SUBJECT_LENGTH]
    if not cleaned_subject:
        return False
    market_code = market.upper() if len(market) == 2 else "TR"
    locale = MARKET_LOCALES.get(market_code, f"und-{market_code}")
    observation_hash = _observation_hash(
        signal_type=signal_type,
        subject=cleaned_subject,
        locale=locale,
        market=market_code,
        provider=provider,
        value=value,
        confidence=None,
        observed_at=observed_at,
        as_of=as_of,
    )
    existing = session.execute(
        select(SearchSignal.id).where(SearchSignal.observation_hash == observation_hash)
    ).scalar_one_or_none()
    if existing is not None:
        return False
    try:
        with session.begin_nested():
            session.add(
                SearchSignal(
                    signal_type=signal_type,
                    subject=cleaned_subject,
                    locale=locale,
                    market=market_code,
                    provider=provider,
                    value=value,
                    confidence=None,
                    observed_at=observed_at,
                    as_of=as_of,
                    observation_hash=observation_hash,
                )
            )
    except IntegrityError:
        return False
    session.flush()
    return True
