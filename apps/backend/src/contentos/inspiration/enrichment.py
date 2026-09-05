"""Pre-decision opportunity enrichment: every signal family, every provider.

`enrich_opportunity` folds what ContentOS knows about ONE opportunity into a
single explainable block the inspiration engine evaluates and the operator
reads section by section (İçerik Değeri, Arama İstihbaratı, Konsepthane
Verisi, Araştırma). Three rules govern it:

- UNKNOWN is a value. A provider that is not configured, refused access,
  hit its quota, timed out or errored yields UNKNOWN plus its honest state;
  nothing is ever guessed or filled with 0.
- Families never fill each other in. Community need never raises search
  demand; search demand comes only from the base score's `search_demand`
  component or an independent Semrush observation; trend comes only from
  Google Trends / Pinterest.
- Bounded and fail-safe. At most `MAX_KEYWORDS` phrases go to Semrush (one
  batched, cached call); ONE trend call per provider on the primary phrase;
  every call is wrapped, and a failure is persisted on the provider's
  durable status through the registry, never raised into the pipeline.

A provider-free process (the API) passes no registry: providers are then
read from the durable `search_signals` history the worker recorded earlier
(`state = "stored"`, with the original observation time) or stay UNKNOWN
(`state = "not_requested"`). Only the worker composes a registry.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from contentos.discovery.models import DiscoveryItem
from contentos.fetching.snapshots import FetchSnapshot
from contentos.inspiration.models import InspirationSignal
from contentos.integrations.base import ProviderError, sanitize_error_class
from contentos.integrations.dto import KeywordMetrics, PinterestKeywordTrend, TrendSummary
from contentos.integrations.enums import ProviderName, ProviderState
from contentos.integrations.google_trends import GoogleTrendsProvider
from contentos.integrations.observations import (
    record_keyword_metrics,
    record_pinterest_trend,
    record_trend_summary,
)
from contentos.integrations.pinterest_trends import PinterestTrendsProvider
from contentos.integrations.registry import IntegrationRegistry
from contentos.integrations.semrush import SemrushProvider
from contentos.integrations.sessions import bind_session
from contentos.intelligence.enums import Band, SignalFamily
from contentos.intelligence.models import IntelligenceSignal
from contentos.intelligence.service import IntelligenceSignalService, bands_from_signals
from contentos.normalization.models import NormalizedDocument
from contentos.opportunities.models import EditorialOpportunity
from contentos.opportunities.repository import OpportunityRepository
from contentos.research.models import ResearchEvidence
from contentos.search_intent.models import SearchIntentAnalysis
from contentos.signals.enums import SearchSignalType
from contentos.signals.models import SearchSignal
from contentos.strategy.service import StrategyContext, StrategyService, normalize_phrase
from contentos.workflow.models import EditorialWorkItem

_logger = structlog.get_logger(__name__)

ENRICHMENT_VERSION = "1"

# --- Bounds -------------------------------------------------------------------
MAX_KEYWORDS = 8
# A phrase longer than this is a sentence, not a query anyone types.
MAX_KEYWORD_TOKENS = 6
MAX_KEYWORD_LENGTH = 100
# Durable-history lookups read at most this many recent provider rows.
MAX_STORED_ROWS = 200

# --- Semrush search-potential thresholds (monthly volume, KD 0..100) ---------
# STRONG: real monthly demand that is still winnable; MODERATE: enough demand
# with a reachable difficulty; anything with a KNOWN volume below that is
# WEAK. No volume -> UNKNOWN, never 0.
SEMRUSH_STRONG_MIN_VOLUME = 1000
SEMRUSH_STRONG_MAX_DIFFICULTY = 50.0
SEMRUSH_MODERATE_MIN_VOLUME = 200
SEMRUSH_MODERATE_MAX_DIFFICULTY = 70.0

# --- Pinterest visual-trend thresholds (percent growth, WoW preferred) ------
PINTEREST_STRONG_MIN_GROWTH_PCT = 20.0
PINTEREST_MODERATE_MIN_GROWTH_PCT = 5.0

# Provider states that are not vendor health but enrichment context.
STATE_NOT_REQUESTED = "not_requested"  # provider-free process, no durable row
STATE_STORED = "stored"  # value read from the durable observation history
STATE_NO_DATA = "no_data"  # provider answered, nothing for this phrase

TREND_UNKNOWN = "unknown"
EVIDENCE_SUFFICIENT = "sufficient"
EVIDENCE_INSUFFICIENT = "insufficient"
CANNIBALIZATION_UNKNOWN = "unknown"

# Keys stripped from the snapshot before hashing so a cache hit re-run of the
# same facts is the SAME evaluation (idempotent), while the persisted block
# keeps the full provenance.
_VOLATILE_KEYS = frozenset({"observed_at", "last_observed_at", "checked_at"})


@dataclass(frozen=True, slots=True)
class ProviderObservation:
    """Provenance of one provider read: who, in what state, when, where."""

    provider: str
    state: str
    error_class: str | None = None
    observed_at: datetime | None = None
    region: str | None = None

    def projection(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "state": self.state,
            "error_class": self.error_class,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "region": self.region,
        }

    @property
    def known(self) -> bool:
        return self.state in (ProviderState.HEALTHY.value, STATE_STORED)


@dataclass(frozen=True, slots=True)
class FamilyObservation:
    band: Band
    occurrences: int
    sources: int

    def projection(self) -> dict[str, Any]:
        return {"band": self.band.value, "occurrences": self.occurrences, "sources": self.sources}


@dataclass(frozen=True, slots=True)
class EnrichmentContext:
    """What the caller already computed; anything absent is derived here."""

    signals: tuple[InspirationSignal, ...] | None = None
    strategy: StrategyContext | None = None
    evidence_count: int | None = None


@dataclass(frozen=True, slots=True)
class EnrichmentResult:
    keywords: tuple[str, ...]
    search_potential: Band
    search_keyword: str | None
    search_volume: int | None
    keyword_difficulty: float | None
    semrush: ProviderObservation
    trend_direction: str
    trend_keyword: str | None
    google_trends: ProviderObservation
    visual_trend: Band
    visual_growth_pct: float | None
    pinterest: ProviderObservation
    families: dict[SignalFamily, FamilyObservation]
    historical_band: str
    historical_outcome: str | None
    historical_basis: dict[str, Any]
    cannibalization_status: str
    independent_sources: int
    signal_families: int
    evidence_count: int
    evidence_state: str
    inspiration_signal_count: int
    families_known: tuple[str, ...] = field(default_factory=tuple)

    def family_band(self, family: SignalFamily) -> Band:
        observation = self.families.get(family)
        return observation.band if observation is not None else Band.UNKNOWN

    @property
    def historical_positive(self) -> bool:
        return self.historical_outcome == "positive" and self.historical_band != Band.UNKNOWN.value

    def projection(self) -> dict[str, Any]:
        return {
            "version": ENRICHMENT_VERSION,
            "keywords": list(self.keywords),
            "search": {
                "potential_band": self.search_potential.value,
                "keyword": self.search_keyword,
                "search_volume": self.search_volume,
                "keyword_difficulty": self.keyword_difficulty,
                "provider": self.semrush.projection(),
            },
            "trend": {
                "direction": self.trend_direction,
                "keyword": self.trend_keyword,
                "provider": self.google_trends.projection(),
            },
            "visual_trend": {
                "band": self.visual_trend.value,
                "growth_pct": self.visual_growth_pct,
                "keyword": self.trend_keyword,
                "provider": self.pinterest.projection(),
            },
            "families": {
                family.value: observation.projection()
                for family, observation in sorted(
                    self.families.items(), key=lambda item: item[0].value
                )
            },
            "historical": {
                "band": self.historical_band,
                "outcome": self.historical_outcome,
                "basis": dict(self.historical_basis),
            },
            "cannibalization_status": self.cannibalization_status,
            "research": {
                "independent_sources": self.independent_sources,
                "signal_families": self.signal_families,
                "families_known": list(self.families_known),
                "evidence_count": self.evidence_count,
                "evidence_state": self.evidence_state,
                "inspiration_signal_count": self.inspiration_signal_count,
            },
        }

    def identity(self) -> dict[str, Any]:
        """The hash-stable subset: facts and states, no timestamps.

        A value read back from the durable history (`stored`) is the same
        fact the worker observed live (`healthy`), so the two states hash
        alike and an API re-evaluation over unchanged facts is a reuse."""
        stable = _without_volatile(self.projection())
        result: dict[str, Any] = dict(stable) if isinstance(stable, dict) else {}
        for section in ("search", "trend", "visual_trend"):
            provider = result.get(section, {}).get("provider")
            if isinstance(provider, dict) and provider.get("state") == STATE_STORED:
                provider["state"] = ProviderState.HEALTHY.value
        return result


def _without_volatile(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_volatile(item) for key, item in value.items() if key not in _VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [_without_volatile(item) for item in value]
    return value


# --- Keyword set -------------------------------------------------------------


def keyword_set(
    topic_summary: str, signal_titles: Iterable[str], strategy: StrategyContext
) -> tuple[str, ...]:
    """At most MAX_KEYWORDS natural-Turkish phrases, deduplicated on the
    normalized key. Strategy keywords lead (an operator chose them), then the
    topic, then inspiration concepts; sentence-length titles are skipped."""
    candidates: list[str] = [row.phrase for row in strategy.keywords]
    candidates.append(topic_summary)
    candidates.extend(signal_titles)
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        phrase = " ".join(candidate.split())[:MAX_KEYWORD_LENGTH]
        key = normalize_phrase(phrase)
        if not key or key in seen or len(key.split()) > MAX_KEYWORD_TOKENS:
            continue
        seen.add(key)
        result.append(phrase)
        if len(result) >= MAX_KEYWORDS:
            break
    return tuple(result)


# --- Banding rules (pure) -----------------------------------------------------


def semrush_band(search_volume: int | None, keyword_difficulty: float | None) -> Band:
    if search_volume is None:
        return Band.UNKNOWN
    if search_volume >= SEMRUSH_STRONG_MIN_VOLUME and (
        keyword_difficulty is None or keyword_difficulty <= SEMRUSH_STRONG_MAX_DIFFICULTY
    ):
        return Band.STRONG
    if search_volume >= SEMRUSH_MODERATE_MIN_VOLUME and (
        keyword_difficulty is None or keyword_difficulty <= SEMRUSH_MODERATE_MAX_DIFFICULTY
    ):
        return Band.MODERATE
    return Band.WEAK


def pinterest_band(growth_pct: float | None) -> Band:
    if growth_pct is None:
        return Band.UNKNOWN
    if growth_pct >= PINTEREST_STRONG_MIN_GROWTH_PCT:
        return Band.STRONG
    if growth_pct >= PINTEREST_MODERATE_MIN_GROWTH_PCT:
        return Band.MODERATE
    return Band.WEAK


def best_metric(metrics: Iterable[KeywordMetrics]) -> KeywordMetrics | None:
    """The keyword with the highest KNOWN volume; None when nothing is known."""
    known = [metric for metric in metrics if metric.search_volume is not None]
    if not known:
        return None
    return max(known, key=lambda metric: (metric.search_volume or 0, metric.keyword))


# --- Entry point ---------------------------------------------------------------


def enrich_opportunity(
    session: Session,
    opportunity_id: uuid.UUID,
    *,
    registry: IntegrationRegistry | None = None,
    context: EnrichmentContext | None = None,
    now: datetime | None = None,
) -> EnrichmentResult:
    """Gather every signal family and provider for one opportunity.

    Raises LookupError only when the opportunity (or its work item) does
    not exist; every provider or engine failure degrades to UNKNOWN.
    """
    opportunities = OpportunityRepository(session)
    opportunity = opportunities.get_by_id(opportunity_id)
    if opportunity is None:
        raise LookupError("opportunity not found")
    work_item = session.get(EditorialWorkItem, opportunity.work_item_id)
    if work_item is None:
        raise LookupError("opportunity work item not found")
    moment = now if now is not None else datetime.now(UTC)
    given = context or EnrichmentContext()

    signals = (
        list(given.signals)
        if given.signals is not None
        else list(
            session.scalars(
                select(InspirationSignal)
                .where(InspirationSignal.opportunity_id == opportunity.id)
                .order_by(InspirationSignal.created_at, InspirationSignal.id)
            )
        )
    )
    strategy = (
        given.strategy
        if given.strategy is not None
        else StrategyService(session).context_for_text(
            " ".join([opportunity.topic_summary, *(row.title for row in signals)]),
            locale=work_item.locale,
            market=work_item.market,
        )
    )
    evidence_count = (
        given.evidence_count
        if given.evidence_count is not None
        else _evidence_count(session, [row.normalized_document_id for row in signals])
    )
    keywords = keyword_set(opportunity.topic_summary, (row.title for row in signals), strategy)
    primary = keywords[0] if keywords else None

    semrush, metrics = _semrush(session, registry, keywords, moment)
    best = best_metric(metrics)
    google_trends, direction = _google_trends(session, registry, primary, work_item.market)
    pinterest, growth = _pinterest(session, registry, primary)

    family_rows = _family_rows(session, opportunity.id)
    families = _family_observations(family_rows)
    historical_band, historical_outcome, historical_basis = _historical(
        session, strategy, primary or opportunity.topic_summary
    )
    cannibalization = _cannibalization(session, opportunity.id)

    research_sources = _research_source_ids(session, opportunity)
    signal_sources = {row.source_id for row in family_rows if row.source_id is not None}
    providers_known = sum(
        1
        for known in (
            semrush.known and best is not None,
            google_trends.known and direction != TREND_UNKNOWN,
            pinterest.known and growth is not None,
        )
        if known
    )
    independent_sources = len(research_sources | signal_sources) + providers_known

    families_known: list[str] = []
    if signals:
        families_known.append(SignalFamily.INSPIRATION.value)
    for family, observation in families.items():
        if observation.band is not Band.UNKNOWN and family.value not in families_known:
            families_known.append(family.value)
    if best is not None and SignalFamily.SEARCH.value not in families_known:
        families_known.append(SignalFamily.SEARCH.value)
    if direction != TREND_UNKNOWN and SignalFamily.TREND.value not in families_known:
        families_known.append(SignalFamily.TREND.value)
    if growth is not None and SignalFamily.VISUAL_TREND.value not in families_known:
        families_known.append(SignalFamily.VISUAL_TREND.value)
    if (
        historical_band != Band.UNKNOWN.value
        and SignalFamily.HISTORICAL_PERFORMANCE.value not in families_known
    ):
        families_known.append(SignalFamily.HISTORICAL_PERFORMANCE.value)

    evidence_state = (
        EVIDENCE_SUFFICIENT
        if evidence_count > 0 and independent_sources >= 2
        else EVIDENCE_INSUFFICIENT
    )
    return EnrichmentResult(
        keywords=keywords,
        search_potential=semrush_band(
            best.search_volume if best else None,
            best.keyword_difficulty if best else None,
        ),
        search_keyword=best.keyword if best else None,
        search_volume=best.search_volume if best else None,
        keyword_difficulty=best.keyword_difficulty if best else None,
        semrush=semrush,
        trend_direction=direction,
        trend_keyword=primary,
        google_trends=google_trends,
        visual_trend=pinterest_band(growth),
        visual_growth_pct=growth,
        pinterest=pinterest,
        families=families,
        historical_band=historical_band,
        historical_outcome=historical_outcome,
        historical_basis=historical_basis,
        cannibalization_status=cannibalization,
        independent_sources=independent_sources,
        signal_families=len(families_known),
        evidence_count=evidence_count,
        evidence_state=evidence_state,
        inspiration_signal_count=len(signals),
        families_known=tuple(families_known),
    )


# --- Providers ------------------------------------------------------------------


def _record_failure(
    session: Session, registry: IntegrationRegistry, name: ProviderName, error: BaseException
) -> ProviderObservation:
    if isinstance(error, ProviderError):
        registry.record_provider_error(session, name, error)
        return ProviderObservation(name.value, error.kind.value, error_class=error.error_class)
    error_class = sanitize_error_class(name.value, type(error).__name__)
    _logger.warning(
        "opportunity_enrichment_provider_failed",
        provider=name.value,
        error_type=type(error).__name__,
    )
    registry.record_error(session, name, error_class, kind=ProviderState.ERROR)
    return ProviderObservation(name.value, ProviderState.ERROR.value, error_class=error_class)


def _unconfigured(provider: Any, name: ProviderName) -> ProviderObservation:
    # Cheap and network-free by contract: an unconfigured provider's
    # test_connection only names the missing variables.
    status = provider.test_connection()
    return ProviderObservation(name.value, status.state.value, error_class=status.last_error_class)


def _semrush(
    session: Session,
    registry: IntegrationRegistry | None,
    keywords: tuple[str, ...],
    now: datetime,
) -> tuple[ProviderObservation, list[KeywordMetrics]]:
    name = ProviderName.SEMRUSH
    if not keywords:
        return ProviderObservation(name.value, STATE_NOT_REQUESTED, error_class="no_keywords"), []
    if registry is None:
        return _stored_keyword_metrics(session, keywords)
    provider = registry.get(name)
    if not isinstance(provider, SemrushProvider):
        return ProviderObservation(name.value, STATE_NOT_REQUESTED), []
    if not provider.configured():
        return _unconfigured(provider, name), []
    try:
        with bind_session(session):
            metrics = provider.keyword_overview(list(keywords))
    except Exception as error:  # noqa: BLE001 - every failure is a typed UNKNOWN
        return _record_failure(session, registry, name, error), []
    registry.record_success(session, name)
    record_keyword_metrics(session, metrics)
    observed_at = max((metric.observed_at for metric in metrics), default=now)
    database = metrics[0].database if metrics else None
    state = ProviderState.HEALTHY.value if best_metric(metrics) is not None else STATE_NO_DATA
    return ProviderObservation(name.value, state, observed_at=observed_at, region=database), metrics


def _google_trends(
    session: Session,
    registry: IntegrationRegistry | None,
    primary: str | None,
    market: str,
) -> tuple[ProviderObservation, str]:
    name = ProviderName.GOOGLE_TRENDS
    if primary is None:
        return ProviderObservation(
            name.value, STATE_NOT_REQUESTED, error_class="no_keywords"
        ), TREND_UNKNOWN
    if registry is None:
        return _stored_trend(session, name, primary)
    provider = registry.get(name)
    if not isinstance(provider, GoogleTrendsProvider):
        return ProviderObservation(name.value, STATE_NOT_REQUESTED), TREND_UNKNOWN
    if not provider.configured():
        return _unconfigured(provider, name), TREND_UNKNOWN
    try:
        with bind_session(session):
            summary: TrendSummary = provider.summary(primary, geo=market)
    except Exception as error:  # noqa: BLE001
        return _record_failure(session, registry, name, error), TREND_UNKNOWN
    registry.record_success(session, name)
    record_trend_summary(session, summary)
    state = ProviderState.HEALTHY.value if summary.direction != TREND_UNKNOWN else STATE_NO_DATA
    return ProviderObservation(
        name.value, state, observed_at=summary.observed_at, region=summary.geo
    ), summary.direction


def _pinterest(
    session: Session, registry: IntegrationRegistry | None, primary: str | None
) -> tuple[ProviderObservation, float | None]:
    name = ProviderName.PINTEREST_TRENDS
    if primary is None:
        return ProviderObservation(name.value, STATE_NOT_REQUESTED, error_class="no_keywords"), None
    if registry is None:
        return _stored_pinterest(session, primary)
    provider = registry.get(name)
    if not isinstance(provider, PinterestTrendsProvider):
        return ProviderObservation(name.value, STATE_NOT_REQUESTED), None
    if not provider.configured():
        return _unconfigured(provider, name), None
    try:
        with bind_session(session):
            trend: PinterestKeywordTrend | None = provider.keyword_trend(primary)
    except Exception as error:  # noqa: BLE001
        return _record_failure(session, registry, name, error), None
    registry.record_success(session, name)
    if trend is None:
        return ProviderObservation(name.value, STATE_NO_DATA), None
    record_pinterest_trend(session, trend)
    growth = trend.growth_pct_wow if trend.growth_pct_wow is not None else trend.growth_pct_yoy
    state = ProviderState.HEALTHY.value if growth is not None else STATE_NO_DATA
    return ProviderObservation(
        name.value, state, observed_at=trend.observed_at, region=trend.region
    ), growth


# --- Durable history (provider-free processes) ---------------------------------


def _recent_signals(
    session: Session, provider: ProviderName, signal_type: SearchSignalType
) -> list[SearchSignal]:
    return list(
        session.scalars(
            select(SearchSignal)
            .where(SearchSignal.provider == provider.value, SearchSignal.signal_type == signal_type)
            .order_by(SearchSignal.observed_at.desc(), SearchSignal.id.desc())
            .limit(MAX_STORED_ROWS)
        )
    )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _stored_keyword_metrics(
    session: Session, keywords: tuple[str, ...]
) -> tuple[ProviderObservation, list[KeywordMetrics]]:
    name = ProviderName.SEMRUSH
    wanted = {normalize_phrase(keyword) for keyword in keywords}
    metrics: list[KeywordMetrics] = []
    seen: set[str] = set()
    for row in _recent_signals(session, name, SearchSignalType.SEARCH_VOLUME):
        key = normalize_phrase(row.subject)
        if key not in wanted or key in seen:
            continue
        seen.add(key)
        value = row.value
        volume = value.get("value")
        raw_extra = value.get("metrics")
        extra: dict[str, Any] = raw_extra if isinstance(raw_extra, dict) else {}
        difficulty = extra.get("keyword_difficulty")
        metrics.append(
            KeywordMetrics(
                keyword=row.subject,
                database=row.market.lower(),
                search_volume=int(volume) if isinstance(volume, int) else None,
                keyword_difficulty=float(difficulty)
                if isinstance(difficulty, (int, float))
                else None,
                cpc=None,
                competition=None,
                intent=None,
                observed_at=_aware(row.observed_at),
            )
        )
    if not metrics:
        return ProviderObservation(name.value, STATE_NOT_REQUESTED), []
    newest = max(metric.observed_at for metric in metrics)
    return ProviderObservation(
        name.value, STATE_STORED, observed_at=newest, region=metrics[0].database
    ), metrics


def _stored_trend(
    session: Session, name: ProviderName, primary: str
) -> tuple[ProviderObservation, str]:
    wanted = normalize_phrase(primary)
    for row in _recent_signals(session, name, SearchSignalType.TREND):
        if normalize_phrase(row.subject) != wanted:
            continue
        direction = row.value.get("observation")
        if isinstance(direction, str) and direction in ("rising", "stable", "falling"):
            return ProviderObservation(
                name.value, STATE_STORED, observed_at=_aware(row.observed_at), region=row.market
            ), direction
    return ProviderObservation(name.value, STATE_NOT_REQUESTED), TREND_UNKNOWN


def _stored_pinterest(session: Session, primary: str) -> tuple[ProviderObservation, float | None]:
    name = ProviderName.PINTEREST_TRENDS
    wanted = normalize_phrase(primary)
    for row in _recent_signals(session, name, SearchSignalType.TREND):
        if normalize_phrase(row.subject) != wanted:
            continue
        growth = row.value.get("observation")
        if isinstance(growth, (int, float)) and not isinstance(growth, bool):
            return ProviderObservation(
                name.value, STATE_STORED, observed_at=_aware(row.observed_at), region=row.market
            ), float(growth)
    return ProviderObservation(name.value, STATE_NOT_REQUESTED), None


# --- Signal families, history, Konsepthane data --------------------------------


def _family_rows(session: Session, opportunity_id: uuid.UUID) -> list[IntelligenceSignal]:
    try:
        return IntelligenceSignalService(session).signals_for_opportunity(opportunity_id)
    except Exception as error:  # noqa: BLE001 - the family store never fails evaluation
        _logger.warning("opportunity_enrichment_families_failed", error_type=type(error).__name__)
        return []


def _family_observations(rows: list[IntelligenceSignal]) -> dict[SignalFamily, FamilyObservation]:
    bands = bands_from_signals(rows)
    occurrences: dict[SignalFamily, int] = {}
    sources: dict[SignalFamily, set[uuid.UUID]] = {}
    for row in rows:
        occurrences[row.family] = occurrences.get(row.family, 0) + row.occurrence_count
        if row.source_id is not None:
            sources.setdefault(row.family, set()).add(row.source_id)
    return {
        family: FamilyObservation(
            band=bands[family],
            occurrences=occurrences.get(family, 0),
            sources=len(sources.get(family, ())),
        )
        for family in (
            SignalFamily.COMMUNITY_NEED,
            SignalFamily.MARKET,
            SignalFamily.COMPETITION,
            SignalFamily.TAXONOMY,
        )
    }


def _historical(
    session: Session, strategy: StrategyContext, theme_key: str
) -> tuple[str, str | None, dict[str, Any]]:
    """Priority-only history from the performance loop; absent -> unknown."""
    try:
        from contentos.performance.history import historical_signal_for
    except ImportError:
        return Band.UNKNOWN.value, None, {"reason": "history_unavailable"}
    cluster_id = strategy.clusters[0].id if strategy.clusters else None
    audience_id = strategy.audiences[0].id if strategy.audiences else None
    try:
        signal = historical_signal_for(
            session,
            cluster_id=cluster_id,
            audience_id=audience_id,
            theme_key=theme_key,
            content_format=None,
        )
    except Exception as error:  # noqa: BLE001
        _logger.warning("opportunity_enrichment_history_failed", error_type=type(error).__name__)
        return Band.UNKNOWN.value, None, {"reason": "history_failed"}
    if signal is None:
        return Band.UNKNOWN.value, None, {"reason": "no_history"}
    outcome = signal.outcome.value if signal.outcome is not None else None
    return signal.band.value, outcome, dict(signal.basis)


def _cannibalization(session: Session, opportunity_id: uuid.UUID) -> str:
    analysis = session.scalar(
        select(SearchIntentAnalysis)
        .where(SearchIntentAnalysis.opportunity_id == opportunity_id)
        .order_by(SearchIntentAnalysis.version.desc(), SearchIntentAnalysis.id.desc())
        .limit(1)
    )
    if analysis is None:
        return CANNIBALIZATION_UNKNOWN
    return analysis.cannibalization_status.value


def _research_source_ids(session: Session, opportunity: EditorialOpportunity) -> set[uuid.UUID]:
    document_ids = {opportunity.promotion_root_document_id}
    document_ids.update(
        row.normalized_document_id
        for row in OpportunityRepository(session).list_research_inputs(opportunity.id)
    )
    rows = session.execute(
        select(DiscoveryItem.source_id)
        .select_from(NormalizedDocument)
        .join(FetchSnapshot, FetchSnapshot.id == NormalizedDocument.fetch_snapshot_id)
        .join(DiscoveryItem, DiscoveryItem.id == FetchSnapshot.discovery_item_id)
        .where(NormalizedDocument.id.in_(document_ids))
    ).all()
    return {source_id for (source_id,) in rows if source_id is not None}


def _evidence_count(session: Session, document_ids: list[uuid.UUID]) -> int:
    if not document_ids:
        return 0
    return int(
        session.scalar(
            select(func.count())
            .select_from(ResearchEvidence)
            .where(ResearchEvidence.normalized_document_id.in_(document_ids))
        )
        or 0
    )
