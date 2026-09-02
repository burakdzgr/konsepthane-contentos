"""Celery editorial orchestration tests (eager mode, no broker, no network)."""

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from celery import Celery
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import contentos.drafts.models  # noqa: F401  (register draft tables for create_all)
from contentos.ai.enums import GenerationStatus, ProviderFailureKind
from contentos.ai.fake import FakeStructuredProvider
from contentos.ai.models import AiGenerationAttempt
from contentos.briefs.enums import BriefStatus
from contentos.briefs.models import BriefStatusEvent, ContentBrief
from contentos.core.config import Environment, LogLevel, Settings
from contentos.db.base import Base
from contentos.discovery.service import DiscoveryService
from contentos.duplicates.enums import DuplicateDecisionOutcome
from contentos.duplicates.models import DuplicateDecision
from contentos.evidence_packs.models import EvidencePack
from contentos.fetching.models import (
    FetchOutcome,
    FetchResult,
    RetryClassification,
    RobotsDecision,
)
from contentos.fetching.snapshot_service import FetchSnapshotService
from contentos.ideas.models import Idea, IdeaSelectionEvent
from contentos.ideas.service import IdeaService
from contentos.normalization.service import NormalizationService
from contentos.opportunities.enums import (
    OpportunityActor,
    OpportunityDisposition,
    ResearchInputRole,
    ScoreEligibility,
)
from contentos.opportunities.errors import (
    CommissioningConflictError,
    CommissioningGateError,
)
from contentos.opportunities.models import (
    EditorialOpportunity,
    OpportunityResearchInput,
)
from contentos.opportunities.repository import OpportunityRepository
from contentos.opportunities.service import OpportunityCommissioningService
from contentos.queue.celery import create_celery_app
from contentos.research.enums import EvidenceType, ExtractionMethod
from contentos.research.service import ResearchEvidenceService
from contentos.search_intent.models import SearchIntentAnalysis
from contentos.sources.enums import SourceKind, TrustTier
from contentos.sources.service import SourceRegistryService
from contentos.worker.editorial_tasks import (
    ANALYZE_SEARCH_INTENT_TASK,
    BUILD_EVIDENCE_PACK_TASK,
    COMPOSE_CONTENT_BRIEF_TASK,
    EDITORIAL_TASK_NAMES,
    EVALUATE_OPPORTUNITY_TASK,
    GENERATE_IDEA_CANDIDATES_TASK,
    PROMOTE_RESEARCH_TASK,
    register_editorial_pipeline_tasks,
)
from contentos.worker.main import create_worker_app
from contentos.worker.research_tasks import RESEARCH_TASK_NAMES
from contentos.worker.runtime import WorkerRuntime
from contentos.workflow.enums import WorkflowState
from contentos.workflow.repository import WorkflowRepository

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

ROOT_HEADINGS = [
    {"level": 2, "text": "Parti temasını seçmek"},
    {"level": 2, "text": "Davetiye ve misafir listesi"},
    {"level": 2, "text": "Süsleme fikirleri"},
]


def eager_settings() -> Settings:
    return Settings(
        environment=Environment.TEST,
        service_name="ContentOS Editorial Test",
        application_version="1.0.0-test",
        log_level=LogLevel.INFO,
        api_docs_enabled=False,
        celery_task_always_eager=True,
        celery_broker_connection_retry_on_startup=False,
    )


class RecordingDispatcher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], str | None]] = []

    def enqueue(
        self, task_name: str, payload: dict[str, Any], *, request_id: str | None = None
    ) -> None:
        self.calls.append((task_name, payload, request_id))


class FailingOnceDispatcher(RecordingDispatcher):
    """Fails the FIRST enqueue of ``fail_task`` (any task when None)."""

    def __init__(self, fail_task: str | None = None) -> None:
        super().__init__()
        self.fail_task = fail_task
        self.failures = 0

    def enqueue(
        self, task_name: str, payload: dict[str, Any], *, request_id: str | None = None
    ) -> None:
        if self.failures == 0 and self.fail_task in (None, task_name):
            self.failures += 1
            raise ConnectionError("broker publish failed")
        super().enqueue(task_name, payload, request_id=request_id)


class CommitCheckingDispatcher(RecordingDispatcher):
    """Proves the durable result is visible BEFORE the next-stage enqueue."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self._session_factory = session_factory
        self.visibility: list[bool] = []

    def enqueue(
        self, task_name: str, payload: dict[str, Any], *, request_id: str | None = None
    ) -> None:
        with self._session_factory() as independent:
            if task_name == EVALUATE_OPPORTUNITY_TASK:
                visible = (
                    OpportunityRepository(independent).get_by_id(
                        uuid.UUID(payload["opportunity_id"])
                    )
                    is not None
                )
            elif task_name == ANALYZE_SEARCH_INTENT_TASK:
                pack = independent.get(EvidencePack, uuid.UUID(payload["evidence_pack_id"]))
                opportunity = OpportunityRepository(independent).get_by_id(
                    uuid.UUID(payload["opportunity_id"])
                )
                work_item = (
                    WorkflowRepository(independent).get_by_id(opportunity.work_item_id)
                    if opportunity is not None
                    else None
                )
                visible = (
                    pack is not None
                    and work_item is not None
                    and work_item.current_state is WorkflowState.SEO_RESEARCH
                )
            else:
                visible = True
        self.visibility.append(visible)
        super().enqueue(task_name, payload, request_id=request_id)


def _postgres_faithful_sqlite_engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _disable_driver_transactions(dbapi_connection: Any, _record: Any) -> None:
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _emit_begin(connection: Any) -> None:
        connection.exec_driver_sql("BEGIN")

    return engine


class Harness:
    """Shared in-memory DB + eager editorial Celery app + provider seam."""

    def __init__(self) -> None:
        self.engine = _postgres_faithful_sqlite_engine()
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

        @event.listens_for(self.session_factory, "loaded_as_persistent")
        def _restore_utc_awareness(_session: Session, instance: Any) -> None:
            for key, value in list(instance.__dict__.items()):
                if isinstance(value, datetime) and value.tzinfo is None:
                    instance.__dict__[key] = value.replace(tzinfo=UTC)

        self.settings = eager_settings()
        self.provider: FakeStructuredProvider = FakeStructuredProvider(payload={})
        self.runtime = WorkerRuntime(
            self.settings,
            session_factory=self.session_factory,
            structured_generation_provider_factory=lambda: self.provider,
        )

    def app(self, dispatcher: RecordingDispatcher | None = None) -> Celery:
        celery_app = create_celery_app(self.settings)
        register_editorial_pipeline_tasks(
            celery_app, self.runtime, dispatcher=dispatcher or RecordingDispatcher()
        )
        return celery_app

    def session(self) -> Session:
        return self.session_factory()


@pytest.fixture()
def harness() -> Harness:
    return Harness()


def seed_document(harness: Harness) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """Eligible research chain + evidence for both documents."""
    token = uuid.uuid4().hex[:8]
    with harness.session() as session:
        document_ids: list[uuid.UUID] = []
        for index, (slug, title, headings) in enumerate(
            (
                (f"ana-{token}", "Doğum günü partisi fikirleri", ROOT_HEADINGS),
                (f"destek-{token}", "Ev partisi süsleme örnekleri", []),
            )
        ):
            source = SourceRegistryService(session).register_source(
                slug=slug,
                name=f"Kaynak {slug}",
                kind=SourceKind.MANUAL,
                base_url=f"https://{slug}.example.test/",
                trust_tier=TrustTier.GENERAL,
            )
            discoveries = DiscoveryService(session)
            item = discoveries.discover_manual(
                source.id, f"https://{slug}.example.test/haber-{index}"
            )
            discoveries.accept_item(item.id)
            body = f"<html>{slug} govdesi</html>".encode()
            snapshot = FetchSnapshotService(session).record_fetch_result(
                item.id,
                FetchResult(
                    requested_url=item.canonical_url,
                    outcome=FetchOutcome.SUCCESS,
                    retry=RetryClassification.NOT_APPLICABLE,
                    robots_decision=RobotsDecision.ALLOWED,
                    fetched_at=NOW,
                    duration_ms=2.0,
                    final_url=item.canonical_url,
                    status_code=200,
                    content_type="text/html; charset=utf-8",
                    body=body,
                ),
                raw_payload_ref=f"memory:sha256:{hashlib.sha256(body).hexdigest()}",
            )
            document = NormalizationService(session).record_success(
                snapshot.id,
                extractor_name="html-basic",
                extractor_version="1",
                clean_text=f"{slug} için uzun ve özgün araştırma metni.",
                title=title,
                headings=headings,
            )
            document_ids.append(document.id)
        session.commit()
        for document_id in document_ids:
            decision = DuplicateDecision(
                normalized_document_id=document_id,
                engine_name="duplicate-engine",
                engine_version="1",
                decision=DuplicateDecisionOutcome.UNIQUE,
                signals={},
                thresholds={},
                matches=[],
                rationale_codes=[],
                evaluated_at=NOW,
            )
            session.add(decision)
        session.commit()
        return document_ids[0], document_ids


class Pipeline:
    """Drives the editorial pipeline stage by stage through real tasks."""

    def __init__(self, harness: Harness, dispatcher: RecordingDispatcher | None = None):
        self.harness = harness
        self.dispatcher = dispatcher or RecordingDispatcher()
        self.app = harness.app(self.dispatcher)
        self.root_document_id, self.document_ids = seed_document(harness)
        self.opportunity_id: uuid.UUID | None = None
        self.work_item_id: uuid.UUID | None = None
        self.idea_id: uuid.UUID | None = None
        self.pack_id: uuid.UUID | None = None
        self.analysis_id: uuid.UUID | None = None
        self.evidence_ids: list[uuid.UUID] = []

    def run(self, task_name: str, **kwargs: Any) -> Any:
        return self.app.tasks[task_name].apply(kwargs=kwargs)

    def promote(self) -> dict[str, Any]:
        result = self.run(
            PROMOTE_RESEARCH_TASK, normalized_document_id=str(self.root_document_id)
        ).get()
        self.opportunity_id = uuid.UUID(result["opportunity_id"])
        self.work_item_id = uuid.UUID(result["work_item_id"])
        with self.harness.session() as session:
            support_decision = session.execute(
                select(DuplicateDecision).where(
                    DuplicateDecision.normalized_document_id == self.document_ids[1]
                )
            ).scalar_one()
            OpportunityRepository(session).insert_research_input(
                OpportunityResearchInput(
                    opportunity_id=self.opportunity_id,
                    normalized_document_id=self.document_ids[1],
                    duplicate_decision_id=support_decision.id,
                    role=ResearchInputRole.SUPPORTING,
                    added_by=OpportunityActor.OPERATOR,
                    note=None,
                    added_at=NOW,
                )
            )
            session.commit()
            for document_id, statement in (
                (self.document_ids[0], "Kaynak, konsept detaylarını belirtiyor."),
                (self.document_ids[0], "Kaynak, hazırlık süresini belirtiyor."),
                (self.document_ids[1], "İkinci kaynak, bütçe aralığını doğruluyor."),
            ):
                evidence = ResearchEvidenceService(session).record_evidence(
                    document_id,
                    evidence_type=EvidenceType.OBSERVATION,
                    statement=statement,
                    extraction_method=ExtractionMethod.MACHINE,
                    source_locator="structured_metadata.author",
                )
                self.evidence_ids.append(evidence.id)
            session.commit()
        return result

    def score(self, eligibility: ScoreEligibility = ScoreEligibility.COMMISSIONABLE) -> Any:
        result = self.run(EVALUATE_OPPORTUNITY_TASK, opportunity_id=str(self.opportunity_id)).get()
        # SQLite-only deterministic control of the gate under test (real PG
        # forbids score mutation; the commissioning gate reads eligibility).
        with self.harness.session() as session:
            score = OpportunityRepository(session).get_effective_score(self.opportunity_id)
            assert score is not None
            score.eligibility = eligibility
            session.commit()
        return result

    def commission(self) -> Any:
        with self.harness.session() as session:
            result = OpportunityCommissioningService(session).commission_opportunity(
                self.opportunity_id, reason="operatör komisyonu"
            )
            session.commit()
            return result

    def generate_ideas(self) -> dict[str, Any]:
        self.harness.provider = FakeStructuredProvider(payload=idea_batch_payload())
        result = self.run(
            GENERATE_IDEA_CANDIDATES_TASK, opportunity_id=str(self.opportunity_id)
        ).get()
        self.idea_id = uuid.UUID(result["idea_ids"][0])
        return result

    def select_idea(self) -> None:
        with self.harness.session() as session:
            IdeaService(session).select_idea(self.idea_id, reason="tek aday")
            session.commit()

    def selections(self) -> list[dict[str, Any]]:
        return [
            {
                "research_evidence_id": str(self.evidence_ids[0]),
                "role": "key_fact",
                "claim_cluster": "detaylar",
                "display_note": None,
            },
            {
                "research_evidence_id": str(self.evidence_ids[1]),
                "role": "supporting",
                "claim_cluster": "sure",
                "display_note": None,
            },
            {
                "research_evidence_id": str(self.evidence_ids[2]),
                "role": "supporting",
                "claim_cluster": "butce",
                "display_note": None,
            },
        ]

    def build_pack(self, selections: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        result = self.run(
            BUILD_EVIDENCE_PACK_TASK,
            opportunity_id=str(self.opportunity_id),
            idea_id=str(self.idea_id),
            selections=selections if selections is not None else self.selections(),
        ).get()
        if result.get("evidence_pack_id"):
            self.pack_id = uuid.UUID(result["evidence_pack_id"])
        return result

    def analyze(self) -> dict[str, Any]:
        self.harness.provider = FakeStructuredProvider(payload=intent_payload())
        result = self.run(
            ANALYZE_SEARCH_INTENT_TASK,
            opportunity_id=str(self.opportunity_id),
            idea_id=str(self.idea_id),
            evidence_pack_id=str(self.pack_id),
        ).get()
        self.analysis_id = uuid.UUID(result["search_intent_analysis_id"])
        return result

    def compose(self) -> dict[str, Any]:
        self.harness.provider = FakeStructuredProvider(payload=brief_payload(self.evidence_ids))
        return self.run(
            COMPOSE_CONTENT_BRIEF_TASK,
            work_item_id=str(self.work_item_id),
            idea_id=str(self.idea_id),
            evidence_pack_id=str(self.pack_id),
            search_intent_analysis_id=str(self.analysis_id),
        ).get()

    def state(self) -> WorkflowState:
        with self.harness.session() as session:
            work_item = WorkflowRepository(session).get_by_id(self.work_item_id)
            assert work_item is not None
            return work_item.current_state

    def events(self) -> list[Any]:
        with self.harness.session() as session:
            return WorkflowRepository(session).list_events(self.work_item_id)


def idea_batch_payload() -> dict[str, Any]:
    dims = dict.fromkeys(
        (
            "theme",
            "cake",
            "budget_band",
            "space",
            "preparation_time",
            "diy_level",
            "suitability",
            "color_palette",
            "decorations",
            "menu",
            "shopping_list",
            "practical_steps",
        )
    )
    dims["theme"] = "balon teması"
    return {
        "candidates": [
            {
                "working_title": f"Evde balon temalı plan {index}",
                "angle": f"Aday {index}: bütçe dostu üç saatlik hazırlık akışı.",
                "audience": "Küçük çocuklu ebeveynler",
                "value_proposition": "Tek listeyle eksiksiz parti hazırlığı sağlar.",
                "rationale": "Kaynaklar genel; biz uygulanabilir zaman çizelgesi veriyoruz.",
                "content_type": "planning_guide",
                "exclusions": ["marka önerme"],
                "planning_dimensions": dims,
            }
            for index in range(3)
        ]
    }


def intent_payload() -> dict[str, Any]:
    return {
        "primary_intent": "Ev partisi planlama rehberi arayışı",
        "secondary_intents": ["fikir arayışı"],
        "query_concepts": ["evde doğum günü partisi", "parti hazırlık listesi"],
        "page_purpose": "Kapsamlı, uygulanabilir planlama rehberi sunmak",
        "likely_format": "planlama rehberi",
    }


def brief_payload(evidence_ids: list[uuid.UUID]) -> dict[str, Any]:
    return {
        "intent_summary": "Okur evde doğum günü partisi planlamak istiyor.",
        "content_objective": "Okura eksiksiz, bütçe dostu bir plan kazandırmak.",
        "required_sections": [
            {
                "key": "giris",
                "heading_guidance": "Neden evde parti?",
                "purpose": "Bağlam ve değer önerisi.",
            },
            {
                "key": "plan",
                "heading_guidance": "Üç saatlik hazırlık planı",
                "purpose": "Adım adım zaman çizelgesi.",
            },
            {
                "key": "butce",
                "heading_guidance": "Bütçe dostu öneriler",
                "purpose": "Maliyet kalemleri ve alternatifler.",
            },
        ],
        "optional_sections": [],
        "title_direction": "Balon temalı pratik plan vurgusu",
        "title_constraints": [],
        "additional_exclusions": [],
        "additional_uncertainty_notes": [],
        "internal_link_needs": [],
        "media_needs": [],
        "faq_questions": [],
        "acceptance_criteria": [],
        "claims": [
            {
                "claim_key": "konsept-detaylari",
                "claim_text": "Kaynaklar konsept detaylarını belirtir.",
                "claim_kind": "factual",
                "handling": None,
                "evidence_ids": [str(evidence_ids[0])],
            },
            {
                "claim_key": "butce-araligi",
                "claim_text": "İkinci kaynak bir bütçe aralığı aktarır.",
                "claim_kind": "source_assertion",
                "handling": None,
                "evidence_ids": [str(evidence_ids[2])],
            },
        ],
    }


class TestRegistration:
    def test_worker_app_registers_both_pipelines_without_side_effects(self) -> None:
        app = create_worker_app(eager_settings())
        for name in RESEARCH_TASK_NAMES + EDITORIAL_TASK_NAMES:
            assert name in app.tasks
        assert len(RESEARCH_TASK_NAMES) == 5
        assert len(EDITORIAL_TASK_NAMES) == 7


class TestPromotionAndScoring:
    def test_promotion_commits_before_dispatch(self, harness: Harness) -> None:
        dispatcher = CommitCheckingDispatcher(harness.session_factory)
        pipeline = Pipeline(harness, dispatcher)
        result = pipeline.promote()
        assert result["status"] == "completed"
        assert pipeline.state() is WorkflowState.IDEA_SCORING
        [(task_name, payload, _)] = dispatcher.calls
        assert task_name == EVALUATE_OPPORTUNITY_TASK
        assert payload == {"opportunity_id": str(pipeline.opportunity_id)}
        # The promoted rows were already visible to an independent session.
        assert dispatcher.visibility == [True]

    def test_promotion_dispatch_failure_and_redelivery(self, harness: Harness) -> None:
        dispatcher = FailingOnceDispatcher()
        pipeline = Pipeline(harness, dispatcher)
        outcome = pipeline.run(
            PROMOTE_RESEARCH_TASK, normalized_document_id=str(pipeline.root_document_id)
        )
        # The eager DISPATCH retry chain resolved inline: the promotion
        # committed before the failed enqueue, and the retry REUSED it.
        result = outcome.get()
        assert result["status"] == "reused"
        assert dispatcher.failures == 1
        assert [call[0] for call in dispatcher.calls] == [EVALUATE_OPPORTUNITY_TASK]
        with harness.session() as session:
            opportunity = session.execute(select(EditorialOpportunity)).scalar_one()
            assert opportunity.disposition is OpportunityDisposition.OPEN
        # Redelivery reuses the durable promotion and only redispatches.
        redelivery = pipeline.run(
            PROMOTE_RESEARCH_TASK, normalized_document_id=str(pipeline.root_document_id)
        ).get()
        assert redelivery["status"] == "reused"
        assert dispatcher.calls[-1][0] == EVALUATE_OPPORTUNITY_TASK
        with harness.session() as session:
            events = WorkflowRepository(session).list_events(uuid.UUID(redelivery["work_item_id"]))
            assert len(events) == 1  # exactly one creation event

    def test_scoring_creates_and_reuses_without_side_effects(self, harness: Harness) -> None:
        pipeline = Pipeline(harness)
        pipeline.promote()
        first = pipeline.run(
            EVALUATE_OPPORTUNITY_TASK, opportunity_id=str(pipeline.opportunity_id)
        ).get()
        second = pipeline.run(
            EVALUATE_OPPORTUNITY_TASK, opportunity_id=str(pipeline.opportunity_id)
        ).get()
        assert first["status"] == "completed"
        assert second["status"] == "reused"
        assert second["opportunity_score_id"] == first["opportunity_score_id"]
        assert pipeline.state() is WorkflowState.IDEA_SCORING
        with harness.session() as session:
            opportunity = OpportunityRepository(session).get_by_id(pipeline.opportunity_id)
            assert opportunity is not None
            assert opportunity.disposition is OpportunityDisposition.OPEN


class TestCommissioning:
    def test_happy_path(self, harness: Harness) -> None:
        pipeline = Pipeline(harness)
        pipeline.promote()
        score_summary = pipeline.score()
        result = pipeline.commission()
        assert result.commissioned is True
        assert str(result.opportunity_score_id) == score_summary["opportunity_score_id"]
        with harness.session() as session:
            opportunity = OpportunityRepository(session).get_by_id(pipeline.opportunity_id)
            assert opportunity is not None
            assert opportunity.disposition is OpportunityDisposition.COMMISSIONED
            assert opportunity.disposition_reason == "operatör komisyonu"
            assert opportunity.disposition_by is OpportunityActor.OPERATOR
        events = pipeline.events()
        assert events[-1].to_state is WorkflowState.EVIDENCE_BUILDING
        assert events[-1].artifact_refs == {
            "opportunity_id": str(pipeline.opportunity_id),
            "opportunity_score_id": score_summary["opportunity_score_id"],
        }
        # Idempotent repeat: no second event, no rewrite.
        repeat = pipeline.commission()
        assert repeat.commissioned is False
        assert len(pipeline.events()) == len(events)

    def test_gates(self, harness: Harness) -> None:
        pipeline = Pipeline(harness)
        pipeline.promote()
        # No score at all.
        with harness.session() as session:
            with pytest.raises(CommissioningGateError, match="no durable"):
                OpportunityCommissioningService(session).commission_opportunity(
                    pipeline.opportunity_id, reason="erken komisyon"
                )
        # NOT_COMMISSIONABLE and NEEDS_OPERATOR_REVIEW both fail closed.
        for eligibility in (
            ScoreEligibility.NOT_COMMISSIONABLE,
            ScoreEligibility.NEEDS_OPERATOR_REVIEW,
        ):
            pipeline.score(eligibility)
            with harness.session() as session:
                with pytest.raises(CommissioningGateError, match="eligibility"):
                    OpportunityCommissioningService(session).commission_opportunity(
                        pipeline.opportunity_id, reason="komisyon"
                    )
        assert pipeline.state() is WorkflowState.IDEA_SCORING
        with harness.session() as session:
            opportunity = OpportunityRepository(session).get_by_id(pipeline.opportunity_id)
            assert opportunity is not None
            assert opportunity.disposition is OpportunityDisposition.OPEN

    def test_rollback_leaves_no_half_commission(self, harness: Harness) -> None:
        pipeline = Pipeline(harness)
        pipeline.promote()
        pipeline.score()
        with harness.session() as session:
            OpportunityCommissioningService(session).commission_opportunity(
                pipeline.opportunity_id, reason="geri alınacak komisyon"
            )
            session.rollback()
        assert pipeline.state() is WorkflowState.IDEA_SCORING
        with harness.session() as session:
            opportunity = OpportunityRepository(session).get_by_id(pipeline.opportunity_id)
            assert opportunity is not None
            assert opportunity.disposition is OpportunityDisposition.OPEN

    def test_inconsistent_history_is_a_typed_conflict(self, harness: Harness) -> None:
        pipeline = Pipeline(harness)
        pipeline.promote()
        with harness.session() as session:
            opportunity = OpportunityRepository(session).get_by_id(pipeline.opportunity_id)
            assert opportunity is not None
            opportunity.disposition = OpportunityDisposition.COMMISSIONED
            opportunity.disposition_reason = "tutarsız geçmiş simülasyonu"
            opportunity.disposition_at = NOW
            opportunity.disposition_by = OpportunityActor.OPERATOR
            session.commit()
            with pytest.raises(CommissioningConflictError, match="history"):
                OpportunityCommissioningService(session).commission_opportunity(
                    pipeline.opportunity_id, reason="tekrar"
                )


class TestIdeaGeneration:
    def test_generates_after_commission_with_no_side_effects(self, harness: Harness) -> None:
        pipeline = Pipeline(harness)
        pipeline.promote()
        pipeline.score()
        pipeline.commission()
        events_before = len(pipeline.events())
        result = pipeline.generate_ideas()
        assert result["status"] == "completed"
        assert len(result["idea_ids"]) == 3
        assert pipeline.state() is WorkflowState.EVIDENCE_BUILDING
        assert len(pipeline.events()) == events_before
        with harness.session() as session:
            assert session.execute(select(IdeaSelectionEvent)).scalar_one_or_none() is None

    def test_rejected_before_commission_without_provider_call(self, harness: Harness) -> None:
        pipeline = Pipeline(harness)
        pipeline.promote()
        harness.provider = FakeStructuredProvider(payload=idea_batch_payload())
        outcome = pipeline.run(
            GENERATE_IDEA_CANDIDATES_TASK, opportunity_id=str(pipeline.opportunity_id)
        )
        assert outcome.state == "FAILURE"
        assert harness.provider.invocations == 0

    def test_ai_timeout_commits_attempts_and_retries_within_bound(self, harness: Harness) -> None:
        pipeline = Pipeline(harness)
        pipeline.promote()
        pipeline.score()
        pipeline.commission()
        harness.provider = FakeStructuredProvider(
            failure=ProviderFailureKind.TIMEOUT, failure_class="deadline"
        )
        # The eager DOMAIN retry chain runs to the bound: 1 + MAX_RETRIES
        # executions, each a DISTINCT durable attempt, then terminal.
        result = pipeline.run(
            GENERATE_IDEA_CANDIDATES_TASK, opportunity_id=str(pipeline.opportunity_id)
        ).get()
        assert result["status"] == "ai_failed"
        assert result["attempt_status"] == "timeout"
        assert harness.provider.invocations == 4
        with harness.session() as session:
            attempts = session.execute(select(AiGenerationAttempt)).scalars().all()
            assert len(attempts) == 4  # every failed attempt was COMMITTED
            assert {attempt.retry_number for attempt in attempts} == {0, 1, 2, 3}
            assert all(attempt.status is GenerationStatus.TIMEOUT for attempt in attempts)
            assert session.execute(select(Idea)).scalar_one_or_none() is None
        assert pipeline.state() is WorkflowState.EVIDENCE_BUILDING

    def test_validation_failure_is_terminal_without_retry(self, harness: Harness) -> None:
        pipeline = Pipeline(harness)
        pipeline.promote()
        pipeline.score()
        pipeline.commission()
        harness.provider = FakeStructuredProvider(payload={"candidates": "broken"})
        result = pipeline.run(
            GENERATE_IDEA_CANDIDATES_TASK, opportunity_id=str(pipeline.opportunity_id)
        ).get()
        assert result["status"] == "ai_failed"
        assert result["attempt_status"] == "validation_failed"
        with harness.session() as session:
            assert session.execute(select(Idea)).scalar_one_or_none() is None
        assert pipeline.state() is WorkflowState.EVIDENCE_BUILDING


def advance_to_selected_idea(pipeline: Pipeline) -> None:
    pipeline.promote()
    pipeline.score()
    pipeline.commission()
    pipeline.generate_ideas()
    pipeline.select_idea()


class TestEvidencePackTask:
    def test_ready_pack_transitions_and_dispatches_after_commit(self, harness: Harness) -> None:
        dispatcher = CommitCheckingDispatcher(harness.session_factory)
        pipeline = Pipeline(harness, dispatcher)
        advance_to_selected_idea(pipeline)
        result = pipeline.build_pack()
        assert result["status"] == "completed"
        assert result["sufficiency"] == "ready"
        assert pipeline.state() is WorkflowState.SEO_RESEARCH
        transition = pipeline.events()[-1]
        assert transition.to_state is WorkflowState.SEO_RESEARCH
        assert transition.actor_origin.value == "system"
        assert transition.artifact_refs["evidence_pack_id"] == result["evidence_pack_id"]
        assert transition.artifact_refs["sufficiency"] == "ready"
        analysis_calls = [
            call for call in dispatcher.calls if call[0] == ANALYZE_SEARCH_INTENT_TASK
        ]
        assert len(analysis_calls) == 1
        assert analysis_calls[0][1]["evidence_pack_id"] == result["evidence_pack_id"]
        # Pack + SEO_RESEARCH state were durable BEFORE the enqueue.
        assert dispatcher.visibility[-1] is True

    def test_non_ready_pack_blocks_without_dispatch(self, harness: Harness) -> None:
        dispatcher = RecordingDispatcher()
        pipeline = Pipeline(harness, dispatcher)
        advance_to_selected_idea(pipeline)
        result = pipeline.build_pack(selections=pipeline.selections()[:2])
        assert result["status"] == "blocked"
        assert result["sufficiency"] == "insufficient"
        assert pipeline.state() is WorkflowState.BLOCKED
        blocked = pipeline.events()[-1]
        assert blocked.to_state is WorkflowState.BLOCKED
        assert result["evidence_pack_id"] in blocked.reason
        assert "missing" in blocked.reason
        assert blocked.artifact_refs["evidence_pack_id"] == result["evidence_pack_id"]
        assert not any(call[0] == ANALYZE_SEARCH_INTENT_TASK for call in dispatcher.calls)

    def test_redelivery_after_transition(self, harness: Harness) -> None:
        dispatcher = RecordingDispatcher()
        pipeline = Pipeline(harness, dispatcher)
        advance_to_selected_idea(pipeline)
        first = pipeline.build_pack()
        events_before = len(pipeline.events())
        redelivery = pipeline.build_pack()
        assert redelivery["evidence_pack_id"] == first["evidence_pack_id"]
        assert len(pipeline.events()) == events_before  # no duplicate transition
        analysis_calls = [
            call for call in dispatcher.calls if call[0] == ANALYZE_SEARCH_INTENT_TASK
        ]
        assert len(analysis_calls) == 2  # only the dispatch repeats

    def test_dispatch_failure_recovery(self, harness: Harness) -> None:
        dispatcher = FailingOnceDispatcher(ANALYZE_SEARCH_INTENT_TASK)
        pipeline = Pipeline(harness, dispatcher)
        advance_to_selected_idea(pipeline)
        transitions_before = len(pipeline.events())
        result = pipeline.run(
            BUILD_EVIDENCE_PACK_TASK,
            opportunity_id=str(pipeline.opportunity_id),
            idea_id=str(pipeline.idea_id),
            selections=pipeline.selections(),
        ).get()
        # Pack + SEO_RESEARCH transition committed before the failed enqueue;
        # the eager DISPATCH retry chain redid ONLY the enqueue.
        assert result["status"] == "reused"
        assert dispatcher.failures == 1
        assert pipeline.state() is WorkflowState.SEO_RESEARCH
        assert len(pipeline.events()) == transitions_before + 1  # one transition
        analysis_calls = [
            call for call in dispatcher.calls if call[0] == ANALYZE_SEARCH_INTENT_TASK
        ]
        assert len(analysis_calls) == 1


def advance_to_ready_pack(pipeline: Pipeline) -> None:
    advance_to_selected_idea(pipeline)
    pipeline.build_pack()


class TestSearchIntentTask:
    def test_happy_path_transitions_to_briefing(self, harness: Harness) -> None:
        dispatcher = RecordingDispatcher()
        pipeline = Pipeline(harness, dispatcher)
        advance_to_ready_pack(pipeline)
        result = pipeline.analyze()
        assert result["status"] == "completed"
        assert result["missing_signals"]  # zero explicit signals -> honest gaps
        assert pipeline.state() is WorkflowState.BRIEFING
        transition = pipeline.events()[-1]
        assert transition.to_state is WorkflowState.BRIEFING
        assert (
            transition.artifact_refs["search_intent_analysis_id"]
            == result["search_intent_analysis_id"]
        )
        # Brief composition is an operator command: no compose dispatch.
        assert not any(call[0] == COMPOSE_CONTENT_BRIEF_TASK for call in dispatcher.calls)

    def test_failure_keeps_seo_research(self, harness: Harness) -> None:
        pipeline = Pipeline(harness)
        advance_to_ready_pack(pipeline)
        harness.provider = FakeStructuredProvider(
            failure=ProviderFailureKind.CANCELLED, failure_class="cancelled"
        )
        result = pipeline.run(
            ANALYZE_SEARCH_INTENT_TASK,
            opportunity_id=str(pipeline.opportunity_id),
            idea_id=str(pipeline.idea_id),
            evidence_pack_id=str(pipeline.pack_id),
        ).get()
        assert result["status"] == "ai_failed"
        assert pipeline.state() is WorkflowState.SEO_RESEARCH
        with harness.session() as session:
            assert session.execute(select(SearchIntentAnalysis)).scalar_one_or_none() is None

    def test_redelivery_reuses_analysis_and_event(self, harness: Harness) -> None:
        pipeline = Pipeline(harness)
        advance_to_ready_pack(pipeline)
        first = pipeline.analyze()
        events_before = len(pipeline.events())
        provider_before = harness.provider
        redelivery = pipeline.run(
            ANALYZE_SEARCH_INTENT_TASK,
            opportunity_id=str(pipeline.opportunity_id),
            idea_id=str(pipeline.idea_id),
            evidence_pack_id=str(pipeline.pack_id),
        ).get()
        assert redelivery["search_intent_analysis_id"] == first["search_intent_analysis_id"]
        assert redelivery["status"] == "reused"
        assert provider_before.invocations == 1  # provider untouched on reuse
        assert len(pipeline.events()) == events_before


class TestComposeTask:
    def test_happy_path_stays_briefing_draft(self, harness: Harness) -> None:
        pipeline = Pipeline(harness)
        advance_to_ready_pack(pipeline)
        pipeline.analyze()
        result = pipeline.compose()
        assert result["status"] == "completed"
        assert result["brief_status"] == "draft"
        assert result["structure_guard"] == "passed"
        assert pipeline.state() is WorkflowState.BRIEFING
        with harness.session() as session:
            brief = session.execute(select(ContentBrief)).scalar_one()
            assert brief.status is BriefStatus.DRAFT
            assert brief.engine_name == "brief-composer"
            assert brief.composition_attempt_id is not None
            assert session.execute(select(BriefStatusEvent)).scalar_one_or_none() is None
        # Even a perfectly valid draft is never auto-accepted.
        events = pipeline.events()
        assert events[-1].to_state is WorkflowState.BRIEFING

    def test_exact_retry_reuses_brief(self, harness: Harness) -> None:
        pipeline = Pipeline(harness)
        advance_to_ready_pack(pipeline)
        pipeline.analyze()
        first = pipeline.compose()
        compose_provider = harness.provider
        redelivery = pipeline.run(
            COMPOSE_CONTENT_BRIEF_TASK,
            work_item_id=str(pipeline.work_item_id),
            idea_id=str(pipeline.idea_id),
            evidence_pack_id=str(pipeline.pack_id),
            search_intent_analysis_id=str(pipeline.analysis_id),
        ).get()
        assert redelivery["content_brief_id"] == first["content_brief_id"]
        assert redelivery["status"] == "reused"
        assert compose_provider.invocations == 1
        assert pipeline.state() is WorkflowState.BRIEFING

    def test_validation_failure_leaves_no_brief(self, harness: Harness) -> None:
        pipeline = Pipeline(harness)
        advance_to_ready_pack(pipeline)
        pipeline.analyze()
        harness.provider = FakeStructuredProvider(payload={"claims": "broken"})
        result = pipeline.run(
            COMPOSE_CONTENT_BRIEF_TASK,
            work_item_id=str(pipeline.work_item_id),
            idea_id=str(pipeline.idea_id),
            evidence_pack_id=str(pipeline.pack_id),
            search_intent_analysis_id=str(pipeline.analysis_id),
        ).get()
        assert result["status"] == "ai_failed"
        with harness.session() as session:
            assert session.execute(select(ContentBrief)).scalar_one_or_none() is None
        assert pipeline.state() is WorkflowState.BRIEFING


class TestTransport:
    def test_request_id_propagates_through_dispatch(self, harness: Harness) -> None:
        dispatcher = RecordingDispatcher()
        pipeline = Pipeline(harness, dispatcher)
        seeded_root = pipeline.root_document_id
        pipeline.app.tasks[PROMOTE_RESEARCH_TASK].apply(
            kwargs={"normalized_document_id": str(seeded_root)},
            headers={"request_id": "req-editorial-1"},
        )
        [(task_name, _, request_id)] = dispatcher.calls
        assert task_name == EVALUATE_OPPORTUNITY_TASK
        assert request_id == "req-editorial-1"

    def test_invalid_request_id_is_not_propagated(self, harness: Harness) -> None:
        dispatcher = RecordingDispatcher()
        pipeline = Pipeline(harness, dispatcher)
        pipeline.app.tasks[PROMOTE_RESEARCH_TASK].apply(
            kwargs={"normalized_document_id": str(pipeline.root_document_id)},
            headers={"request_id": "bad id!"},
        )
        [(_, _, request_id)] = dispatcher.calls
        assert request_id is None

    def test_dispatched_payloads_are_json_safe(self, harness: Harness) -> None:
        dispatcher = RecordingDispatcher()
        pipeline = Pipeline(harness, dispatcher)
        advance_to_selected_idea(pipeline)
        pipeline.build_pack()
        for _, payload, _ in dispatcher.calls:
            for value in payload.values():
                assert isinstance(value, str | int | float | bool | list | dict | type(None))
                if isinstance(value, list):
                    assert all(isinstance(entry, str) for entry in value)

    def test_malformed_uuid_is_terminal(self, harness: Harness) -> None:
        pipeline = Pipeline(harness)
        outcome = pipeline.run(EVALUATE_OPPORTUNITY_TASK, opportunity_id="not-a-uuid")
        assert outcome.state == "FAILURE"
        assert "not-a-uuid" not in str(outcome.result)


class TestWriterDraftTask:
    """contentos.editorial.generate_writer_draft (Phase 4 Task 5)."""

    def accepted(self, harness: Harness) -> Any:
        from test_drafts import accepted_context

        return accepted_context(harness)

    def test_valid_draft_transitions_to_editing(self, harness: Harness) -> None:
        from test_writer_generation import writer_payload

        from contentos.worker.editorial_tasks import GENERATE_WRITER_DRAFT_TASK

        dispatcher = RecordingDispatcher()
        app = harness.app(dispatcher)
        accepted = self.accepted(harness)
        harness.provider = FakeStructuredProvider(payload=writer_payload(accepted))

        result = (
            app.tasks[GENERATE_WRITER_DRAFT_TASK]
            .apply(kwargs={"content_brief_id": str(accepted.context.brief_id)})
            .get()
        )
        assert result["status"] == "completed"
        draft_id = result["content_draft_id"]

        with harness.session() as session:
            item = WorkflowRepository(session).get_by_id(accepted.context.work_item_id)
            assert item is not None and item.current_state is WorkflowState.EDITING
            events = WorkflowRepository(session).list_events(accepted.context.work_item_id)
            transition = events[-1]
            assert transition.to_state is WorkflowState.EDITING
            assert transition.actor_origin.value == "system"
            assert transition.artifact_refs["content_draft_id"] == draft_id
            assert transition.artifact_refs["content_brief_id"] == str(accepted.context.brief_id)
            assert transition.artifact_refs["draft_version"] == 1
        # Editor does not exist: nothing is dispatched downstream.
        assert dispatcher.calls == []

    def test_redelivery_reuses_draft_and_transition(self, harness: Harness) -> None:
        from test_writer_generation import writer_payload

        from contentos.drafts.models import ContentDraft
        from contentos.worker.editorial_tasks import GENERATE_WRITER_DRAFT_TASK

        app = harness.app(RecordingDispatcher())
        accepted = self.accepted(harness)
        harness.provider = FakeStructuredProvider(payload=writer_payload(accepted))
        kwargs = {"content_brief_id": str(accepted.context.brief_id)}

        first = app.tasks[GENERATE_WRITER_DRAFT_TASK].apply(kwargs=kwargs).get()
        with harness.session() as session:
            events_before = len(
                WorkflowRepository(session).list_events(accepted.context.work_item_id)
            )
        redelivered = app.tasks[GENERATE_WRITER_DRAFT_TASK].apply(kwargs=kwargs).get()
        assert redelivered["status"] == "reused"
        assert redelivered["content_draft_id"] == first["content_draft_id"]
        assert harness.provider.invocations == 1
        with harness.session() as session:
            events_after = len(
                WorkflowRepository(session).list_events(accepted.context.work_item_id)
            )
            drafts = session.execute(select(ContentDraft)).scalars().all()
        assert events_after == events_before
        assert len(drafts) == 1

    def test_validation_failure_keeps_drafting(self, harness: Harness) -> None:
        import uuid as _uuid

        from test_writer_generation import writer_payload

        from contentos.drafts.models import ContentDraft
        from contentos.worker.editorial_tasks import GENERATE_WRITER_DRAFT_TASK

        app = harness.app(RecordingDispatcher())
        accepted = self.accepted(harness)
        bad = writer_payload(accepted)
        bad["sections"][0]["blocks"][1]["claim_refs"] = [str(_uuid.uuid4())]
        harness.provider = FakeStructuredProvider(payload=bad)

        result = (
            app.tasks[GENERATE_WRITER_DRAFT_TASK]
            .apply(kwargs={"content_brief_id": str(accepted.context.brief_id)})
            .get()
        )
        assert result["status"] == "ai_failed"
        assert result["attempt_status"] == "validation_failed"
        with harness.session() as session:
            item = WorkflowRepository(session).get_by_id(accepted.context.work_item_id)
            assert item is not None and item.current_state is WorkflowState.DRAFTING
            assert session.execute(select(ContentDraft)).scalar_one_or_none() is None

    def test_timeout_retries_within_bound_then_terminal(self, harness: Harness) -> None:
        from contentos.drafts.models import ContentDraft
        from contentos.worker.editorial_tasks import GENERATE_WRITER_DRAFT_TASK

        app = harness.app(RecordingDispatcher())
        accepted = self.accepted(harness)
        harness.provider = FakeStructuredProvider(
            failure=ProviderFailureKind.TIMEOUT, failure_class="deadline"
        )
        result = (
            app.tasks[GENERATE_WRITER_DRAFT_TASK]
            .apply(kwargs={"content_brief_id": str(accepted.context.brief_id)})
            .get()
        )
        assert result["status"] == "ai_failed"
        assert result["attempt_status"] == "timeout"
        assert harness.provider.invocations == 4  # 1 + MAX_RETRIES distinct attempts
        with harness.session() as session:
            attempts = session.execute(select(AiGenerationAttempt)).scalars().all()
            writer_attempts = [a for a in attempts if a.purpose.value == "writer_draft"]
            assert {a.retry_number for a in writer_attempts} == {0, 1, 2, 3}
            item = WorkflowRepository(session).get_by_id(accepted.context.work_item_id)
            assert item is not None and item.current_state is WorkflowState.DRAFTING
            assert session.execute(select(ContentDraft)).scalar_one_or_none() is None

    def test_unaccepted_brief_is_terminal_with_zero_invocations(self, harness: Harness) -> None:
        from editorial_harness import Context as HContext
        from editorial_harness import seed_draft_brief

        from contentos.worker.editorial_tasks import GENERATE_WRITER_DRAFT_TASK

        app = harness.app(RecordingDispatcher())
        with harness.session() as session:
            context = HContext()
            seed_draft_brief(session, context)  # brief stays DRAFT
            session.commit()
        harness.provider = FakeStructuredProvider(payload={})
        outcome = app.tasks[GENERATE_WRITER_DRAFT_TASK].apply(
            kwargs={"content_brief_id": str(context.brief_id)}
        )
        assert outcome.state == "FAILURE"
        assert harness.provider.invocations == 0
