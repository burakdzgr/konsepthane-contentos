"""Research-driven idea engine: missions plan, search, synthesize, evaluate,
ground and promote — without a single source being the starting point."""

import copy
import dataclasses
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from editorial_harness import Harness, seed_documents
from sqlalchemy import select

from contentos.ai.dto import (
    GenerationRequest,
    ProviderIdentity,
    ProviderOutputSchema,
    ProviderResult,
)
from contentos.ai.enums import GenerationPurpose, ProviderFailureKind
from contentos.ai.errors import ProviderFailureError
from contentos.ai.models import AiGenerationAttempt
from contentos.autopilot.enums import AutopilotMode
from contentos.autopilot.planner import ACTION_GENERATE_IDEAS, Snapshot, plan
from contentos.evidence_packs.policy import DEFAULT_EVIDENCE_POLICY, IDEA_LED_EVIDENCE_POLICY
from contentos.evidence_packs.service import EvidencePackService
from contentos.missions.engine import (
    MissionEngine,
    matches_cliche,
    quality_score,
)
from contentos.missions.enums import (
    CandidateKind,
    CandidateRecommendation,
    MissionStage,
    MissionStatus,
    SurfaceKind,
)
from contentos.missions.models import MissionIdeaCandidate, MissionSignal, ResearchMission
from contentos.missions.service import MissionInput, ResearchMissionService
from contentos.opportunities.enums import OpportunityDisposition, ScoreEligibility
from contentos.opportunities.models import EditorialOpportunity
from contentos.opportunities.repository import OpportunityRepository
from contentos.opportunities.scoring import IDEA_LED_ENGINE_NAME, OPPORTUNITY_ENGINE_NAME
from contentos.opportunities.scoring_service import OpportunityScoringService
from contentos.research.enums import EvidenceType, ExtractionMethod
from contentos.research.service import ResearchEvidenceService
from contentos.workflow.enums import WorkflowState, WorkItemOrigin
from contentos.workflow.repository import WorkflowRepository

NOW = datetime(2026, 9, 7, 9, 0, tzinfo=UTC)


class PurposeProvider:
    """A structured provider that answers each generation purpose with its
    own fixed payload (the fake provider answers everything the same way)."""

    identity = ProviderIdentity(provider="fake", model_name="mission-test-model", model_version="1")

    def __init__(self, payloads: dict[GenerationPurpose, dict[str, Any]]) -> None:
        self.payloads = payloads
        self.calls: list[GenerationPurpose] = []
        self.projections: dict[GenerationPurpose, dict[str, Any]] = {}

    def generate(
        self, request: GenerationRequest, output_schema: ProviderOutputSchema
    ) -> ProviderResult:
        del output_schema
        self.calls.append(request.purpose)
        self.projections[request.purpose] = dict(request.input_projection)
        return ProviderResult(
            payload=copy.deepcopy(self.payloads[request.purpose]),
            provider=self.identity.provider,
            model_name=self.identity.model_name,
            model_version=self.identity.model_version,
            finish_reason="stop",
        )


def plan_payload() -> dict[str, Any]:
    return {
        "intent_summary": "Çiftler klişe olmayan, uygulanabilir teklif fikirleri arıyor.",
        "audience_notes": "20-35 yaş çiftler; orta bütçe; şehir içi mekânlar.",
        "keywords": [
            "ilginç evlilik teklifleri",
            "yaratıcı evlilik teklifi",
            "sürpriz evlilik teklifi",
            "doğum günü partisi",
        ],
        "queries": [
            {
                "query": "yaratıcı evlilik teklifi fikirleri",
                "language": "tr",
                "purpose": "inspiration",
                "surface": "open_web",
            },
            {
                "query": "site:pinterest.com creative marriage proposal",
                "language": "en",
                "purpose": "visual",
                "surface": "visual_inspiration",
            },
            {
                "query": "evlilik teklifi nasıl yapılır forum",
                "language": "tr",
                "purpose": "community",
                "surface": "community_need",
            },
        ],
        "cliche_patterns": ["sahilde teklif", "restoranda teklif", "çiçeklerle teklif"],
        "primitive_hints": ["yükseklik", "sürpriz zamanlaması", "gizli mesaj"],
    }


def web_payload() -> dict[str, Any]:
    return {
        "signals": [
            {
                "title": "Ferris wheel proposal at sunset",
                "snippet": "A proposal timed for the top of a ferris wheel ride.",
                "url": "https://www.example-ideas.com/ferris-wheel-proposal",
                "surface": "open_web",
                "language": "en",
                "why_relevant": "Height and timing mechanics.",
                "query": "creative marriage proposal",
            },
            {
                "title": "Scavenger hunt proposal ideas",
                "snippet": "Clues across the couple's favourite places ending with the ring.",
                "url": None,
                "surface": "visual_inspiration",
                "language": "en",
                "why_relevant": "Route and reveal mechanics.",
                "query": "site:pinterest.com creative marriage proposal",
            },
            {
                "title": "Sahilde evlilik teklifi",
                "snippet": "Sahilde gün batımında teklif.",
                "url": "https://blog.example-ideas.com/sahilde-teklif",
                "surface": "open_web",
                "language": "tr",
                "why_relevant": "Common approach.",
                "query": "yaratıcı evlilik teklifi fikirleri",
            },
        ],
        "search_notes": None,
    }


def synthesis_payload(signal_ids: list[str]) -> dict[str, Any]:
    strong = {
        "novelty": 88,
        "usefulness": 80,
        "specificity": 85,
        "visual_potential": 90,
        "shareability": 80,
        "emotional_impact": 85,
        "audience_fit": 80,
        "turkey_applicability": 75,
    }
    weak = {key: 30 for key in strong}
    return {
        "primitives": [
            {"key": "height", "label": "Yükseklik", "description": "Şehre yukarıdan bakan bir an."},
            {
                "key": "hidden-message",
                "label": "Gizli mesaj",
                "description": "Ortaya çıkan bir mesaj.",
            },
            {"key": "route", "label": "Rota", "description": "Anlamlı duraklardan geçen bir yol."},
        ],
        "candidates": [
            {
                "title": "Dönme dolabın tepesinde açılan gizli mesaj teklifi",
                "angle": "Kabin tam tepedeyken küçük bir kutudaki mesajla teklif; şehir manzarası fotoğraf anını verir.",
                "kind": "synthesized",
                "signal_ids": signal_ids[:1],
                "primitive_keys": ["height", "hidden-message"],
                "cluster_key": "height-reveal",
                "is_cliche": False,
                "cliche_reason": None,
                "factors": strong,
                "implementation_steps": [
                    "Kabini önceden ayırt",
                    "Mesajı kutuya gizle",
                    "Tepede aç",
                ],
                "factual_claims_needed": ["Dönme dolap bilet ve kabin kuralları"],
                "rationale": "Yükseklik ve sürpriz zamanlaması birleşiyor.",
            },
            {
                "title": "Dönme dolap tepesinde mesajlı teklif",
                "angle": "Aynı fikrin yakın bir varyantı.",
                "kind": "synthesized",
                "signal_ids": [],
                "primitive_keys": ["height"],
                "cluster_key": "height-reveal",
                "is_cliche": False,
                "cliche_reason": None,
                "factors": {**strong, "novelty": 70},
                "implementation_steps": [],
                "factual_claims_needed": [],
                "rationale": "Benzer.",
            },
            {
                "title": "Şehir rotasında ipuçlu teklif yürüyüşü",
                "angle": "Çiftin ilk buluşma noktalarından geçen ipuçlu rota; son durakta teklif.",
                "kind": "synthesized",
                "signal_ids": signal_ids[1:2],
                "primitive_keys": ["route", "hidden-message"],
                "cluster_key": "route-hunt",
                "is_cliche": False,
                "cliche_reason": None,
                "factors": {**strong, "novelty": 78, "visual_potential": 70},
                "implementation_steps": ["Durakları seç", "İpuçlarını yaz", "Son durağı hazırla"],
                "factual_claims_needed": [],
                "rationale": "Rota ve reveal mekaniği.",
            },
            {
                "title": "Sahilde gün batımında teklif",
                "angle": "Sahilde teklif.",
                "kind": "extracted",
                "signal_ids": signal_ids[2:3],
                "primitive_keys": [],
                "cluster_key": "beach",
                "is_cliche": False,
                "cliche_reason": None,
                "factors": {**strong, "novelty": 40},
                "implementation_steps": [],
                "factual_claims_needed": [],
                "rationale": "Sık görülen fikir.",
            },
            {
                "title": "Restoranda çiçekli teklif",
                "angle": "Restoranda çiçek.",
                "kind": "extracted",
                "signal_ids": signal_ids[2:3],
                "primitive_keys": [],
                "cluster_key": "restaurant",
                "is_cliche": True,
                "cliche_reason": "Herkesin yaptığı sıradan fikir.",
                "factors": weak,
                "implementation_steps": [],
                "factual_claims_needed": [],
                "rationale": "Klişe.",
            },
        ],
    }


class LazyProvider(PurposeProvider):
    """Synthesis needs the signal ids the engine created: build it lazily."""

    def generate(
        self, request: GenerationRequest, output_schema: ProviderOutputSchema
    ) -> ProviderResult:
        if request.purpose is GenerationPurpose.IDEA_SYNTHESIS:
            ids = [entry["id"] for entry in request.input_projection["signals"]]
            web_ids = [
                entry["id"]
                for entry in request.input_projection["signals"]
                if entry["surface"] != "registered_source"
            ]
            ordered = web_ids + [sid for sid in ids if sid not in web_ids]
            self.payloads[GenerationPurpose.IDEA_SYNTHESIS] = synthesis_payload(ordered)
        return super().generate(request, output_schema)


@pytest.fixture()
def harness() -> Harness:
    return Harness()


def make_provider() -> LazyProvider:
    return LazyProvider(
        {
            GenerationPurpose.MISSION_PLANNING: plan_payload(),
            GenerationPurpose.WEB_RESEARCH: web_payload(),
            GenerationPurpose.IDEA_SYNTHESIS: {},
        }
    )


def create_mission(harness: Harness) -> uuid.UUID:
    with harness.session() as session:
        row = ResearchMissionService(session).create(
            MissionInput(
                topic="İlginç Evlilik Teklifleri",
                goal="Türkiye için gerçekten yaratıcı ve uygulanabilir 20 fikir bul.",
                audience="20–35 yaş çiftler",
                seed_keyword="ilginç evlilik teklifleri",
            )
        )
        ResearchMissionService(session).mark_queued(row.id)
        session.commit()
        return row.id


class TestContracts:
    def test_over_long_lists_are_cut_to_the_contract_not_refused(self) -> None:
        from contentos.missions.schemas import MAX_WEB_SIGNALS, ResearchSignalsV1

        signal = web_payload()["signals"][0]
        payload = ResearchSignalsV1.model_validate(
            {"signals": [signal] * (MAX_WEB_SIGNALS + 5), "search_notes": None}
        )
        assert len(payload.signals) == MAX_WEB_SIGNALS


class TestDeterministicLayer:
    def test_quality_is_a_weighted_creative_score_never_demand(self) -> None:
        factors = {
            key: 80
            for key in (
                "novelty",
                "usefulness",
                "specificity",
                "visual_potential",
                "shareability",
                "emotional_impact",
                "audience_fit",
                "turkey_applicability",
            )
        }
        assert quality_score(factors, strategic_fit=False) == 80
        assert quality_score(factors, strategic_fit=True) == 85
        assert quality_score({}, strategic_fit=False) == 0

    def test_cliche_patterns_match_on_distinctive_tokens(self) -> None:
        patterns = ["sahilde teklif", "restoranda teklif"]
        assert matches_cliche("Sahilde gün batımında teklif", "", patterns) == "sahilde teklif"
        assert matches_cliche("Dönme dolapta gizli mesaj", "", patterns) is None


class TestMissionRun:
    def test_goal_only_mission_plans_searches_synthesizes_and_evaluates(
        self, harness: Harness
    ) -> None:
        mission_id = create_mission(harness)
        provider = make_provider()
        fetched: list[str] = []
        with harness.session() as session:
            seed_documents(session)  # registered sources with discovery items
            engine = MissionEngine(
                session,
                provider=provider,
                dispatch_fetch=fetched.append,
                checkpoint=session.commit,
                now=lambda: NOW,
            )
            mission = engine.run(mission_id)
            session.commit()

            # 1. keyword/context expansion happened from the goal alone.
            keywords = [entry["keyword"] for entry in mission.keyword_plan]
            assert "yaratıcı evlilik teklifi" in keywords
            assert all(entry["demand"]["state"] == "unknown" for entry in mission.keyword_plan)
            assert mission.plan["source"] == "model"
            assert mission.plan["cliche_patterns"] == plan_payload()["cliche_patterns"]

            # 2. more than one research surface was used.
            signals = list(
                session.scalars(select(MissionSignal).where(MissionSignal.mission_id == mission_id))
            )
            surfaces = {row.surface_kind for row in signals}
            assert SurfaceKind.OPEN_WEB in surfaces and SurfaceKind.VISUAL_INSPIRATION in surfaces
            assert all(row.provenance["is_factual_evidence"] is False for row in signals)
            assert mission.surface_summary["counts"]["open_web"] == 2

            # 3–7. idea signals, cliché separation, clustering, synthesis, quality.
            candidates = list(
                session.scalars(
                    select(MissionIdeaCandidate).where(
                        MissionIdeaCandidate.mission_id == mission_id
                    )
                )
            )
            by_title = {row.title: row for row in candidates}
            ferris = by_title["Dönme dolabın tepesinde açılan gizli mesaj teklifi"]
            assert ferris.candidate_kind is CandidateKind.SYNTHESIZED
            assert ferris.recommendation is CandidateRecommendation.PROMOTE
            assert ferris.idea_quality >= 80 and ferris.idea_confidence.value == "high"
            assert [p["key"] for p in ferris.primitives] == ["height", "hidden-message"]
            twin = by_title["Dönme dolap tepesinde mesajlı teklif"]
            assert twin.recommendation is CandidateRecommendation.MERGED
            assert twin.merged_into_id == ferris.id
            beach = by_title["Sahilde gün batımında teklif"]
            assert beach.is_cliche and beach.recommendation is CandidateRecommendation.ELIMINATE
            assert beach.cliche_reason is not None and "sahilde teklif" in beach.cliche_reason
            restaurant = by_title["Restoranda çiçekli teklif"]
            assert restaurant.recommendation is CandidateRecommendation.ELIMINATE
            summary = mission.elimination_summary
            assert summary == {
                "found": 5,
                "generic_eliminated": 2,
                "merged": 1,
                "weak_eliminated": 0,
                "retained": 2,
                "promotable": 2,
            }
            # 9. the two confidences stay separate: nothing here is factual.
            assert ferris.factual_evidence_confidence.value == "unknown"
            assert mission.result_summary["factual_evidence"] == "not_evaluated"

            # grounding: the open-web page behind the strong idea is fetched
            # through the normal intake chain (an ad-hoc SEARCH-role source).
            assert mission.status is MissionStatus.GROUNDING
            assert len(fetched) >= 1  # the ferris page, plus topic pages for URL-less ideas
            stages = [entry["stage"] for entry in mission.progress_log]
            for stage in (
                MissionStage.PLANNING,
                MissionStage.KEYWORDS,
                MissionStage.SEARCHING,
                MissionStage.EXTRACTING,
                MissionStage.CLUSTERING,
                MissionStage.EVALUATING,
                MissionStage.GROUNDING,
            ):
                assert stage.value in stages
            assert provider.calls == [
                GenerationPurpose.MISSION_PLANNING,
                GenerationPurpose.WEB_RESEARCH,
                GenerationPurpose.IDEA_SYNTHESIS,
            ]
            attempts = list(session.scalars(select(AiGenerationAttempt)))
            assert {a.purpose for a in attempts} == set(provider.calls)

    def test_a_rerun_makes_fresh_model_calls(self, harness: Harness) -> None:
        mission_id = create_mission(harness)
        provider = make_provider()
        with harness.session() as session:
            engine = MissionEngine(
                session, provider=provider, checkpoint=session.commit, now=lambda: NOW
            )
            engine.run(mission_id)
            session.commit()
            first = len(provider.calls)
            ResearchMissionService(session).mark_queued(mission_id)
            session.commit()
            engine.run(mission_id)
            session.commit()
            # Three purposes, called again (not reused from the first run).
            assert len(provider.calls) == first * 2
            mission = session.get(ResearchMission, mission_id)
            assert mission is not None and mission.result_summary["run_number"] == 2
            attempts = session.scalars(select(AiGenerationAttempt.retry_number)).all()
            assert len(set(attempts)) == len(attempts)

    def test_without_a_text_provider_the_mission_stays_truthful(self, harness: Harness) -> None:
        mission_id = create_mission(harness)
        with harness.session() as session:
            seed_documents(session)
            engine = MissionEngine(
                session, provider=None, checkpoint=session.commit, now=lambda: NOW
            )
            mission = engine.run(mission_id)
            session.commit()
            assert mission.plan["source"] == "deterministic"
            assert any("open_web" in note for note in mission.surface_summary["unavailable"])
            assert mission.result_summary["synthesis_source"] == "deterministic"
            outcome = engine.finalize(mission_id)
            session.commit()
            assert outcome.done
            assert mission.status is MissionStatus.NEEDS_MORE_RESEARCH


class TestResearchSurfaces:
    def test_live_web_failure_falls_back_to_labelled_recall(self, harness: Harness) -> None:
        mission_id = create_mission(harness)

        class FlakyProvider(LazyProvider):
            def generate(self, request: GenerationRequest, output_schema: ProviderOutputSchema):
                if (
                    request.purpose is GenerationPurpose.WEB_RESEARCH
                    and request.template_name == "web-research"
                ):
                    self.calls.append(request.purpose)
                    raise ProviderFailureError(ProviderFailureKind.TIMEOUT, "browser_hung")
                return super().generate(request, output_schema)

        provider = FlakyProvider(
            {
                GenerationPurpose.MISSION_PLANNING: plan_payload(),
                GenerationPurpose.WEB_RESEARCH: web_payload(),
                GenerationPurpose.IDEA_SYNTHESIS: {},
            }
        )
        with harness.session() as session:
            engine = MissionEngine(
                session, provider=provider, checkpoint=session.commit, now=lambda: NOW
            )
            mission = engine.run(mission_id)
            session.commit()
            signals = list(
                session.scalars(select(MissionSignal).where(MissionSignal.mission_id == mission_id))
            )
            assert signals, "recall signals were collected"
            assert all(row.provenance["method"] == "model_recall" for row in signals)
            assert all(row.reference_url is None for row in signals)  # never a guessed URL
            assert any(
                "model hatırlaması" in note for note in mission.surface_summary["unavailable"]
            )
            # Ideas were still synthesized from the recall signals.
            assert mission.elimination_summary["found"] > 0

    def test_url_less_strong_ideas_are_grounded_with_topic_pages(self, harness: Harness) -> None:
        from contentos.discovery.models import DiscoveryItem

        mission_id = create_mission(harness)
        provider = make_provider()
        provider.payloads[GenerationPurpose.WEB_RESEARCH] = {
            "signals": [{**entry, "url": None} for entry in web_payload()["signals"]],
            "search_notes": None,
        }
        fetched: list[str] = []
        with harness.session() as session:
            seed_documents(session)
            for item in session.scalars(select(DiscoveryItem)).all():
                item.title_hint = "Unutulmaz evlilik teklifi fikirleri"
            session.commit()
            engine = MissionEngine(
                session,
                provider=provider,
                dispatch_fetch=fetched.append,
                checkpoint=session.commit,
                now=lambda: NOW,
            )
            mission = engine.run(mission_id)
            session.commit()
            grounding = mission.result_summary["grounding"]
            assert grounding["context_links"] >= 1
            # The registered pages already have documents: ideas are ready.
            assert grounding["ready"] >= 1
            engine.finalize(mission_id)
            session.commit()
            assert mission.status is MissionStatus.COMPLETED
            assert mission.result_summary["promoted"] >= 1

    def test_registered_sources_match_by_url_slug_when_titles_are_missing(
        self, harness: Harness
    ) -> None:
        from contentos.discovery.models import DiscoveryItem

        mission_id = create_mission(harness)
        with harness.session() as session:
            seed_documents(session)
            item = session.scalar(select(DiscoveryItem))
            assert item is not None
            item.title_hint = None
            item.canonical_url = "https://ana.example.test/ilginc-evlilik-teklifi-fikirleri"
            session.commit()
            engine = MissionEngine(
                session, provider=None, checkpoint=session.commit, now=lambda: NOW
            )
            mission = engine.run(mission_id)
            session.commit()
            assert mission.surface_summary["counts"]["registered_source"] >= 1
            signal = session.scalar(
                select(MissionSignal).where(
                    MissionSignal.surface_kind == SurfaceKind.REGISTERED_SOURCE
                )
            )
            assert signal is not None and "evlilik" in signal.query


class TestPromotion:
    def test_a_strong_grounded_idea_becomes_an_idea_led_opportunity(self, harness: Harness) -> None:
        mission_id = create_mission(harness)
        provider = make_provider()
        with harness.session() as session:
            document_ids = seed_documents(session)
            engine = MissionEngine(
                session, provider=provider, checkpoint=session.commit, now=lambda: NOW
            )
            mission = engine.run(mission_id)
            # Simulate the intake chain having grounded the ferris-wheel page.
            ferris = session.scalar(
                select(MissionIdeaCandidate).where(
                    MissionIdeaCandidate.title
                    == "Dönme dolabın tepesinde açılan gizli mesaj teklifi"
                )
            )
            assert ferris is not None
            signal = session.get(MissionSignal, uuid.UUID(ferris.signal_ids[0]))
            assert signal is not None
            signal.normalized_document_id = document_ids[0]
            # The intake chain would have extracted at least metadata-level
            # evidence from the grounded page before anyone scores it.
            for statement in (
                "Kaynak, dönme dolap kabin süresini belirtiyor.",
                "Kaynak, teklif anı için fotoğraf noktasını tarif ediyor.",
            ):
                ResearchEvidenceService(session).record_evidence(
                    document_ids[0],
                    evidence_type=EvidenceType.OBSERVATION,
                    statement=statement,
                    extraction_method=ExtractionMethod.MACHINE,
                    source_locator="structured_metadata.author",
                )
            session.commit()

            # Past the grounding window: whatever is still unfetched no longer
            # holds the mission open.
            later = NOW + timedelta(minutes=20)
            engine = MissionEngine(
                session, provider=provider, checkpoint=session.commit, now=lambda: later
            )
            outcome = engine.finalize(mission_id)
            session.commit()
            assert outcome.done and len(outcome.promoted) == 1
            assert mission.status is MissionStatus.COMPLETED
            assert mission.result_summary["promoted"] == 1

            opportunity = session.get(EditorialOpportunity, outcome.promoted[0])
            assert opportunity is not None
            assert opportunity.mission_candidate_id == ferris.id
            assert opportunity.topic_summary == ferris.title
            assert opportunity.disposition is OpportunityDisposition.OPEN
            work_item = WorkflowRepository(session).get_by_id(opportunity.work_item_id)
            assert work_item is not None
            assert work_item.origin is WorkItemOrigin.RESEARCH_MISSION
            assert work_item.current_state is WorkflowState.IDEA_SCORING
            # Scoring is the task's job AFTER its commit; the engine only reports.
            assert outcome.newly_promoted == (opportunity.id,)
            inputs = OpportunityRepository(session).list_research_inputs(opportunity.id)
            assert len(inputs) == 1  # ONE grounded source: not a weakness

            # 8. one source never auto-rejects: the idea-led engine scores it.
            evaluation = OpportunityScoringService(session).evaluate_opportunity(
                opportunity.id, evaluated_at=NOW
            )
            assert evaluation.score.engine_name == IDEA_LED_ENGINE_NAME
            assert evaluation.score.eligibility is ScoreEligibility.COMMISSIONABLE
            assert evaluation.score.input_snapshot["idea_quality"] == ferris.idea_quality / 100

            # The pack policy follows the origin; factual gates stay.
            packs = EvidencePackService(session)
            assert (
                packs._policy_for(opportunity.id, DEFAULT_EVIDENCE_POLICY)
                is IDEA_LED_EVIDENCE_POLICY
            )  # noqa: SLF001
            assert IDEA_LED_EVIDENCE_POLICY.min_key_facts == 0
            assert DEFAULT_EVIDENCE_POLICY.min_distinct_sources == 2  # intake policy unchanged

            # The intake engine still scores intake promotions the old way.
            intake = OpportunityScoringService(session)
            assert intake._engine_for(opportunity).name == IDEA_LED_ENGINE_NAME  # noqa: SLF001
            opportunity.mission_candidate_id = None
            assert intake._engine_for(opportunity).name == OPPORTUNITY_ENGINE_NAME  # noqa: SLF001


class TestPlannerAndApi:
    def test_idea_led_items_regenerate_ideas_without_a_second_source(self) -> None:
        base = Snapshot(
            work_item_id=uuid.uuid4(),
            state=WorkflowState.EVIDENCE_BUILDING,
            opportunity_id=uuid.uuid4(),
            disposition=OpportunityDisposition.COMMISSIONED,
            idea_count=2,
            ideas_predate_research_inputs=True,
            distinct_input_sources=1,
        )
        assert plan(base, AutopilotMode.AUTONOMOUS).kind == "wait"
        idea_led = dataclasses.replace(base, idea_led=True)
        assert plan(idea_led, AutopilotMode.AUTONOMOUS).name == ACTION_GENERATE_IDEAS

    def test_api_creates_and_queues_a_mission_from_four_fields(self, harness: Harness) -> None:
        queued: list[str] = []

        class Dispatcher:
            def enqueue_run(self, mission_id: str) -> None:
                queued.append(mission_id)

        harness.app.state.mission_dispatcher = Dispatcher()
        response = harness.post(
            "/internal/research-missions",
            json_body={
                "topic": "1 Yaş Doğum Günü Konseptleri",
                "goal": "Annelerin uygulayabileceği yaratıcı ve görsel olarak güçlü konseptler.",
                "audience": "Anneler",
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["queued"] is True
        assert body["mission"]["status"] == "queued"
        assert queued == [body["mission"]["id"]]

        detail = harness.get(f"/internal/research-missions/{body['mission']['id']}")
        assert detail.status_code == 200
        assert detail.json()["mission"]["progress_log"][0]["status"] == "queued"
        assert (
            harness.get("/internal/research-missions").json()[0]["topic"]
            == "1 Yaş Doğum Günü Konseptleri"
        )

        rerun = harness.post(f"/internal/research-missions/{body['mission']['id']}/run")
        assert rerun.status_code == 200 and len(queued) == 2

    def test_api_validation_keeps_missions_truthful(self, harness: Harness) -> None:
        harness.app.state.mission_dispatcher = type(
            "D", (), {"enqueue_run": lambda self, m: None}
        )()
        response = harness.post(
            "/internal/research-missions",
            json_body={"topic": " ", "goal": "x", "audience": "y"},
        )
        assert response.status_code == 422
        with harness.session() as session:
            assert session.scalar(select(ResearchMission)) is None
