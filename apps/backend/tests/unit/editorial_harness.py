"""Shared harness for the editorial read/control API tests (not collected).

Real services over PG-faithful in-memory SQLite behind the real FastAPI app;
producer dispatchers replaced with recording fakes. Seeding drives the REAL
Phase-3 domain services (promotion, scoring, commissioning, generation,
selection, packs, intent synthesis, brief composition) — never direct ORM
state invention beyond the two documented SQLite-only knobs (duplicate
decision rows and score eligibility control).
"""

import asyncio
import hashlib
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from contentos.ai.fake import FakeStructuredProvider
from contentos.api.app import create_app
from contentos.briefs.composition import BriefCompositionEngine
from contentos.core.config import Environment, LogLevel, Settings
from contentos.db.base import Base
from contentos.discovery.service import DiscoveryService
from contentos.duplicates.enums import DuplicateDecisionOutcome
from contentos.duplicates.models import DuplicateDecision
from contentos.evidence_packs.enums import ContradictionSeverity, EvidenceItemRole
from contentos.evidence_packs.service import (
    ContradictionDeclaration,
    EvidencePackService,
    EvidenceSelection,
)
from contentos.fetching.models import (
    FetchOutcome,
    FetchResult,
    RetryClassification,
    RobotsDecision,
)
from contentos.fetching.snapshot_service import FetchSnapshotService
from contentos.ideas.generation import IdeaGenerationEngine
from contentos.ideas.service import IdeaService
from contentos.media.store import MediaStore
from contentos.normalization.service import NormalizationService
from contentos.opportunities.enums import (
    OpportunityActor,
    ResearchInputRole,
    ScoreEligibility,
)
from contentos.opportunities.models import OpportunityResearchInput
from contentos.opportunities.repository import OpportunityRepository
from contentos.opportunities.scoring_service import OpportunityScoringService
from contentos.opportunities.service import (
    OpportunityCommissioningService,
    ResearchPromotionService,
)
from contentos.research.enums import EvidenceType, ExtractionMethod
from contentos.research.service import ResearchEvidenceService
from contentos.search_intent.service import SearchIntentService
from contentos.signals.enums import SearchSignalType
from contentos.signals.service import SearchSignalService
from contentos.sources.enums import SourceKind, TrustTier
from contentos.sources.service import SourceRegistryService
from contentos.workflow.enums import WorkflowActorOrigin, WorkflowState
from contentos.workflow.service import WorkflowService

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

ROOT_HEADINGS = [
    {"level": 2, "text": "Parti temasını seçmek"},
    {"level": 2, "text": "Davetiye ve misafir listesi"},
    {"level": 2, "text": "Süsleme fikirleri"},
    {"level": 2, "text": "Pasta ve ikramlar"},
]


def api_settings() -> Settings:
    return Settings(
        environment=Environment.TEST,
        service_name="ContentOS Editorial API Test",
        application_version="1.0.0-test",
        log_level=LogLevel.INFO,
        api_docs_enabled=False,
        database_url="postgresql+psycopg://contentos:api-secret@localhost:5432/contentos_api",
        redis_broker_url="redis://:api-secret@localhost:6379/0",
    )


class FakeEditorialControlDispatcher:
    """Records (task_label, entity_id, kwargs, request_id) per publish."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], str | None]] = []

    def enqueue_promote(
        self, normalized_document_id: str, *, request_id: str | None = None
    ) -> None:
        self.calls.append(
            ("promote_research", {"normalized_document_id": normalized_document_id}, request_id)
        )

    def enqueue_evaluate(self, opportunity_id: str, *, request_id: str | None = None) -> None:
        self.calls.append(("evaluate_opportunity", {"opportunity_id": opportunity_id}, request_id))

    def enqueue_generate_ideas(
        self,
        opportunity_id: str,
        *,
        candidate_count: int,
        retry_number: int,
        request_id: str | None = None,
    ) -> None:
        self.calls.append(
            (
                "generate_idea_candidates",
                {
                    "opportunity_id": opportunity_id,
                    "candidate_count": candidate_count,
                    "retry_number": retry_number,
                },
                request_id,
            )
        )

    def enqueue_build_pack(
        self,
        opportunity_id: str,
        *,
        idea_id: str,
        selections: list[dict[str, Any]],
        contradictions: list[dict[str, Any]] | None,
        request_id: str | None = None,
    ) -> None:
        self.calls.append(
            (
                "build_evidence_pack",
                {
                    "opportunity_id": opportunity_id,
                    "idea_id": idea_id,
                    "selections": selections,
                    "contradictions": contradictions,
                },
                request_id,
            )
        )

    def enqueue_analyze_intent(
        self,
        opportunity_id: str,
        *,
        idea_id: str,
        evidence_pack_id: str,
        signal_ids: list[str],
        retry_number: int,
        request_id: str | None = None,
    ) -> None:
        self.calls.append(
            (
                "analyze_search_intent",
                {
                    "opportunity_id": opportunity_id,
                    "idea_id": idea_id,
                    "evidence_pack_id": evidence_pack_id,
                    "signal_ids": signal_ids,
                    "retry_number": retry_number,
                },
                request_id,
            )
        )

    def enqueue_compose_brief(
        self,
        work_item_id: str,
        *,
        idea_id: str,
        evidence_pack_id: str,
        search_intent_analysis_id: str,
        retry_number: int,
        supersede_reason: str | None,
        request_id: str | None = None,
    ) -> None:
        self.calls.append(
            (
                "compose_content_brief",
                {
                    "work_item_id": work_item_id,
                    "idea_id": idea_id,
                    "evidence_pack_id": evidence_pack_id,
                    "search_intent_analysis_id": search_intent_analysis_id,
                    "retry_number": retry_number,
                    "supersede_reason": supersede_reason,
                },
                request_id,
            )
        )

    def enqueue_generate_writer_draft(
        self,
        content_brief_id: str,
        *,
        retry_number: int,
        supersede_reason: str | None,
        request_id: str | None = None,
    ) -> None:
        self.calls.append(
            (
                "generate_writer_draft",
                {
                    "content_brief_id": content_brief_id,
                    "retry_number": retry_number,
                    "supersede_reason": supersede_reason,
                },
                request_id,
            )
        )

    def enqueue_generate_editor_review(
        self,
        work_item_id: str,
        *,
        retry_number: int,
        supersede_reason: str | None,
        request_id: str | None = None,
    ) -> None:
        self.calls.append(
            (
                "generate_editor_review",
                {
                    "work_item_id": work_item_id,
                    "retry_number": retry_number,
                    "supersede_reason": supersede_reason,
                },
                request_id,
            )
        )

    def enqueue_run_qa(self, work_item_id: str, *, request_id: str | None = None) -> None:
        self.calls.append(("run_qa_gates", {"work_item_id": work_item_id}, request_id))

    def enqueue_generate_media_image(
        self,
        work_item_id: str,
        need_index: int,
        requested_by_user_id: str,
        *,
        request_id: str | None = None,
    ) -> None:
        self.calls.append(
            (
                "generate_media_image",
                {
                    "work_item_id": work_item_id,
                    "need_index": need_index,
                    "requested_by_user_id": requested_by_user_id,
                },
                request_id,
            )
        )

    def enqueue_publish(self, work_item_id: str, *, request_id: str | None = None) -> None:
        self.calls.append(("publish_package", {"work_item_id": work_item_id}, request_id))


class FailingEditorialDispatcher(FakeEditorialControlDispatcher):
    def __getattribute__(self, name: str) -> Any:
        if name.startswith("enqueue_"):

            def fail(*args: Any, **kwargs: Any) -> None:
                raise ConnectionError("broker connect failed: redis://:secret@internal:6379/0")

            return fail
        return super().__getattribute__(name)


# Phase 5 G1: tests authenticate through the REAL login flow. The seed row
# reuses one precomputed argon2id hash (hashing is deliberately slow), but
# every request rides a session issued by the real /internal/auth/login.
TEST_OPERATOR_USERNAME = "test-operator"
TEST_OPERATOR_PASSWORD = "test-operator-password"
_TEST_PASSWORD_HASH: str | None = None


def _test_password_hash() -> str:
    global _TEST_PASSWORD_HASH
    if _TEST_PASSWORD_HASH is None:
        from argon2 import PasswordHasher

        _TEST_PASSWORD_HASH = PasswordHasher().hash(TEST_OPERATOR_PASSWORD)
    return _TEST_PASSWORD_HASH


def seed_test_operator(session: Session) -> None:
    from contentos.auth.models import User

    session.add(
        User(
            username=TEST_OPERATOR_USERNAME,
            display_name="Test Operator",
            password_hash=_test_password_hash(),
            roles=["operator", "reviewer"],
            is_active=True,
        )
    )
    session.commit()


class Harness:
    """Real sessions over shared in-memory SQLite behind the real app."""

    def __init__(self, dispatcher: FakeEditorialControlDispatcher | None = None) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(self.engine, "connect")
        def _disable_driver_transactions(dbapi_connection: Any, _record: Any) -> None:
            dbapi_connection.isolation_level = None

        @event.listens_for(self.engine, "begin")
        def _emit_begin(connection: Any) -> None:
            connection.exec_driver_sql("BEGIN")

        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

        @event.listens_for(self.session_factory, "loaded_as_persistent")
        def _restore_utc_awareness(_session: Session, instance: Any) -> None:
            for key, value in list(instance.__dict__.items()):
                if isinstance(value, datetime) and value.tzinfo is None:
                    instance.__dict__[key] = value.replace(tzinfo=UTC)

        self.dispatcher = dispatcher if dispatcher is not None else FakeEditorialControlDispatcher()
        self.app: FastAPI = create_app(settings=api_settings())
        self.app.state.db_session_factory = self.session_factory
        self.app.state.editorial_control_dispatcher = self.dispatcher
        # Isolated per-harness media byte store (never the repo default).
        self.media_store_root = Path(tempfile.mkdtemp(prefix="contentos-test-media-"))
        self.app.state.media_store = MediaStore(self.media_store_root)
        with self.session_factory() as seed_session:
            seed_test_operator(seed_session)
        self.auth_token: str | None = None

    def request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        files: Any = None,
        form_data: dict[str, Any] | None = None,
    ) -> httpx.Response:
        async def run() -> httpx.Response:
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
                if self.auth_token is None and not path.startswith("/internal/auth/"):
                    login = await client.post(
                        "/internal/auth/login",
                        json={
                            "username": TEST_OPERATOR_USERNAME,
                            "password": TEST_OPERATOR_PASSWORD,
                        },
                    )
                    assert login.status_code == 200, login.text
                    self.auth_token = login.json()["token"]
                merged = dict(headers or {})
                if self.auth_token is not None and "Authorization" not in merged:
                    merged["Authorization"] = f"Bearer {self.auth_token}"
                return await client.request(
                    method,
                    path,
                    json=json_body,
                    files=files,
                    data=form_data,
                    headers=merged,
                )

        return asyncio.run(run())

    def get(self, path: str) -> httpx.Response:
        return self.request("GET", path)

    def post(
        self,
        path: str,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        return self.request("POST", path, json_body=json_body, headers=headers)

    def session(self) -> Session:
        return self.session_factory()


class Context:
    work_item_id: uuid.UUID
    opportunity_id: uuid.UUID
    document_ids: list[uuid.UUID]
    evidence_ids: list[uuid.UUID]
    idea_ids: list[uuid.UUID]
    selected_idea_id: uuid.UUID
    pack_id: uuid.UUID
    contradiction_id: uuid.UUID
    signal_id: uuid.UUID
    analysis_id: uuid.UUID
    brief_id: uuid.UUID
    score_id: uuid.UUID


def idea_batch_payload(count: int = 3) -> dict[str, Any]:
    dims: dict[str, Any] = dict.fromkeys(
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
            for index in range(count)
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
        "internal_link_needs": [
            {"topic": "ev partisi oyunları", "purpose": "İlgili rehbere yönlendirme."}
        ],
        "media_needs": [
            {
                "role": "kapak görseli",
                "purpose": "Balon temasını görselleştirmek.",
                "constraints": None,
            }
        ],
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
            {
                "claim_key": "editoryal-cikarim",
                "claim_text": "Ev partileri hazırlıkla stressiz olabilir.",
                "claim_kind": "inference",
                "handling": None,
                "evidence_ids": [],
            },
        ],
    }


def seed_documents(session: Session) -> list[uuid.UUID]:
    """Two eligible research documents with UNIQUE duplicate decisions."""
    token = uuid.uuid4().hex[:8]
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
        item = discoveries.discover_manual(source.id, f"https://{slug}.example.test/haber-{index}")
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
        session.add(
            DuplicateDecision(
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
        )
    session.commit()
    return document_ids


def seed_scored(
    session: Session,
    context: Context,
    eligibility: ScoreEligibility = ScoreEligibility.COMMISSIONABLE,
) -> None:
    """Promotion + supporting input + evidence + a controlled-eligibility score."""
    context.document_ids = seed_documents(session)
    promo = ResearchPromotionService(session).promote_research(context.document_ids[0])
    session.commit()
    context.work_item_id = promo.work_item_id
    context.opportunity_id = promo.opportunity_id

    repo = OpportunityRepository(session)
    support_decision = session.execute(
        select(DuplicateDecision).where(
            DuplicateDecision.normalized_document_id == context.document_ids[1]
        )
    ).scalar_one()
    repo.insert_research_input(
        OpportunityResearchInput(
            opportunity_id=context.opportunity_id,
            normalized_document_id=context.document_ids[1],
            duplicate_decision_id=support_decision.id,
            role=ResearchInputRole.SUPPORTING,
            added_by=OpportunityActor.OPERATOR,
            note=None,
            added_at=NOW,
        )
    )
    session.commit()

    context.evidence_ids = []
    for document_id, statement in (
        (context.document_ids[0], "Kaynak, konsept detaylarını belirtiyor."),
        (context.document_ids[0], "Kaynak, hazırlık süresini belirtiyor."),
        (context.document_ids[1], "İkinci kaynak, bütçe aralığını doğruluyor."),
    ):
        evidence = ResearchEvidenceService(session).record_evidence(
            document_id,
            evidence_type=EvidenceType.OBSERVATION,
            statement=statement,
            extraction_method=ExtractionMethod.MACHINE,
            source_locator="structured_metadata.author",
        )
        context.evidence_ids.append(evidence.id)
    session.commit()

    evaluation = OpportunityScoringService(session).evaluate_opportunity(context.opportunity_id)
    session.commit()
    # SQLite-only deterministic gate control (real PG scores are immutable;
    # the commissioning gate reads eligibility).
    score = repo.get_effective_score(context.opportunity_id)
    assert score is not None
    score.eligibility = eligibility
    session.commit()
    context.score_id = evaluation.score.id


def seed_commissioned(session: Session, context: Context) -> None:
    seed_scored(session, context)
    OpportunityCommissioningService(session).commission_opportunity(
        context.opportunity_id, reason="operatör komisyonu"
    )
    session.commit()


def seed_selected_idea(session: Session, context: Context) -> None:
    seed_commissioned(session, context)
    execution = IdeaGenerationEngine(session).generate_candidates(
        context.opportunity_id,
        provider=FakeStructuredProvider(payload=idea_batch_payload()),
    )
    session.commit()
    context.idea_ids = [idea.id for idea in execution.ideas]
    context.selected_idea_id = context.idea_ids[0]
    IdeaService(session).select_idea(context.selected_idea_id, reason="tek aday")
    session.commit()


def seed_ready_pack(session: Session, context: Context) -> None:
    """READY pack with one unresolved MATERIAL contradiction, at SEO_RESEARCH."""
    seed_selected_idea(session, context)
    assembly = EvidencePackService(session).assemble_pack(
        context.opportunity_id,
        [
            EvidenceSelection(context.evidence_ids[0], EvidenceItemRole.KEY_FACT, "detaylar"),
            EvidenceSelection(context.evidence_ids[1], EvidenceItemRole.SUPPORTING, "sure"),
            EvidenceSelection(context.evidence_ids[2], EvidenceItemRole.SUPPORTING, "butce"),
        ],
        contradictions=[
            ContradictionDeclaration(
                claim_key="sure-tahmini",
                evidence_side_a=(context.evidence_ids[0],),
                evidence_side_b=(context.evidence_ids[1],),
                nature="Kaynaklar hazırlık süresinde uyuşmuyor.",
                severity=ContradictionSeverity.MATERIAL,
            )
        ],
        idea_id=context.selected_idea_id,
    )
    session.commit()
    context.pack_id = assembly.pack.id
    from contentos.evidence_packs.repository import EvidencePackRepository

    contradictions = EvidencePackRepository(session).list_contradictions(context.pack_id)
    context.contradiction_id = contradictions[0].id
    WorkflowService(session).transition(
        context.work_item_id,
        WorkflowState.SEO_RESEARCH,
        actor_origin=WorkflowActorOrigin.SYSTEM,
        reason=f"evidence pack {context.pack_id} READY",
        artifact_refs={"evidence_pack_id": str(context.pack_id)},
    )
    session.commit()


def seed_briefing(session: Session, context: Context) -> None:
    """Analysis with one exact known signal, then BRIEFING."""
    seed_ready_pack(session, context)
    recorded = SearchSignalService(session).record_manual_signal(
        signal_type=SearchSignalType.MANUAL_INTENT_NOTE,
        subject="evde doğum günü partisi",
        value={"note": "Operatör gözlemi: planlama rehberi aranıyor."},
        observed_at=NOW,
    )
    session.commit()
    context.signal_id = recorded.signal.id
    outcome = SearchIntentService(session).synthesize(
        context.opportunity_id,
        idea_id=context.selected_idea_id,
        provider=FakeStructuredProvider(payload=intent_payload()),
        signal_ids=[context.signal_id],
    )
    session.commit()
    assert outcome.analysis is not None
    context.analysis_id = outcome.analysis.id
    WorkflowService(session).transition(
        context.work_item_id,
        WorkflowState.BRIEFING,
        actor_origin=WorkflowActorOrigin.SYSTEM,
        reason=f"search intent analysis {context.analysis_id}",
        artifact_refs={"search_intent_analysis_id": str(context.analysis_id)},
    )
    session.commit()


def seed_draft_brief(session: Session, context: Context) -> None:
    seed_briefing(session, context)
    result = BriefCompositionEngine(session).compose(
        context.work_item_id,
        idea_id=context.selected_idea_id,
        evidence_pack_id=context.pack_id,
        search_intent_analysis_id=context.analysis_id,
        provider=FakeStructuredProvider(payload=brief_payload(context.evidence_ids)),
    )
    session.commit()
    assert result.brief is not None
    context.brief_id = result.brief.id


def seed_full(session: Session) -> Context:
    context = Context()
    seed_draft_brief(session, context)
    return context
