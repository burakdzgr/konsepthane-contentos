"""Opportunity Intelligence: enrichment, policy, rationale, read exposure.

Providers are the REAL adapters over a scripted httpx transport: a healthy
body, a missing key, a vendor 429, a read timeout and a partial failure
are exercised as the vendor would produce them. No test invents a metric;
every UNKNOWN below is asserted as UNKNOWN (never 0).
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from editorial_harness import Context, Harness, seed_scored
from integrations_fixtures import (
    FAKE_PINTEREST_TOKEN,
    FAKE_SEMRUSH_KEY,
    FAKE_TRENDS_KEY,
    FixedClock,
    Recorder,
    assert_no_secrets,
    integration_settings,
    json_response,
    text_response,
    timeout_raiser,
)
from sqlalchemy import select

from contentos.inspiration.enrichment import (
    MAX_KEYWORDS,
    STATE_NOT_REQUESTED,
    STATE_STORED,
    enrich_opportunity,
    keyword_set,
    pinterest_band,
    semrush_band,
)
from contentos.inspiration.enums import (
    InspirationBand,
    OpportunityRecommendation,
    SearchOpportunityBand,
    TrendState,
)
from contentos.inspiration.models import InspirationEvaluation
from contentos.inspiration.service import (
    ENGINE_VERSION,
    InspirationIntelligenceService,
    recommendation_for,
)
from contentos.integrations.enums import ProviderState
from contentos.integrations.models import IntegrationStatusRecord
from contentos.integrations.registry import IntegrationRegistry
from contentos.intelligence.enums import Band, SignalFamily
from contentos.intelligence.models import IntelligenceSignal
from contentos.signals.models import SearchSignal
from contentos.sources.models import Source
from contentos.strategy.service import StrategyContext, StrategyService

NOW = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)
PRIMARY = "doğum günü partisi"

SEMRUSH_BODY = (
    "Keyword;Search Volume;CPC;Competition;Keyword Difficulty;Intent\n"
    f"{PRIMARY};1900;0.45;0.12;32;1\n"
    "parti süsleri;;;;;\n"
)


def trends_payload(term: str, values: list[float]) -> dict[str, Any]:
    start = datetime(2026, 1, 5, tzinfo=UTC)
    return {
        "series": [
            {
                "term": term,
                "points": [
                    {"date": (start + timedelta(days=7 * index)).date().isoformat(), "value": v}
                    for index, v in enumerate(values)
                ],
            }
        ]
    }


RISING = [10.0] * 12 + [20.0] * 12


def pinterest_payload(keyword: str, wow: float | None = 25.0) -> dict[str, Any]:
    return {
        "trends": [
            {
                "keyword": keyword,
                "pct_growth_wow": wow,
                "pct_growth_yoy": 40.0,
                "time_series": {"date": ["2026-08-24", "2026-08-31"], "index": [50, 62]},
            }
        ]
    }


Handler = Any


def route(
    *,
    semrush: Handler | None = None,
    trends: Handler | None = None,
    pinterest: Handler | None = None,
) -> Recorder:
    def handle(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "api.semrush.com":
            return semrush(request) if semrush else text_response(200, SEMRUSH_BODY)
        if host == "trends.googleapis.com":
            return (
                trends(request) if trends else json_response(200, trends_payload(PRIMARY, RISING))
            )
        if host == "api.pinterest.com":
            return (
                pinterest(request) if pinterest else json_response(200, pinterest_payload(PRIMARY))
            )
        raise AssertionError(f"unexpected host {host}")

    return Recorder(handle)


def registry(recorder: Recorder, *, configured: bool = True) -> IntegrationRegistry:
    overrides: dict[str, Any] = (
        {
            "semrush_api_key": FAKE_SEMRUSH_KEY,
            "google_trends_api_key": FAKE_TRENDS_KEY,
            "pinterest_access_token": FAKE_PINTEREST_TOKEN,
        }
        if configured
        else {}
    )
    return IntegrationRegistry(
        integration_settings(**overrides),
        http_client=recorder.client(),
        clock=FixedClock(NOW),
        sleep=recorder.sleep,
    )


@pytest.fixture()
def harness() -> Harness:
    return Harness()


def seed(harness: Harness, *, keyword: bool = True) -> Context:
    context = Context()
    with harness.session() as session:
        seed_scored(session, context)
        if keyword:
            cluster = StrategyService(session).create_cluster(name="Doğum Günü", priority=90)
            StrategyService(session).create_keyword(
                phrase=PRIMARY, priority=95, topic_cluster_id=cluster.id
            )
            session.commit()
    return context


def status_rows(harness: Harness) -> dict[str, IntegrationStatusRecord]:
    with harness.session() as session:
        return {row.provider: row for row in session.scalars(select(IntegrationStatusRecord))}


# --- pure rules ------------------------------------------------------------------


class TestPureRules:
    def test_semrush_thresholds_and_unknown(self) -> None:
        assert semrush_band(None, None) is Band.UNKNOWN
        assert semrush_band(None, 10.0) is Band.UNKNOWN
        assert semrush_band(1900, 32.0) is Band.STRONG
        assert semrush_band(1900, None) is Band.STRONG
        assert semrush_band(1900, 65.0) is Band.MODERATE
        assert semrush_band(250, 40.0) is Band.MODERATE
        assert semrush_band(1900, 90.0) is Band.WEAK
        assert semrush_band(50, 5.0) is Band.WEAK
        assert semrush_band(0, None) is Band.WEAK  # a KNOWN zero is weak, not unknown

    def test_pinterest_thresholds_and_unknown(self) -> None:
        assert pinterest_band(None) is Band.UNKNOWN
        assert pinterest_band(25.0) is Band.STRONG
        assert pinterest_band(8.0) is Band.MODERATE
        assert pinterest_band(-3.0) is Band.WEAK

    def test_keyword_set_is_bounded_natural_turkish_and_deduplicated(self) -> None:
        strategy = StrategyContext(audiences=(), keywords=(), clusters=())
        titles = [
            "Doğum Günü Partisi",  # duplicate of the topic after normalization
            "Balon süsleme fikirleri",
            "Bu bir çok uzun başlık olduğu için sorgu olarak gönderilmemeli asla",
            *[f"tema {index}" for index in range(20)],
        ]
        keywords = keyword_set("doğum   günü partisi", titles, strategy)
        assert keywords[0] == "doğum günü partisi"  # whitespace cleaned, diacritics kept
        assert "Balon süsleme fikirleri" in keywords
        assert not any("sorgu olarak" in keyword for keyword in keywords)
        assert len(keywords) == MAX_KEYWORDS
        assert len({keyword.casefold() for keyword in keywords}) == MAX_KEYWORDS


class TestRecommendationPolicy:
    def test_search_strong_and_inspiration_low_continues_research(self) -> None:
        assert (
            recommendation_for(
                search=SearchOpportunityBand.STRONG,
                inspiration=InspirationBand.LOW,
                has_evidence=True,
                has_strategy_match=True,
                commissionable=True,
            )
            is OpportunityRecommendation.CONTINUE_RESEARCH
        )

    def test_known_weak_search_never_produces(self) -> None:
        assert (
            recommendation_for(
                search=SearchOpportunityBand.WEAK,
                inspiration=InspirationBand.HIGH,
                has_evidence=True,
                has_strategy_match=True,
                commissionable=True,
            )
            is OpportunityRecommendation.HUMAN_REVIEW
        )

    def test_unknown_search_does_not_block_produce(self) -> None:
        assert (
            recommendation_for(
                search=SearchOpportunityBand.UNKNOWN,
                inspiration=InspirationBand.HIGH,
                has_evidence=True,
                has_strategy_match=True,
                commissionable=True,
            )
            is OpportunityRecommendation.PRODUCE
        )

    def test_historical_positive_alone_never_forces_produce(self) -> None:
        for inspiration in (InspirationBand.MEDIUM, InspirationBand.LOW, InspirationBand.UNKNOWN):
            assert (
                recommendation_for(
                    search=SearchOpportunityBand.UNKNOWN,
                    inspiration=inspiration,
                    has_evidence=True,
                    has_strategy_match=False,
                    commissionable=True,
                    historical_positive=True,
                )
                is not OpportunityRecommendation.PRODUCE
            )
        # Not commissionable: history is a priority signal, not a gate override.
        assert (
            recommendation_for(
                search=SearchOpportunityBand.UNKNOWN,
                inspiration=InspirationBand.HIGH,
                has_evidence=True,
                has_strategy_match=False,
                commissionable=False,
                historical_positive=True,
            )
            is OpportunityRecommendation.HUMAN_REVIEW
        )

    def test_historical_positive_lifts_only_high_and_commissionable(self) -> None:
        assert (
            recommendation_for(
                search=SearchOpportunityBand.UNKNOWN,
                inspiration=InspirationBand.HIGH,
                has_evidence=True,
                has_strategy_match=False,
                commissionable=True,
                historical_positive=False,
            )
            is OpportunityRecommendation.HUMAN_REVIEW
        )
        assert (
            recommendation_for(
                search=SearchOpportunityBand.UNKNOWN,
                inspiration=InspirationBand.HIGH,
                has_evidence=True,
                has_strategy_match=False,
                commissionable=True,
                historical_positive=True,
            )
            is OpportunityRecommendation.PRODUCE
        )

    def test_eliminate_and_review(self) -> None:
        assert (
            recommendation_for(
                search=SearchOpportunityBand.UNKNOWN,
                inspiration=InspirationBand.LOW,
                has_evidence=False,
                has_strategy_match=False,
                commissionable=False,
                base_ineligible=True,
            )
            is OpportunityRecommendation.ELIMINATE
        )
        assert (
            recommendation_for(
                search=SearchOpportunityBand.MODERATE,
                inspiration=InspirationBand.MEDIUM,
                has_evidence=True,
                has_strategy_match=True,
                commissionable=True,
            )
            is OpportunityRecommendation.HUMAN_REVIEW
        )


# --- enrichment with real adapters over scripted HTTP ------------------------------


class TestEnrichment:
    def test_healthy_providers_feed_search_trend_and_provenance(self, harness: Harness) -> None:
        context = seed(harness)
        recorder = route()
        with harness.session() as session:
            result = InspirationIntelligenceService(session).evaluate(
                context.opportunity_id, evaluated_at=NOW, registry=registry(recorder)
            )
            session.commit()
            evaluation = result.evaluation
            signals = list(session.scalars(select(SearchSignal)))

        assert evaluation.engine_version == ENGINE_VERSION == "5"
        assert evaluation.search_opportunity is SearchOpportunityBand.STRONG
        assert evaluation.trend_state is TrendState.KNOWN
        block = evaluation.input_snapshot["intelligence"]
        assert block["keywords"][0] == PRIMARY
        assert block["search"]["search_volume"] == 1900
        assert block["search"]["keyword_difficulty"] == 32.0
        assert block["search"]["provider"]["state"] == "healthy"
        assert block["search"]["provider"]["region"] == "tr"
        assert block["search"]["provider"]["observed_at"] == NOW.isoformat()
        assert block["trend"]["direction"] == "rising"
        assert block["visual_trend"]["band"] == "strong"
        assert block["visual_trend"]["growth_pct"] == 25.0
        assert block["research"]["independent_sources"] >= 2 + 3
        assert "search" in block["research"]["families_known"]
        assert "trend" in block["research"]["families_known"]
        assert "visual_trend" in block["research"]["families_known"]
        assert "measured_search_demand" not in evaluation.missing_signals
        assert "trend_signal" not in evaluation.missing_signals
        # Rationale names the concrete bases with provider freshness.
        assert "Semrush: hacim 1.900, zorluk 32 (tr, bugün)" in evaluation.rationale
        assert "Google Trends: yükseliyor (TR, bugün)" in evaluation.rationale
        assert "Pinterest: güçlü (%25 büyüme, bugün)" in evaluation.rationale
        assert "Topluluk ihtiyacı: bilinmiyor" in evaluation.rationale
        # Observations were persisted as provenance-complete SearchSignal rows
        # (UNKNOWN volume for "parti süsleri" is NOT persisted as 0).
        kinds = {(row.provider, row.signal_type.value, row.subject) for row in signals}
        assert ("semrush", "search_volume", PRIMARY) in kinds
        assert ("google_trends", "trend", PRIMARY) in kinds
        assert ("pinterest_trends", "trend", PRIMARY) in kinds
        assert not any(row.subject == "parti süsleri" for row in signals)
        # Durable provider status: healthy for all three; no secret anywhere.
        rows = status_rows(harness)
        assert {name: row.state for name, row in rows.items()} == {
            "semrush": ProviderState.HEALTHY,
            "google_trends": ProviderState.HEALTHY,
            "pinterest_trends": ProviderState.HEALTHY,
        }
        assert_no_secrets(json.dumps(evaluation.input_snapshot, ensure_ascii=False))
        assert_no_secrets(evaluation.rationale)
        # Exactly one call per provider (Semrush batched; one trend call each).
        hosts = [request.url.host for request in recorder.requests]
        assert hosts.count("api.semrush.com") == 1
        assert hosts.count("trends.googleapis.com") == 1
        assert hosts.count("api.pinterest.com") == 1

    def test_unconfigured_providers_stay_unknown_without_any_call(self, harness: Harness) -> None:
        context = seed(harness)
        recorder = route()
        with harness.session() as session:
            result = InspirationIntelligenceService(session).evaluate(
                context.opportunity_id,
                evaluated_at=NOW,
                registry=registry(recorder, configured=False),
            )
            session.commit()
            evaluation = result.evaluation

        assert recorder.requests == []
        assert evaluation.search_opportunity is SearchOpportunityBand.UNKNOWN
        assert evaluation.trend_state is TrendState.UNKNOWN
        block = evaluation.input_snapshot["intelligence"]
        assert block["search"]["search_volume"] is None
        assert block["search"]["potential_band"] == "unknown"
        assert block["search"]["provider"]["state"] == "not_configured"
        assert block["trend"]["provider"]["state"] == "access_required"
        assert block["visual_trend"]["provider"]["state"] == "access_required"
        assert "Semrush: yapılandırılmadı" in evaluation.rationale
        assert "Google Trends: erişim gerekli" in evaluation.rationale
        assert "Pinterest: erişim gerekli" in evaluation.rationale
        assert "measured_search_demand" in evaluation.missing_signals
        assert status_rows(harness) == {}  # nothing attempted, nothing recorded

    def test_rate_limit_timeout_and_partial_success_are_typed_unknowns(
        self, harness: Harness
    ) -> None:
        context = seed(harness)
        recorder = route(
            semrush=lambda request: text_response(429, "slow down", {"Retry-After": "3600"}),
            trends=timeout_raiser,
        )
        with harness.session() as session:
            result = InspirationIntelligenceService(session).evaluate(
                context.opportunity_id, evaluated_at=NOW, registry=registry(recorder)
            )
            session.commit()
            evaluation = result.evaluation

        block = evaluation.input_snapshot["intelligence"]
        assert block["search"]["potential_band"] == "unknown"
        assert block["search"]["search_volume"] is None
        assert block["search"]["provider"]["state"] == "rate_limited"
        assert block["trend"]["direction"] == "unknown"
        assert block["trend"]["provider"]["state"] == "degraded"
        assert block["trend"]["provider"]["error_class"] == "google_trends_timeout"
        # Partial: Pinterest still answered and is used; search stays unknown.
        assert block["visual_trend"]["band"] == "strong"
        assert evaluation.search_opportunity is SearchOpportunityBand.UNKNOWN
        assert evaluation.trend_state is TrendState.KNOWN
        assert "Semrush: kota sınırında" in evaluation.rationale
        assert "Google Trends: kısıtlı" in evaluation.rationale
        rows = status_rows(harness)
        assert rows["semrush"].state is ProviderState.RATE_LIMITED
        assert rows["google_trends"].state is ProviderState.DEGRADED
        assert rows["google_trends"].last_error_class == "google_trends_timeout"
        assert rows["pinterest_trends"].state is ProviderState.HEALTHY

    def test_provider_free_process_reads_stored_history_and_reuses(self, harness: Harness) -> None:
        context = seed(harness)
        with harness.session() as session:
            first = InspirationIntelligenceService(session).evaluate(
                context.opportunity_id, evaluated_at=NOW, registry=registry(route())
            )
            session.commit()
            # The API process: no registry, no network — durable rows only.
            second = InspirationIntelligenceService(session).evaluate(
                context.opportunity_id, evaluated_at=NOW + timedelta(days=2)
            )
            session.commit()
            stored = enrich_opportunity(session, context.opportunity_id)

        assert stored.semrush.state == STATE_STORED
        assert stored.search_volume == 1900
        assert stored.keyword_difficulty == 32.0
        assert stored.semrush.observed_at == NOW
        assert stored.trend_direction == "rising"
        assert stored.google_trends.state == STATE_STORED
        assert stored.visual_growth_pct == 25.0
        # Same facts -> the SAME evaluation (timestamps are not identity).
        assert second.created is False
        assert second.evaluation.id == first.evaluation.id

    def test_provider_free_process_without_history_is_not_requested(self, harness: Harness) -> None:
        context = seed(harness)
        with harness.session() as session:
            result = enrich_opportunity(session, context.opportunity_id)
        assert result.semrush.state == STATE_NOT_REQUESTED
        assert result.search_potential is Band.UNKNOWN
        assert result.google_trends.state == STATE_NOT_REQUESTED
        assert result.pinterest.state == STATE_NOT_REQUESTED
        assert result.historical_band == "unknown"
        assert result.cannibalization_status == "unknown"

    def test_community_need_never_raises_search_demand(self, harness: Harness) -> None:
        context = seed(harness)
        with harness.session() as session:
            sources = list(session.scalars(select(Source)))
            assert len(sources) >= 2
            for index, source in enumerate(sources[:2]):
                session.add(
                    IntelligenceSignal(
                        family=SignalFamily.COMMUNITY_NEED,
                        subject="Doğum günü için tema önerir misiniz?",
                        concept_key=f"dogum gunu tema {index}",
                        source_id=source.id,
                        normalized_document_id=None,
                        opportunity_id=context.opportunity_id,
                        provider="community-need-extractor/1",
                        value={"category": "doğum günü"},
                        occurrence_count=4,
                        first_observed_at=NOW,
                        last_observed_at=NOW,
                        observation_hash=uuid.uuid4().hex + uuid.uuid4().hex,
                    )
                )
            session.commit()
            result = InspirationIntelligenceService(session).evaluate(
                context.opportunity_id,
                evaluated_at=NOW,
                registry=registry(route(), configured=False),
            )
            session.commit()
            evaluation = result.evaluation

        block = evaluation.input_snapshot["intelligence"]
        assert block["families"]["community_need"]["band"] == "strong"
        assert block["families"]["community_need"]["sources"] == 2
        assert block["families"]["community_need"]["occurrences"] == 8
        assert block["search"]["potential_band"] == "unknown"
        assert evaluation.search_opportunity is SearchOpportunityBand.UNKNOWN
        assert "Topluluk ihtiyacı: güçlü (2 kaynak, 8 gözlem)" in evaluation.rationale
        assert "community_need" not in evaluation.missing_signals

    def test_unknown_opportunity_is_a_lookup_error(self, harness: Harness) -> None:
        with harness.session() as session, pytest.raises(LookupError):
            enrich_opportunity(session, uuid.uuid4())


# --- read model exposure ---------------------------------------------------------


class TestReadExposure:
    def test_queue_row_and_detail_expose_explainable_sections(self, harness: Harness) -> None:
        context = seed(harness)
        with harness.session() as session:
            InspirationIntelligenceService(session).evaluate(
                context.opportunity_id, evaluated_at=NOW, registry=registry(route())
            )
            session.commit()

        page = harness.get("/internal/editorial/work-items").json()
        [row] = page["items"]
        intelligence = row["intelligence"]
        assert intelligence["engine_version"] == "5"
        assert intelligence["content_value"]["inspiration_band"] in {"high", "medium", "low"}
        assert intelligence["content_value"]["strategy_fit_band"] == "very_high"
        assert intelligence["content_value"]["community_need_band"] == "unknown"
        search = intelligence["search_intelligence"]
        assert search["semrush_potential_band"] == "high"
        assert search["search_volume"] == 1900
        assert search["keyword_difficulty"] == 32.0
        assert search["google_trends_direction"] == "rising"
        assert search["pinterest_trend_band"] == "high"
        assert search["competition_band"] == "unknown"
        assert search["provider_freshness"]["semrush"]["state"] == "healthy"
        assert search["provider_freshness"]["semrush"]["observed_at"] is not None
        assert search["provider_freshness"]["semrush"]["region"] == "tr"
        assert intelligence["konsepthane_data"] == {
            "similar_content_performance_band": "unknown",
            "cannibalization_status": "unknown",
            "historical_outcome": None,
        }
        assert intelligence["research"]["evidence_state"] == "sufficient"
        assert intelligence["research"]["independent_sources"] >= 5
        assert intelligence["recommendation"] == row["recommendation"]
        assert intelligence["why"] == row["inspiration_rationale"]
        assert [entry["factor"] for entry in intelligence["factor_bands"]] == [
            "novelty",
            "usefulness",
            "specificity",
            "visual_potential",
            "shareability",
            "emotional_impact",
            "audience_fit",
            "turkish_market_applicability",
            "variation_potential",
            "strategic_fit",
        ]
        assert all(entry["basis"] for entry in intelligence["factor_bands"])
        serialized = json.dumps(page, ensure_ascii=False)
        assert_no_secrets(serialized)
        assert "api_key" not in serialized.lower()

        detail = harness.get(f"/internal/editorial/work-items/{context.work_item_id}").json()
        inspiration = detail["inspiration"]
        assert inspiration["engine_name"] == "inspiration-quality"
        assert inspiration["engine_version"] == "5"
        assert inspiration["search_opportunity"] == "strong"
        assert inspiration["trend_state"] == "known"
        assert inspiration["intelligence"] == intelligence
        assert_no_secrets(json.dumps(detail, ensure_ascii=False))

    def test_pre_v5_evaluation_projects_unknowns_not_zeros(self, harness: Harness) -> None:
        context = seed(harness, keyword=False)
        with harness.session() as session:
            session.add(
                InspirationEvaluation(
                    opportunity_id=context.opportunity_id,
                    engine_name="inspiration-quality",
                    engine_version="4",
                    inspiration_band=InspirationBand.MEDIUM,
                    search_opportunity=SearchOpportunityBand.UNKNOWN,
                    trend_state=TrendState.UNKNOWN,
                    recommendation=OpportunityRecommendation.HUMAN_REVIEW,
                    rationale="Eski değerlendirme.",
                    factors={"novelty": {"value": 4, "basis": "b"}},
                    strategy_context={},
                    missing_signals=["measured_search_demand"],
                    input_snapshot={"engine_version": "4"},
                    input_snapshot_hash="a" * 64,
                    evaluated_at=NOW,
                )
            )
            session.commit()

        [row] = harness.get("/internal/editorial/work-items").json()["items"]
        intelligence = row["intelligence"]
        assert intelligence["search_intelligence"]["search_volume"] is None
        assert intelligence["search_intelligence"]["semrush_potential_band"] == "unknown"
        assert intelligence["search_intelligence"]["google_trends_direction"] == "unknown"
        assert intelligence["search_intelligence"]["provider_freshness"]["semrush"]["state"] == (
            "unknown"
        )
        assert intelligence["research"] == {
            "independent_sources": None,
            "signal_families": None,
            "evidence_state": "unknown",
        }
        assert intelligence["content_value"]["audience_fit_band"] == "unknown"
        bands = {entry["factor"]: entry["band"] for entry in intelligence["factor_bands"]}
        assert bands["novelty"] == "high"
        assert bands["usefulness"] == "unknown"

    def test_unevaluated_opportunity_has_no_intelligence(self, harness: Harness) -> None:
        context = seed(harness, keyword=False)
        [row] = harness.get("/internal/editorial/work-items").json()["items"]
        assert row["intelligence"] is None
        detail = harness.get(f"/internal/editorial/work-items/{context.work_item_id}").json()
        assert detail["inspiration"] is None
