"""Trend discovery: Google's Türkiye top / rising terms as Konsepthane signals.

Every term Google lists is persisted as a provenance-complete `SearchSignal`
(`contentos.integrations.observations.record_trend_term_observations`).
This module answers the editorial question on top of that: which of those
terms have anything to do with Konsepthane? A term is *relevant* when it
overlaps the strategy layer (active strategic keywords, clusters,
audiences) OR the domain vocabulary below. Strategy is a priority signal,
never a censor: an unexpected rising term that is clearly about parties,
celebrations, gifts or decoration is surfaced even when no strategic
keyword names it.

Relevant terms become `IntelligenceSignal` rows of family `trend`
(provider `google_trends_bigquery`, no source document) so the opportunity
engine picks them up through concept matching, and ContentOS' own
append-only history derives what the dataset does not say directly:
first/last observed, recurring, newly rising. Nothing here is a search
volume, and absence from the sets is never recorded as "low".
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from contentos.integrations.dto import TrendTermObservation
from contentos.integrations.enums import ProviderName
from contentos.intelligence.enums import SignalFamily
from contentos.intelligence.models import (
    MAX_CONCEPT_KEY_LENGTH,
    MAX_SUBJECT_LENGTH,
    IntelligenceSignal,
)
from contentos.intelligence.repository import IntelligenceSignalRepository
from contentos.intelligence.service import observation_hash
from contentos.signals.enums import SearchSignalType
from contentos.signals.models import SearchSignal
from contentos.strategy.service import StrategyService, normalize_phrase

PROVIDER = ProviderName.GOOGLE_TRENDS_BIGQUERY.value
DEFAULT_LOCALE = "tr-TR"
MAX_MATCH_TERMS = 12
MAX_SNAPSHOT_TERMS = 50
MAX_SNAPSHOT_ROWS = 400
MIN_TOKEN_LENGTH = 3

# Konsepthane's editorial domain (parties, celebrations, gifts, decoration),
# Turkish first, the English forms Google often lists for Türkiye as well.
# Matching is on normalized tokens (diacritics folded), never on raw text.
DOMAIN_VOCABULARY: tuple[str, ...] = (
    "parti",
    "party",
    "doğum günü",
    "birthday",
    "yaş günü",
    "baby shower",
    "bebek partisi",
    "cinsiyet partisi",
    "gender reveal",
    "diş buğdayı",
    "hoş geldin bebek",
    "gelin",
    "bride",
    "bekarlığa veda",
    "düğün",
    "wedding",
    "nişan",
    "söz",
    "kına",
    "evlenme teklifi",
    "sünnet",
    "mezuniyet",
    "kutlama",
    "davet",
    "davetiye",
    "dekorasyon",
    "dekor",
    "süsleme",
    "süs",
    "balon",
    "pasta",
    "kek",
    "kurabiye",
    "hediye",
    "hediyelik",
    "sürpriz",
    "tema",
    "kostüm",
    "yılbaşı",
    "yeni yıl",
    "sevgililer günü",
    "anneler günü",
    "babalar günü",
    "öğretmenler günü",
    "kadınlar günü",
    "cadılar bayramı",
    "halloween",
    "bayram",
    "ramazan",
    "iftar",
    "sofra",
    "masa süsleme",
    "çiçek",
    "buket",
    "piknik",
    "1 yaş",
    "ilk yaş",
    "çocuk partisi",
    "animasyon",
    "organizasyon",
    "etkinlik",
    "konsept",
)

_DOMAIN_TOKENS: tuple[tuple[str, tuple[str, ...]], ...] = tuple(
    (phrase, tuple(normalize_phrase(phrase).split())) for phrase in DOMAIN_VOCABULARY
)


def _tokens(term: str) -> tuple[str, ...]:
    return tuple(token for token in normalize_phrase(term).split() if token)


def domain_terms_for(term: str) -> tuple[str, ...]:
    """Vocabulary phrases whose every token appears in the term (in order
    for multi-token phrases), longest phrases first, bounded."""
    tokens = _tokens(term)
    if not tokens:
        return ()
    token_set = set(tokens)
    joined = " ".join(tokens)
    hits: list[str] = []
    for phrase, parts in _DOMAIN_TOKENS:
        if not parts:
            continue
        if len(parts) == 1:
            matched = parts[0] in token_set and (
                len(parts[0]) >= MIN_TOKEN_LENGTH or len(tokens) == 1 or parts[0].isdigit()
            )
        else:
            matched = f" {' '.join(parts)} " in f" {joined} "
        if matched and phrase not in hits:
            hits.append(phrase)
    hits.sort(key=lambda item: (-len(item), item))
    return tuple(hits[:MAX_MATCH_TERMS])


@dataclass(frozen=True, slots=True)
class TrendMatch:
    observation: TrendTermObservation
    strategy_keywords: tuple[str, ...]
    strategy_clusters: tuple[str, ...]
    audiences: tuple[str, ...]
    domain_terms: tuple[str, ...]

    @property
    def match_kind(self) -> str | None:
        if self.strategy_keywords or self.strategy_clusters or self.audiences:
            return "strategy"
        if self.domain_terms:
            return "domain"
        return None

    @property
    def relevant(self) -> bool:
        return self.match_kind is not None

    def projection(self) -> dict[str, Any]:
        return {
            "match_kind": self.match_kind,
            "strategy_keywords": list(self.strategy_keywords),
            "strategy_clusters": list(self.strategy_clusters),
            "audiences": list(self.audiences),
            "domain_terms": list(self.domain_terms),
        }


def match_observation(
    session: Session, observation: TrendTermObservation, *, locale: str = DEFAULT_LOCALE
) -> TrendMatch:
    """Strategy overlap (bounded, via the strategy service) plus domain
    vocabulary. Strategy contributes; it never excludes."""
    try:
        context = StrategyService(session).context_for_text(
            observation.term, locale=locale, market=observation.country_code
        )
        keywords = tuple(row.phrase for row in context.keywords)[:MAX_MATCH_TERMS]
        clusters = tuple(row.name for row in context.clusters)[:MAX_MATCH_TERMS]
        audiences = tuple(row.name for row in context.audiences)[:MAX_MATCH_TERMS]
    except Exception:  # noqa: BLE001 - strategy lookup never blocks discovery
        keywords, clusters, audiences = (), (), ()
    return TrendMatch(
        observation=observation,
        strategy_keywords=keywords,
        strategy_clusters=clusters,
        audiences=audiences,
        domain_terms=domain_terms_for(observation.term),
    )


@dataclass(frozen=True, slots=True)
class DiscoveryOutcome:
    matched: tuple[TrendMatch, ...]
    signals_created: int
    signals_updated: int
    terms_seen: int

    def projection(self) -> dict[str, Any]:
        return {
            "terms_seen": self.terms_seen,
            "matched": len(self.matched),
            "signals_created": self.signals_created,
            "signals_updated": self.signals_updated,
            "matched_terms": [
                {
                    "term": match.observation.term,
                    "trend_type": match.observation.trend_type,
                    **match.projection(),
                }
                for match in self.matched[:MAX_SNAPSHOT_TERMS]
            ],
        }


def record_trend_discoveries(
    session: Session,
    observations: Sequence[TrendTermObservation],
    *,
    now: datetime | None = None,
    locale: str = DEFAULT_LOCALE,
) -> DiscoveryOutcome:
    """Persist ONE `trend` intelligence signal per relevant term (top and
    rising merge into the same row; a re-run over the same refresh date
    is idempotent, a new refresh date bumps the occurrence count)."""
    moment = now if now is not None else datetime.now(UTC)
    repository = IntelligenceSignalRepository(session)
    matched: list[TrendMatch] = []
    created = 0
    updated = 0
    by_term: dict[str, list[TrendTermObservation]] = {}
    for observation in observations:
        by_term.setdefault(observation.term, []).append(observation)
    for term, group in sorted(by_term.items()):
        match = match_observation(session, group[0], locale=locale)
        if not match.relevant:
            continue
        matched.append(match)
        concept_key = normalize_phrase(term)[:MAX_CONCEPT_KEY_LENGTH]
        if not concept_key:
            continue
        digest = observation_hash(SignalFamily.TREND, concept_key, PROVIDER, None, None)
        refresh = max(item.refresh_date for item in group)
        value = _signal_value(group, match, refresh)
        existing = repository.get_by_hash(digest)
        if existing is not None:
            previous = existing.value.get("refresh_date")
            if previous != refresh.isoformat():
                existing.occurrence_count += 1
                existing.last_observed_at = moment
                value["first_refresh_date"] = existing.value.get("first_refresh_date") or previous
                existing.value = value
                updated += 1
            session.flush()
            continue
        value["first_refresh_date"] = refresh.isoformat()
        repository.add(
            IntelligenceSignal(
                family=SignalFamily.TREND,
                subject=term[:MAX_SUBJECT_LENGTH],
                concept_key=concept_key,
                locale=locale,
                market=group[0].country_code,
                source_id=None,
                normalized_document_id=None,
                opportunity_id=None,
                provider=PROVIDER,
                value=value,
                occurrence_count=1,
                first_observed_at=moment,
                last_observed_at=moment,
                observation_hash=digest,
            )
        )
        created += 1
    session.flush()
    return DiscoveryOutcome(
        matched=tuple(matched),
        signals_created=created,
        signals_updated=updated,
        terms_seen=len(by_term),
    )


def _signal_value(
    group: Sequence[TrendTermObservation], match: TrendMatch, refresh: date
) -> dict[str, Any]:
    types = sorted({item.trend_type for item in group})
    ranks = [item.rank for item in group if item.rank is not None]
    gains = [item.percent_gain for item in group if item.percent_gain is not None]
    scores = [item.latest_score for item in group if item.latest_score is not None]
    value: dict[str, Any] = {
        "provider": PROVIDER,
        "dataset": group[0].dataset,
        "trend_types": types,
        "refresh_date": refresh.isoformat(),
        "country_code": group[0].country_code,
        "region_count": max(item.region_count for item in group),
        **match.projection(),
    }
    if ranks:
        value["rank"] = min(ranks)
    if gains:
        value["percent_gain"] = max(gains)
    if scores:
        value["latest_score"] = max(scores)
    return value


# --- read side (API / admin) ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TrendTermSummary:
    term: str
    trend_type: str
    rank: int | None
    percent_gain: float | None
    latest_score: float | None
    region_count: int | None
    refresh_date: date
    matched: bool
    match_kind: str | None
    strategy_keywords: tuple[str, ...] = ()
    domain_terms: tuple[str, ...] = ()
    first_refresh_date: date | None = None
    occurrence_count: int | None = None


@dataclass(frozen=True, slots=True)
class DiscoverySnapshot:
    country: str
    refresh_date: date | None
    top: tuple[TrendTermSummary, ...] = ()
    rising: tuple[TrendTermSummary, ...] = ()
    matched: tuple[TrendTermSummary, ...] = ()
    total_terms: int = 0
    signal_count: int = 0
    unique_terms_ever: int = 0

    @property
    def synced(self) -> bool:
        return self.refresh_date is not None


def discovery_snapshot(session: Session, *, country: str = "TR") -> DiscoverySnapshot:
    """The latest synced refresh date for the country with its top / rising
    terms and which of them ContentOS deems relevant. DB-only, bounded."""
    market = country.strip().upper()[:2] or "TR"
    latest = session.execute(
        select(func.max(SearchSignal.as_of)).where(
            SearchSignal.provider == PROVIDER,
            SearchSignal.signal_type == SearchSignalType.TREND,
            SearchSignal.market == market,
        )
    ).scalar_one_or_none()
    signal_rows = list(
        session.scalars(
            select(IntelligenceSignal)
            .where(
                IntelligenceSignal.provider == PROVIDER,
                IntelligenceSignal.family == SignalFamily.TREND,
                IntelligenceSignal.market == market,
            )
            .order_by(IntelligenceSignal.last_observed_at.desc(), IntelligenceSignal.id)
            .limit(MAX_SNAPSHOT_ROWS)
        )
    )
    matches = {row.concept_key: row for row in signal_rows}
    if latest is None:
        return DiscoverySnapshot(
            country=market,
            refresh_date=None,
            signal_count=len(signal_rows),
            unique_terms_ever=len(matches),
        )
    rows = list(
        session.scalars(
            select(SearchSignal)
            .where(
                SearchSignal.provider == PROVIDER,
                SearchSignal.signal_type == SearchSignalType.TREND,
                SearchSignal.market == market,
                SearchSignal.as_of == latest,
            )
            .order_by(SearchSignal.subject, SearchSignal.id)
            .limit(MAX_SNAPSHOT_ROWS)
        )
    )
    top: list[TrendTermSummary] = []
    rising: list[TrendTermSummary] = []
    for row in rows:
        summary = _summary(row, matches)
        if summary is None:
            continue
        (rising if summary.trend_type == "rising" else top).append(summary)
    ordering = _rank_key
    top.sort(key=ordering)
    rising.sort(key=ordering)
    matched = [item for item in [*rising, *top] if item.matched]
    seen: set[str] = set()
    unique_matched: list[TrendTermSummary] = []
    for item in matched:
        if item.term in seen:
            continue
        seen.add(item.term)
        unique_matched.append(item)
    refresh = latest.date() if isinstance(latest, datetime) else latest
    return DiscoverySnapshot(
        country=market,
        refresh_date=refresh,
        top=tuple(top[:MAX_SNAPSHOT_TERMS]),
        rising=tuple(rising[:MAX_SNAPSHOT_TERMS]),
        matched=tuple(unique_matched[:MAX_SNAPSHOT_TERMS]),
        total_terms=len(rows),
        signal_count=len(signal_rows),
        unique_terms_ever=len(matches),
    )


def _rank_key(item: TrendTermSummary) -> tuple[int, str]:
    return (item.rank if item.rank is not None else 10**6, item.term)


def _summary(row: SearchSignal, matches: dict[str, IntelligenceSignal]) -> TrendTermSummary | None:
    value = row.value
    trend_type = value.get("trend_type") or value.get("observation")
    refresh_raw = value.get("refresh_date")
    if not isinstance(trend_type, str) or not isinstance(refresh_raw, str):
        return None
    try:
        refresh = date.fromisoformat(refresh_raw)
    except ValueError:
        return None
    signal = matches.get(normalize_phrase(row.subject))
    match_kind = signal.value.get("match_kind") if signal is not None else None
    keywords = signal.value.get("strategy_keywords") if signal is not None else None
    domain = signal.value.get("domain_terms") if signal is not None else None
    first_raw = signal.value.get("first_refresh_date") if signal is not None else None
    first: date | None = None
    if isinstance(first_raw, str):
        try:
            first = date.fromisoformat(first_raw)
        except ValueError:
            first = None
    return TrendTermSummary(
        term=row.subject,
        trend_type=trend_type,
        rank=_int(value.get("rank")),
        percent_gain=_float(value.get("percent_gain")),
        latest_score=_float(value.get("latest_score")),
        region_count=_int(value.get("region_count")),
        refresh_date=refresh,
        matched=signal is not None,
        match_kind=match_kind if isinstance(match_kind, str) else None,
        strategy_keywords=tuple(_strings(keywords)),
        domain_terms=tuple(_strings(domain)),
        first_refresh_date=first,
        occurrence_count=signal.occurrence_count if signal is not None else None,
    )


def _strings(value: Any) -> Iterable[str]:
    if not isinstance(value, list):
        return ()
    return [item for item in value if isinstance(item, str)]


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


__all__ = [
    "DOMAIN_VOCABULARY",
    "DiscoveryOutcome",
    "DiscoverySnapshot",
    "TrendMatch",
    "TrendTermSummary",
    "discovery_snapshot",
    "domain_terms_for",
    "match_observation",
    "record_trend_discoveries",
]
