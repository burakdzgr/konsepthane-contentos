"""Persist provider observations as provenance-complete SearchSignal rows.

Semrush volumes become `search_volume` signals; Google Trends and Pinterest
observations become `trend` signals whose value says `relative: true`.
Every value names the provider, the metric basis and the observation
time; UNKNOWN metrics are omitted (never 0). Idempotent through the
existing exact-observation hash. The caller commits.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from contentos.integrations.dto import KeywordMetrics, PinterestKeywordTrend, TrendSummary
from contentos.integrations.enums import ProviderName
from contentos.signals.enums import SearchSignalType
from contentos.signals.models import SearchSignal
from contentos.signals.service import MAX_SUBJECT_LENGTH, _observation_hash

MARKET_LOCALES = {"TR": "tr-TR", "US": "en-US", "GB": "en-GB", "DE": "de-DE", "FR": "fr-FR"}


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
        as_of=None,
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
                    as_of=None,
                    observation_hash=observation_hash,
                )
            )
    except IntegrityError:
        return False
    session.flush()
    return True
