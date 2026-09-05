"""Bounded source-signal extraction and explainable editorial evaluation."""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from contentos.inspiration.enrichment import (
    STATE_NO_DATA,
    STATE_NOT_REQUESTED,
    STATE_STORED,
    TREND_UNKNOWN,
    EnrichmentContext,
    EnrichmentResult,
    ProviderObservation,
    enrich_opportunity,
)
from contentos.inspiration.enums import (
    InspirationBand,
    OpportunityRecommendation,
    SearchOpportunityBand,
    SignalExtractionMethod,
    TrendState,
)
from contentos.inspiration.models import InspirationEvaluation, InspirationSignal
from contentos.integrations.enums import ProviderState
from contentos.integrations.registry import IntegrationRegistry
from contentos.intelligence.enums import Band, SignalFamily
from contentos.normalization.models import NormalizedDocument
from contentos.opportunities.enums import (
    ComponentAvailability,
    ScoreBand,
    ScoreComponent,
    ScoreEligibility,
)
from contentos.opportunities.models import EditorialOpportunity, OpportunityScoreComponent
from contentos.opportunities.repository import OpportunityRepository
from contentos.research.models import ResearchEvidence
from contentos.strategy.service import StrategyContext, StrategyService, normalize_phrase
from contentos.workflow.models import EditorialWorkItem

ENGINE_NAME = "inspiration-quality"
# v5: pre-decision enrichment (every signal family + every provider) in the
# input snapshot; search opportunity may come from an independent Semrush
# observation; trend from Google Trends / Pinterest; the policy refuses
# PRODUCE on known-weak search and lets a positive history lift only a
# HIGH + commissionable HUMAN_REVIEW.
ENGINE_VERSION = "5"
SIGNAL_EXTRACTOR = "normalized-structure-signals"
SIGNAL_EXTRACTOR_VERSION = "1"
MAX_SIGNALS_PER_DOCUMENT = 12


@dataclass(frozen=True, slots=True)
class IntelligenceResult:
    evaluation: InspirationEvaluation
    signals_created: int
    created: bool


def recommendation_for(
    *,
    search: SearchOpportunityBand,
    inspiration: InspirationBand,
    has_evidence: bool,
    has_strategy_match: bool,
    commissionable: bool,
    base_ineligible: bool = False,
    historical_positive: bool = False,
) -> OpportunityRecommendation:
    """Explainable editorial recommendation over the durable signals.

    `search` is the effective search band: the base score's search_demand
    component when KNOWN, else an independent Semrush observation, else
    UNKNOWN. Community need is deliberately NOT an input here — people
    asking is not people searching.

    `commissionable` is the effective base score's eligibility — the ONLY
    thing the commissioning gate honours (commissioning_admits). PRODUCE is
    never recommended for a score the domain would refuse to commission;
    such an opportunity is routed to HUMAN_REVIEW so the inbox never shows
    an "İÇERİK ÜRET" verdict next to a decision the backend rejects.

    Known-WEAK search never yields PRODUCE (HUMAN_REVIEW instead). A
    positive history is a PRIORITY signal, not a filter: it lifts a
    HUMAN_REVIEW to PRODUCE only when inspiration is HIGH, evidence exists,
    the base is commissionable and search is not known-weak — i.e. when
    the only missing ingredient was a strategy match."""
    if search is SearchOpportunityBand.STRONG and inspiration is InspirationBand.LOW:
        return OpportunityRecommendation.CONTINUE_RESEARCH
    if base_ineligible and inspiration is InspirationBand.LOW:
        return OpportunityRecommendation.ELIMINATE
    producible = (
        inspiration is InspirationBand.HIGH
        and has_evidence
        and commissionable
        and search is not SearchOpportunityBand.WEAK
    )
    if producible and (has_strategy_match or historical_positive):
        return OpportunityRecommendation.PRODUCE
    if inspiration is InspirationBand.LOW or not has_evidence:
        return OpportunityRecommendation.CONTINUE_RESEARCH
    return OpportunityRecommendation.HUMAN_REVIEW


class InspirationIntelligenceService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._opportunities = OpportunityRepository(session)
        self._strategy = StrategyService(session)

    def extract_signals(self, opportunity_id: uuid.UUID) -> tuple[list[InspirationSignal], int]:
        opportunity = self._require_opportunity(opportunity_id)
        rows: list[InspirationSignal] = []
        created = 0
        for research_input in self._opportunities.list_research_inputs(opportunity.id):
            document = self._session.get(NormalizedDocument, research_input.normalized_document_id)
            if document is None:
                continue
            for position, title in enumerate(_candidate_signal_titles(document)):
                concept_key = normalize_phrase(title)[:240]
                if not concept_key:
                    continue
                signal_key = hashlib.sha256(f"{position}:{concept_key}".encode()).hexdigest()
                existing = self._session.scalar(
                    select(InspirationSignal).where(
                        InspirationSignal.opportunity_id == opportunity.id,
                        InspirationSignal.normalized_document_id == document.id,
                        InspirationSignal.extractor_name == SIGNAL_EXTRACTOR,
                        InspirationSignal.extractor_version == SIGNAL_EXTRACTOR_VERSION,
                        InspirationSignal.signal_key == signal_key,
                    )
                )
                if existing is not None:
                    rows.append(existing)
                    continue
                signal = InspirationSignal(
                    opportunity_id=opportunity.id,
                    normalized_document_id=document.id,
                    signal_key=signal_key,
                    concept_key=concept_key,
                    title=title[:300],
                    detail=None,
                    extraction_method=SignalExtractionMethod.DETERMINISTIC,
                    extractor_name=SIGNAL_EXTRACTOR,
                    extractor_version=SIGNAL_EXTRACTOR_VERSION,
                    source_locator={"kind": "normalized_structure", "position": position},
                )
                self._session.add(signal)
                self._session.flush()
                rows.append(signal)
                created += 1
        return rows, created

    def evaluate(
        self,
        opportunity_id: uuid.UUID,
        *,
        evaluated_at: datetime | None = None,
        registry: IntegrationRegistry | None = None,
    ) -> IntelligenceResult:
        """Evaluate one opportunity from every signal family and provider.

        `registry` is the worker's provider registry; the API process passes
        none and stays provider-free (durable provider history is still
        read). Enrichment is fail-safe: nothing here raises for a provider.
        """
        opportunity = self._require_opportunity(opportunity_id)
        signals, signals_created = self.extract_signals(opportunity.id)
        work_item = self._session.get(EditorialWorkItem, opportunity.work_item_id)
        if work_item is None:
            raise LookupError("opportunity work item not found")
        joined_text = " ".join([opportunity.topic_summary, *(row.title for row in signals)])
        strategy = self._strategy.context_for_text(
            joined_text, locale=work_item.locale, market=work_item.market
        )
        factors = _evaluate_factors(signals, strategy)
        inspiration = _overall_band(factors)
        moment = evaluated_at or datetime.now(UTC)
        evidence_count = (
            int(
                self._session.scalar(
                    select(func.count())
                    .select_from(ResearchEvidence)
                    .where(
                        ResearchEvidence.normalized_document_id.in_(
                            [row.normalized_document_id for row in signals]
                        )
                    )
                )
                or 0
            )
            if signals
            else 0
        )
        enrichment = enrich_opportunity(
            self._session,
            opportunity.id,
            registry=registry,
            context=EnrichmentContext(
                signals=tuple(signals), strategy=strategy, evidence_count=evidence_count
            ),
            now=moment,
        )
        # Search demand: the base component when KNOWN, else the independent
        # Semrush potential. Never community need, never trend.
        base_search = self._search_opportunity(opportunity.id)
        search = (
            base_search
            if base_search is not SearchOpportunityBand.UNKNOWN
            else SearchOpportunityBand(enrichment.search_potential.value)
        )
        trend_state = (
            TrendState.KNOWN
            if enrichment.trend_direction != TREND_UNKNOWN
            or enrichment.trend_discovery.observed
            or enrichment.visual_trend is not Band.UNKNOWN
            else TrendState.UNKNOWN
        )
        effective_score = self._opportunities.get_effective_score(opportunity.id)
        commissionable = (
            effective_score is not None
            and effective_score.eligibility is ScoreEligibility.COMMISSIONABLE
        )
        recommendation = recommendation_for(
            search=search,
            inspiration=inspiration,
            has_evidence=evidence_count > 0,
            has_strategy_match=bool(strategy.keywords or strategy.clusters),
            commissionable=commissionable,
            base_ineligible=effective_score is not None
            and effective_score.overall_band is ScoreBand.INELIGIBLE,
            historical_positive=enrichment.historical_positive,
        )
        missing = _missing_signals(search, trend_state, signals, enrichment)
        intelligence = enrichment.projection()
        snapshot: dict[str, Any] = {
            "opportunity_id": str(opportunity.id),
            "signal_ids": sorted(str(row.id) for row in signals),
            "concept_count": len({row.concept_key for row in signals}),
            "strategy": strategy.projection(),
            "search_opportunity": search.value,
            "trend_state": trend_state.value,
            "evidence_count": evidence_count,
            "score_eligibility": (
                effective_score.eligibility.value if effective_score is not None else None
            ),
            "engine": ENGINE_NAME,
            "engine_version": ENGINE_VERSION,
            "intelligence": intelligence,
        }
        # Identity excludes provider timestamps: a re-run over the same facts
        # (cache hit, same durable rows) is the SAME evaluation.
        hashed = {**snapshot, "intelligence": enrichment.identity()}
        snapshot_hash = hashlib.sha256(
            json.dumps(hashed, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
        existing = self._session.scalar(
            select(InspirationEvaluation).where(
                InspirationEvaluation.opportunity_id == opportunity.id,
                InspirationEvaluation.engine_name == ENGINE_NAME,
                InspirationEvaluation.engine_version == ENGINE_VERSION,
                InspirationEvaluation.input_snapshot_hash == snapshot_hash,
            )
        )
        if existing is not None:
            return IntelligenceResult(existing, signals_created, False)
        evaluation = InspirationEvaluation(
            opportunity_id=opportunity.id,
            engine_name=ENGINE_NAME,
            engine_version=ENGINE_VERSION,
            inspiration_band=inspiration,
            search_opportunity=search,
            trend_state=trend_state,
            recommendation=recommendation,
            rationale=_rationale(
                recommendation,
                inspiration,
                search,
                evidence_count,
                strategy,
                enrichment,
                commissionable=commissionable,
                evaluated_at=moment,
            ),
            factors=factors,
            strategy_context=strategy.projection(),
            missing_signals=missing,
            input_snapshot=snapshot,
            input_snapshot_hash=snapshot_hash,
            evaluated_at=moment,
        )
        self._session.add(evaluation)
        self._session.flush()
        return IntelligenceResult(evaluation, signals_created, True)

    def latest_evaluation(self, opportunity_id: uuid.UUID) -> InspirationEvaluation | None:
        return self._session.scalar(
            select(InspirationEvaluation)
            .where(InspirationEvaluation.opportunity_id == opportunity_id)
            .order_by(InspirationEvaluation.evaluated_at.desc(), InspirationEvaluation.id.desc())
            .limit(1)
        )

    def strategy_context_for_opportunity(self, opportunity_id: uuid.UUID) -> dict[str, object]:
        evaluation = self.latest_evaluation(opportunity_id)
        return evaluation.strategy_context if evaluation is not None else {}

    def _search_opportunity(self, opportunity_id: uuid.UUID) -> SearchOpportunityBand:
        score = self._opportunities.get_effective_score(opportunity_id)
        if score is None:
            return SearchOpportunityBand.UNKNOWN
        component = self._session.scalar(
            select(OpportunityScoreComponent).where(
                OpportunityScoreComponent.score_id == score.id,
                OpportunityScoreComponent.component == ScoreComponent.SEARCH_DEMAND,
            )
        )
        if (
            component is None
            or component.availability is not ComponentAvailability.KNOWN
            or component.value is None
        ):
            return SearchOpportunityBand.UNKNOWN
        if component.value >= 0.7:
            return SearchOpportunityBand.STRONG
        if component.value >= 0.4:
            return SearchOpportunityBand.MODERATE
        return SearchOpportunityBand.WEAK

    def _require_opportunity(self, opportunity_id: uuid.UUID) -> EditorialOpportunity:
        row = self._opportunities.get_by_id(opportunity_id)
        if row is None:
            raise LookupError("opportunity not found")
        return row


def _candidate_signal_titles(document: NormalizedDocument) -> list[str]:
    candidates: list[str] = []
    if document.title and document.title.strip():
        candidates.append(document.title.strip())
    for heading in document.headings:
        value = heading.get("text") or heading.get("heading") or heading.get("title")
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip())
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = normalize_phrase(candidate)
        if key and key not in seen:
            seen.add(key)
            result.append(candidate)
        if len(result) >= MAX_SIGNALS_PER_DOCUMENT:
            break
    return result


def _evaluate_factors(
    signals: list[InspirationSignal], strategy: StrategyContext
) -> dict[str, Any]:
    text = normalize_phrase(" ".join(row.title for row in signals))
    tokens = text.split()
    visual_words = {
        "balon",
        "balloon",
        "cake",
        "pasta",
        "masa",
        "table",
        "dekor",
        "decor",
        "frozen",
        "wedding",
        "dugun",
        "bride",
    }
    emotional_words = {
        "surpriz",
        "surprise",
        "romantik",
        "romantic",
        "birthday",
        "dogum",
        "baby",
        "proposal",
        "teklif",
    }
    generic_words = {"ideas", "fikirleri", "party", "parti", "guide", "rehber"}
    factor_values = {
        "novelty": 4 if len(set(tokens) - generic_words) >= 7 else 2,
        "usefulness": 3 if signals else None,
        "specificity": 4 if any(char.isdigit() for char in text) or len(tokens) >= 7 else 2,
        "visual_potential": 5 if visual_words & set(tokens) else 3,
        "shareability": 4 if (visual_words | emotional_words) & set(tokens) else 2,
        "emotional_impact": 4 if emotional_words & set(tokens) else 2,
        "audience_fit": 5 if strategy.audiences or strategy.keywords else 3 if signals else None,
        "turkish_market_applicability": 3 if signals else None,
        "variation_potential": 4
        if len({row.concept_key for row in signals}) >= 3
        else 2
        if signals
        else None,
        "strategic_fit": 5 if strategy.keywords else 3 if strategy.clusters else 1,
    }
    return {
        name: {"value": value, "basis": _factor_basis(name, value)}
        for name, value in factor_values.items()
    }


def _factor_basis(name: str, value: int | None) -> str:
    if value is None:
        return "Bu faktör için yeterli sinyal yok."
    labels = {1: "çok zayıf", 2: "zayıf", 3: "orta", 4: "güçlü", 5: "çok güçlü"}
    return f"Kaynak başlığı, bölüm sinyalleri ve strateji eşleşmesine göre {labels[value]} editoryal değerlendirme."


def _overall_band(factors: dict[str, Any]) -> InspirationBand:
    values = [entry["value"] for entry in factors.values() if entry["value"] is not None]
    if not values:
        return InspirationBand.UNKNOWN
    average = sum(values) / len(values)
    if average >= 3.8:
        return InspirationBand.HIGH
    if average >= 2.5:
        return InspirationBand.MEDIUM
    return InspirationBand.LOW


def _missing_signals(
    search: SearchOpportunityBand,
    trend_state: TrendState,
    signals: list[InspirationSignal],
    enrichment: EnrichmentResult,
) -> list[str]:
    missing: list[str] = []
    if search is SearchOpportunityBand.UNKNOWN:
        missing.append("measured_search_demand")
    if trend_state is TrendState.UNKNOWN:
        missing.append("trend_signal")
    if not signals:
        missing.append("inspiration_signals")
    if enrichment.family_band(SignalFamily.COMMUNITY_NEED) is Band.UNKNOWN:
        missing.append("community_need")
    if enrichment.family_band(SignalFamily.COMPETITION) is Band.UNKNOWN:
        missing.append("competition")
    if enrichment.historical_band == Band.UNKNOWN.value:
        missing.append("historical_performance")
    return missing


# Operator-facing rationale is Turkish end to end; enum values never leak.
_TR_BAND = {
    "very_high": "çok yüksek",
    "high": "yüksek",
    "medium": "orta",
    "low": "düşük",
    "strong": "güçlü",
    "moderate": "orta",
    "weak": "zayıf",
    "unknown": "bilinmiyor",
}
_TR_DIRECTION = {
    "rising": "yükseliyor",
    "stable": "stabil",
    "falling": "düşüyor",
    "unknown": "bilinmiyor",
}
_TR_OUTCOME = {"positive": "olumlu", "neutral": "nötr", "negative": "olumsuz"}
_TR_PROVIDER_STATE = {
    ProviderState.NOT_CONFIGURED.value: "yapılandırılmadı",
    ProviderState.ACCESS_REQUIRED.value: "erişim gerekli",
    ProviderState.RATE_LIMITED.value: "kota sınırında",
    ProviderState.DEGRADED.value: "kısıtlı (zaman aşımı/servis hatası)",
    ProviderState.ERROR.value: "hata",
    STATE_NOT_REQUESTED: "bu süreçte sorgulanmadı",
    STATE_NO_DATA: "bu ifade için veri yok",
}


def _tr_number(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _tr_freshness(observed_at: datetime | None, now: datetime) -> str:
    if observed_at is None:
        return "zaman bilinmiyor"
    days = max((now - observed_at).days, 0)
    if days == 0:
        return "bugün"
    if days == 1:
        return "dün"
    return f"{days} gün önce"


def _provider_state_tr(observation: ProviderObservation) -> str:
    return _TR_PROVIDER_STATE.get(observation.state, "bilinmiyor")


def _bases(
    enrichment: EnrichmentResult,
    evidence_count: int,
    strategy: StrategyContext,
    now: datetime,
) -> list[str]:
    """Concrete Turkish bases, one per section, unknowns named honestly."""
    bases: list[str] = []
    semrush = enrichment.semrush
    if enrichment.search_volume is not None:
        difficulty = (
            f", zorluk {enrichment.keyword_difficulty:.0f}"
            if enrichment.keyword_difficulty is not None
            else ", zorluk bilinmiyor"
        )
        stored = " kayıtlı gözlem," if semrush.state == STATE_STORED else ""
        bases.append(
            f"Semrush: hacim {_tr_number(enrichment.search_volume)}{difficulty} "
            f"({semrush.region or 'tr'},{stored} {_tr_freshness(semrush.observed_at, now)})"
        )
    else:
        bases.append(f"Semrush: {_provider_state_tr(semrush)}")
    trends = enrichment.google_trends
    if enrichment.trend_direction != TREND_UNKNOWN:
        bases.append(
            f"Google Trends: {_TR_DIRECTION[enrichment.trend_direction]} "
            f"({trends.region or 'TR'}, {_tr_freshness(trends.observed_at, now)})"
        )
    else:
        bases.append(f"Google Trends: {_provider_state_tr(trends)}")
    discovery = enrichment.trend_discovery
    if discovery.observed:
        kind = "yükselen" if discovery.trend_type == "rising" else "en çok aranan"
        rank = f", sıra {discovery.rank}" if discovery.rank is not None else ""
        bases.append(
            f"Google Trend Keşfi (BigQuery): '{discovery.term}' Türkiye {kind} sorgularında "
            f"gözlendi ({discovery.refresh_date or 'tarih bilinmiyor'}{rank})"
        )
    elif discovery.state == "not_observed":
        bases.append(
            "Google Trend Keşfi (BigQuery): günlük top/rising listelerinde gözlenmedi "
            "(tek başına düşük trend demek değildir)"
        )
    else:
        bases.append(f"Google Trend Keşfi (BigQuery): {_provider_state_tr(discovery.provider)}")
    pinterest = enrichment.pinterest
    if enrichment.visual_growth_pct is not None:
        bases.append(
            f"Pinterest: {_TR_BAND[enrichment.visual_trend.value]} "
            f"(%{enrichment.visual_growth_pct:.0f} büyüme, "
            f"{_tr_freshness(pinterest.observed_at, now)})"
        )
    else:
        bases.append(f"Pinterest: {_provider_state_tr(pinterest)}")
    community = enrichment.families.get(SignalFamily.COMMUNITY_NEED)
    if community is not None and community.band is not Band.UNKNOWN:
        bases.append(
            f"Topluluk ihtiyacı: {_TR_BAND[community.band.value]} "
            f"({community.sources} kaynak, {community.occurrences} gözlem)"
        )
    else:
        bases.append("Topluluk ihtiyacı: bilinmiyor")
    competition = enrichment.families.get(SignalFamily.COMPETITION)
    if competition is not None and competition.band is not Band.UNKNOWN:
        bases.append(
            f"Rekabet: {_TR_BAND[competition.band.value]} ({competition.occurrences} rakip içerik)"
        )
    if enrichment.historical_outcome is not None:
        publications = enrichment.historical_basis.get("publication_count")
        count = f", {publications} yayın" if isinstance(publications, int) else ""
        bases.append(
            f"Geçmiş başarı: {_TR_OUTCOME.get(enrichment.historical_outcome, 'bilinmiyor')} "
            f"({_TR_BAND[enrichment.historical_band]}{count})"
        )
    else:
        bases.append("Geçmiş başarı: bilinmiyor")
    bases.append(
        f"Kanıt: {evidence_count} kayıt, {enrichment.independent_sources} bağımsız kaynak, "
        f"{enrichment.signal_families} sinyal türü; strateji: "
        f"{len(strategy.keywords)} konu eşleşti"
    )
    return bases


def _rationale(
    recommendation: OpportunityRecommendation,
    inspiration: InspirationBand,
    search: SearchOpportunityBand,
    evidence_count: int,
    strategy: StrategyContext,
    enrichment: EnrichmentResult,
    *,
    commissionable: bool,
    evaluated_at: datetime,
) -> str:
    verdict: str
    if recommendation is OpportunityRecommendation.CONTINUE_RESEARCH:
        if search is SearchOpportunityBand.STRONG and inspiration is InspirationBand.LOW:
            verdict = (
                "Arama potansiyeli güçlü ama fikir sinyalleri klişe; özgün bir açı "
                "bulunana kadar araştırma sürmeli."
            )
        else:
            verdict = (
                "Konu umut veriyor olabilir; mevcut fikir sinyalleri veya kanıt seti "
                "henüz içerik üretimi için yeterince güçlü değil."
            )
    elif recommendation is OpportunityRecommendation.PRODUCE:
        lift = (
            " Stratejik eşleşme yok; benzer içeriklerin geçmiş başarısı önceliği yükseltti."
            if not (strategy.keywords or strategy.clusters) and enrichment.historical_positive
            else ""
        )
        verdict = (
            f"İlham değeri yüksek, {evidence_count} kanıt kaydı var ve "
            f"{len(strategy.keywords)} stratejik konu eşleşti.{lift}"
        )
    elif recommendation is OpportunityRecommendation.ELIMINATE:
        verdict = (
            "Hem temel uygunluk hem de ilham değeri zayıf; editoryal kaynak ayırmak önerilmiyor."
        )
    elif not commissionable:
        verdict = (
            f"İlham değeri {_TR_BAND[inspiration.value]}; arama fırsatı {_TR_BAND[search.value]}. "
            "Kaynak tabanı (güncellik, kaynak sayısı, kaynak güveni, kanıt) henüz "
            "görevlendirilebilir değil; bu konunun değeri değil kaynak kalitesidir. "
            "Yeni araştırma girdisi ve yeniden değerlendirme olmadan üretim onayı "
            "verilemez."
        )
    elif search is SearchOpportunityBand.WEAK:
        verdict = (
            f"İlham değeri {_TR_BAND[inspiration.value]} ancak ölçülen arama potansiyeli "
            "zayıf; üretim kararı operatörde."
        )
    else:
        verdict = (
            f"İlham değeri {_TR_BAND[inspiration.value]}; arama fırsatı {_TR_BAND[search.value]}. "
            "Nihai değerlendirme operatörde."
        )
    bases = _bases(enrichment, evidence_count, strategy, evaluated_at)
    return f"{verdict} Dayanaklar — {'; '.join(bases)}."
