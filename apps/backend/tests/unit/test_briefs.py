"""ContentBrief persistence, claim map, and acceptance-gate tests."""

import hashlib
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from contentos.ai.enums import GenerationPurpose, GenerationStatus
from contentos.ai.models import AiGenerationAttempt
from contentos.briefs.enums import BriefClaimKind, BriefStatus
from contentos.briefs.errors import (
    BriefAcceptanceGateError,
    BriefClaimEvidenceError,
    BriefConflictError,
    BriefInputError,
    BriefStatusConflictError,
    BriefStructureGuardError,
    BriefUpstreamMismatchError,
)
from contentos.briefs.models import (
    BriefClaim,
    BriefClaimEvidence,
    BriefStatusEvent,
    ContentBrief,
)
from contentos.briefs.repository import BriefRepository
from contentos.briefs.service import BriefService
from contentos.briefs.values import (
    BriefClaimInput,
    BriefDraftInput,
    BriefSection,
)
from contentos.db.base import Base
from contentos.discovery.service import DiscoveryService
from contentos.duplicates.enums import DuplicateDecisionOutcome
from contentos.duplicates.models import DuplicateDecision
from contentos.evidence_packs.enums import ContradictionSeverity, EvidenceItemRole
from contentos.evidence_packs.models import EvidencePack
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
from contentos.ideas.enums import ContentType
from contentos.ideas.models import Idea
from contentos.ideas.service import IdeaService
from contentos.normalization.service import NormalizationService
from contentos.opportunities.enums import (
    OpportunityActor,
    OpportunityDisposition,
    ResearchInputRole,
)
from contentos.opportunities.models import OpportunityResearchInput
from contentos.opportunities.repository import OpportunityRepository
from contentos.research.enums import (
    EvidenceType,
    ExtractionMethod,
    VerificationStatus,
)
from contentos.research.models import ResearchEvidence
from contentos.research.service import ResearchEvidenceService
from contentos.search_intent.models import SearchIntentAnalysis
from contentos.search_intent.service import SearchIntentService
from contentos.search_intent.values import IntentComposition
from contentos.sources.enums import SourceKind, TrustTier
from contentos.sources.service import SourceRegistryService
from contentos.workflow.enums import WorkflowActorOrigin, WorkflowState
from contentos.workflow.repository import WorkflowRepository
from contentos.workflow.service import WorkflowService

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

ROOT_HEADINGS = [
    {"level": 2, "text": "Parti temasını seçmek"},
    {"level": 2, "text": "Davetiye ve misafir listesi"},
    {"level": 2, "text": "Süsleme fikirleri"},
    {"level": 2, "text": "Pasta ve ikramlar"},
]

COMPOSITION = IntentComposition(
    primary_intent="Evde doğum günü partisi planlama rehberi arayışı",
    page_purpose="Adım adım uygulanabilir bir planlama rehberi sunmak",
    likely_format="planlama rehberi",
)


@pytest.fixture()
def session_factory() -> sessionmaker[Session]:
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

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    @event.listens_for(factory, "loaded_as_persistent")
    def _restore_utc_awareness(_session: Session, instance: Any) -> None:
        for key, value in list(instance.__dict__.items()):
            if isinstance(value, datetime) and value.tzinfo is None:
                instance.__dict__[key] = value.replace(tzinfo=UTC)

    return factory


@contextmanager
def open_session(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
    finally:
        session.close()


@dataclass
class Context:
    work_item_id: uuid.UUID
    opportunity_id: uuid.UUID
    idea_id: uuid.UUID
    pack_id: uuid.UUID
    intent_id: uuid.UUID
    evidence_ids: list[uuid.UUID]
    document_ids: list[uuid.UUID]


def seed_context(
    session: Session,
    *,
    commissioned: bool = True,
    walk_to_briefing: bool = True,
    idea_title: str = "Evde balon temalı doğum günü planı",
    root_headings: list[dict[str, Any]] | None = None,
    pack_pins_idea: bool = True,
    blocking_contradiction: bool = False,
    pack_items: int = 3,
) -> Context:
    token = uuid.uuid4().hex[:8]
    document_ids: list[uuid.UUID] = []
    for index, (slug, title, headings) in enumerate(
        (
            (
                f"ana-{token}",
                "Doğum günü partisi fikirleri ve önerileri",
                root_headings if root_headings is not None else ROOT_HEADINGS,
            ),
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
    decisions: list[uuid.UUID] = []
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
        session.flush()
        decisions.append(decision.id)
    session.commit()
    from contentos.opportunities.service import ResearchPromotionService

    promo = ResearchPromotionService(session).promote_research(document_ids[0])
    session.commit()
    OpportunityRepository(session).insert_research_input(
        OpportunityResearchInput(
            opportunity_id=promo.opportunity_id,
            normalized_document_id=document_ids[1],
            duplicate_decision_id=decisions[1],
            role=ResearchInputRole.SUPPORTING,
            added_by=OpportunityActor.OPERATOR,
            note=None,
            added_at=NOW,
        )
    )
    session.commit()

    evidence_ids: list[uuid.UUID] = []
    for document_id, statement in (
        (document_ids[0], "Kaynak, konsept detaylarını belirtiyor."),
        (document_ids[0], "Kaynak, hazırlık süresini belirtiyor."),
        (document_ids[1], "İkinci kaynak, bütçe aralığını doğruluyor."),
    ):
        evidence = ResearchEvidenceService(session).record_evidence(
            document_id,
            evidence_type=EvidenceType.OBSERVATION,
            statement=statement,
            extraction_method=ExtractionMethod.MACHINE,
            source_locator="structured_metadata.author",
        )
        evidence_ids.append(evidence.id)
    session.commit()

    idea = IdeaService(session).create_operator_idea(
        promo.opportunity_id,
        working_title=idea_title,
        angle="Bütçe dostu üç saatlik hazırlık akışına odaklanıyoruz.",
        audience="Küçük çocuklu ebeveynler",
        value_proposition="Tek listeyle eksiksiz parti hazırlığı sağlar.",
        rationale="Kaynaklar genel; biz uygulanabilir zaman çizelgesi veriyoruz.",
        content_type=ContentType.PLANNING_GUIDE,
    )
    session.commit()
    IdeaService(session).select_idea(idea.id, reason="tek aday")
    session.commit()

    selections = [
        EvidenceSelection(evidence_ids[0], EvidenceItemRole.KEY_FACT, "detaylar"),
        EvidenceSelection(evidence_ids[1], EvidenceItemRole.SUPPORTING, "sure"),
        EvidenceSelection(evidence_ids[2], EvidenceItemRole.SUPPORTING, "butce"),
    ][:pack_items]
    contradictions = (
        [
            ContradictionDeclaration(
                claim_key="sure",
                evidence_side_a=(evidence_ids[1],),
                evidence_side_b=(evidence_ids[2],),
                nature="Kaynaklar süre konusunda çelişiyor.",
                severity=ContradictionSeverity.BLOCKING,
            )
        ]
        if blocking_contradiction
        else None
    )
    pack = (
        EvidencePackService(session)
        .assemble_pack(
            promo.opportunity_id,
            selections,
            contradictions=contradictions,
            idea_id=idea.id if pack_pins_idea else None,
        )
        .pack
    )
    session.commit()

    intent = (
        SearchIntentService(session)
        .compose_deterministic(promo.opportunity_id, idea_id=idea.id, composition=COMPOSITION)
        .analysis
    )
    session.commit()

    opportunity = OpportunityRepository(session).get_by_id(promo.opportunity_id)
    assert opportunity is not None
    if commissioned:
        opportunity.disposition = OpportunityDisposition.COMMISSIONED
        opportunity.disposition_reason = "test komisyonu"
        opportunity.disposition_at = NOW
        opportunity.disposition_by = OpportunityActor.OPERATOR
        session.commit()
    work_item_id = opportunity.work_item_id
    if walk_to_briefing:
        workflow = WorkflowService(session)
        for target in (
            WorkflowState.EVIDENCE_BUILDING,
            WorkflowState.SEO_RESEARCH,
            WorkflowState.BRIEFING,
        ):
            workflow.transition(
                work_item_id,
                target,
                actor_origin=WorkflowActorOrigin.SYSTEM,
                reason=f"test ilerlemesi: {target.value}",
            )
        session.commit()
    return Context(
        work_item_id=work_item_id,
        opportunity_id=promo.opportunity_id,
        idea_id=idea.id,
        pack_id=pack.id,
        intent_id=intent.id,
        evidence_ids=evidence_ids,
        document_ids=document_ids,
    )


def draft_input(context: Context, **overrides: Any) -> BriefDraftInput:
    values: dict[str, Any] = {
        "intent_summary": "Okur evde doğum günü partisi planlamak istiyor.",
        "content_objective": "Okura eksiksiz, bütçe dostu bir plan kazandırmak.",
        "required_sections": (
            BriefSection("giris", "Neden evde parti?", "Bağlam ve değer önerisi."),
            BriefSection("plan", "Üç saatlik hazırlık planı", "Adım adım zaman çizelgesi."),
            BriefSection("butce", "Bütçe dostu öneriler", "Maliyet kalemleri ve alternatifler."),
        ),
        "claims": (
            BriefClaimInput(
                claim_key="konsept-detaylari",
                claim_text="Kaynaklar konsept detaylarını belirtir.",
                claim_kind=BriefClaimKind.FACTUAL,
                evidence_ids=(context.evidence_ids[0],),
            ),
            BriefClaimInput(
                claim_key="butce-araligi",
                claim_text="İkinci kaynak bir bütçe aralığı aktarır.",
                claim_kind=BriefClaimKind.SOURCE_ASSERTION,
                evidence_ids=(context.evidence_ids[2],),
            ),
            BriefClaimInput(
                claim_key="editoryal-cikirim",
                claim_text="Ev partileri hazırlıkla stressiz olabilir.",
                claim_kind=BriefClaimKind.INFERENCE,
            ),
            BriefClaimInput(
                claim_key="editoryal-tercih",
                claim_text="Tema seçimini ilk adım olarak öneriyoruz.",
                claim_kind=BriefClaimKind.EDITORIAL_JUDGMENT,
            ),
        ),
        "uncertainty_notes": ("Hazırlık süreleri eve göre değişebilir.",),
        "extra_exclusions": ("fiyat garantisi verme",),
    }
    values.update(overrides)
    return BriefDraftInput(**values)


class TestDraftCreation:
    def test_basic_draft(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            result = BriefService(session).create_draft(
                context.work_item_id,
                idea_id=context.idea_id,
                evidence_pack_id=context.pack_id,
                search_intent_analysis_id=context.intent_id,
                draft=draft_input(context),
            )
            session.commit()

            assert result.created is True and result.superseded_brief_id is None
            brief = result.brief
            assert brief.version == 1
            assert brief.status is BriefStatus.DRAFT
            assert brief.composition_attempt_id is None
            assert brief.idea_id == context.idea_id
            assert brief.evidence_pack_id == context.pack_id
            assert brief.search_intent_analysis_id == context.intent_id
            idea = session.get(Idea, context.idea_id)
            assert idea is not None
            assert brief.target_audience == idea.audience
            assert brief.original_angle == idea.angle
            assert brief.title_guidance["idea_working_title"] == idea.working_title
            # Every idea prohibition survives; the brief only adds more.
            for exclusion in idea.exclusions:
                assert exclusion in brief.exclusions
            assert "fiyat garantisi verme" in brief.exclusions
            assert brief.structure_guard_result["outcome"] == "passed"
            assert brief.locale == "tr-TR" and brief.market == "TR"
            # Draft creation performs NO workflow transition.
            events = WorkflowRepository(session).list_events(context.work_item_id)
            assert events[-1].to_state is WorkflowState.BRIEFING
            assert len(events) == 4

    def test_claim_map_is_relational(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            brief = (
                BriefService(session)
                .create_draft(
                    context.work_item_id,
                    idea_id=context.idea_id,
                    evidence_pack_id=context.pack_id,
                    search_intent_analysis_id=context.intent_id,
                    draft=draft_input(context),
                )
                .brief
            )
            session.commit()
            repo = BriefRepository(session)
            claims = repo.list_claims(brief.id)
            assert [claim.claim_kind.value for claim in claims] == [
                "source_assertion",
                "inference",
                "editorial_judgment",
                "factual",
            ]
            by_key = {claim.claim_key: claim for claim in claims}
            factual_links = repo.list_claim_evidence(by_key["konsept-detaylari"].id)
            assert [link.research_evidence_id for link in factual_links] == [
                context.evidence_ids[0]
            ]
            assert repo.list_claim_evidence(by_key["editoryal-cikirim"].id) == []
            # No evidence text is copied anywhere.
            claim_columns = {column.name for column in BriefClaim.__table__.columns}
            link_columns = {column.name for column in BriefClaimEvidence.__table__.columns}
            assert "evidence_text" not in claim_columns | link_columns
            assert "statement" not in claim_columns | link_columns

    def test_factual_without_evidence_rejected_at_creation(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            bad = draft_input(
                context,
                claims=(
                    BriefClaimInput(
                        claim_key="dayanaksiz",
                        claim_text="Kanıtsız olgusal iddia.",
                        claim_kind=BriefClaimKind.FACTUAL,
                    ),
                ),
            )
            with pytest.raises(BriefClaimEvidenceError, match="requires at least one"):
                BriefService(session).create_draft(
                    context.work_item_id,
                    idea_id=context.idea_id,
                    evidence_pack_id=context.pack_id,
                    search_intent_analysis_id=context.intent_id,
                    draft=bad,
                )
            session.rollback()
            assert session.execute(select(ContentBrief)).scalar_one_or_none() is None

    def test_evidence_outside_pack_rejected(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            foreign = ResearchEvidenceService(session).record_evidence(
                context.document_ids[0],
                evidence_type=EvidenceType.OBSERVATION,
                statement="Pakete dahil edilmemiş kanıt.",
                extraction_method=ExtractionMethod.MACHINE,
                source_locator="structured_metadata.author",
            )
            session.commit()
            bad = draft_input(
                context,
                claims=(
                    BriefClaimInput(
                        claim_key="paket-disi",
                        claim_text="Paket dışı kanıta dayanan iddia.",
                        claim_kind=BriefClaimKind.FACTUAL,
                        evidence_ids=(foreign.id,),
                    ),
                ),
            )
            with pytest.raises(BriefClaimEvidenceError, match="outside the pinned"):
                BriefService(session).create_draft(
                    context.work_item_id,
                    idea_id=context.idea_id,
                    evidence_pack_id=context.pack_id,
                    search_intent_analysis_id=context.intent_id,
                    draft=bad,
                )
            session.rollback()
            assert session.execute(select(ContentBrief)).scalar_one_or_none() is None

    def test_wrong_upstream_combinations_rejected(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            other = seed_context(session)
            service = BriefService(session)
            cases = [
                {"idea_id": other.idea_id},
                {"evidence_pack_id": other.pack_id},
                {"search_intent_analysis_id": other.intent_id},
            ]
            for override in cases:
                kwargs: dict[str, Any] = {
                    "idea_id": context.idea_id,
                    "evidence_pack_id": context.pack_id,
                    "search_intent_analysis_id": context.intent_id,
                }
                kwargs.update(override)
                with pytest.raises(BriefUpstreamMismatchError):
                    service.create_draft(context.work_item_id, draft=draft_input(context), **kwargs)
            assert session.execute(select(ContentBrief)).scalar_one_or_none() is None

    def test_selection_change_blocks_new_draft(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            service = BriefService(session)
            first = service.create_draft(
                context.work_item_id,
                idea_id=context.idea_id,
                evidence_pack_id=context.pack_id,
                search_intent_analysis_id=context.intent_id,
                draft=draft_input(context),
            ).brief
            session.commit()
            other_idea = IdeaService(session).create_operator_idea(
                context.opportunity_id,
                working_title="Bahçede yaz temalı doğum günü rehberi",
                angle="Açık hava akışına odaklanıyoruz.",
                audience="Küçük çocuklu ebeveynler",
                value_proposition="Bahçe partisi için eksiksiz hazırlık.",
                rationale="Alternatif mekan açısı sunuyoruz.",
                content_type=ContentType.PLANNING_GUIDE,
            )
            session.commit()
            IdeaService(session).select_idea(other_idea.id, reason="yeni açı")
            session.commit()
            with pytest.raises(BriefUpstreamMismatchError, match="effective selection"):
                service.create_draft(
                    context.work_item_id,
                    idea_id=context.idea_id,
                    evidence_pack_id=context.pack_id,
                    search_intent_analysis_id=context.intent_id,
                    draft=draft_input(context, intent_summary="Farklı özet."),
                    engine_version="2",
                )
            # The historical brief stays pinned to idea A, untouched.
            reread = BriefRepository(session).get_brief(first.id)
            assert reread is not None and reread.idea_id == context.idea_id

    def test_requires_briefing_state(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session, walk_to_briefing=False)
            with pytest.raises(BriefInputError, match="BRIEFING"):
                BriefService(session).create_draft(
                    context.work_item_id,
                    idea_id=context.idea_id,
                    evidence_pack_id=context.pack_id,
                    search_intent_analysis_id=context.intent_id,
                    draft=draft_input(context),
                )

    def test_identity_idempotency_and_conflict(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            service = BriefService(session)
            first = service.create_draft(
                context.work_item_id,
                idea_id=context.idea_id,
                evidence_pack_id=context.pack_id,
                search_intent_analysis_id=context.intent_id,
                draft=draft_input(context),
            )
            session.commit()
            retry = service.create_draft(
                context.work_item_id,
                idea_id=context.idea_id,
                evidence_pack_id=context.pack_id,
                search_intent_analysis_id=context.intent_id,
                draft=draft_input(context),
            )
            assert retry.created is False and retry.brief.id == first.brief.id
            assert len(list(session.execute(select(ContentBrief)).scalars())) == 1
            # Same identity + different wording is a CONFLICT, never a
            # silent overwrite or a noisy second version.
            with pytest.raises(BriefConflictError, match="different content"):
                service.create_draft(
                    context.work_item_id,
                    idea_id=context.idea_id,
                    evidence_pack_id=context.pack_id,
                    search_intent_analysis_id=context.intent_id,
                    draft=draft_input(context, intent_summary="Başka bir özet metni."),
                )

    def test_new_version_supersedes_active_draft(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            service = BriefService(session)
            first = service.create_draft(
                context.work_item_id,
                idea_id=context.idea_id,
                evidence_pack_id=context.pack_id,
                search_intent_analysis_id=context.intent_id,
                draft=draft_input(context),
            ).brief
            session.commit()
            first_hash = first.content_hash

            with pytest.raises(BriefInputError, match="reason"):
                service.create_draft(
                    context.work_item_id,
                    idea_id=context.idea_id,
                    evidence_pack_id=context.pack_id,
                    search_intent_analysis_id=context.intent_id,
                    draft=draft_input(context),
                    engine_version="2",
                )
            second = service.create_draft(
                context.work_item_id,
                idea_id=context.idea_id,
                evidence_pack_id=context.pack_id,
                search_intent_analysis_id=context.intent_id,
                draft=draft_input(context),
                engine_version="2",
                supersede_reason="kompozisyon sürümü yenilendi",
            )
            session.commit()
            assert second.created is True
            assert second.superseded_brief_id == first.id
            assert second.brief.version == 2
            repo = BriefRepository(session)
            old = repo.get_brief(first.id)
            assert old is not None
            assert old.status is BriefStatus.SUPERSEDED
            assert old.content_hash == first_hash  # content untouched
            active = repo.get_active_brief(context.work_item_id)
            assert active is not None and active.id == second.brief.id
            [event_row] = repo.list_status_events(first.id)
            assert event_row.from_status is BriefStatus.DRAFT
            assert event_row.to_status is BriefStatus.SUPERSEDED
            assert event_row.replacement_brief_id == second.brief.id
            assert event_row.reason == "kompozisyon sürümü yenilendi"

    def test_caller_owns_commit(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            BriefService(session).create_draft(
                context.work_item_id,
                idea_id=context.idea_id,
                evidence_pack_id=context.pack_id,
                search_intent_analysis_id=context.intent_id,
                draft=draft_input(context),
            )
            session.rollback()
        with open_session(session_factory) as session:
            assert session.execute(select(ContentBrief)).scalar_one_or_none() is None
            assert session.execute(select(BriefClaim)).scalar_one_or_none() is None
            assert session.execute(select(BriefStatusEvent)).scalar_one_or_none() is None


def create_default_draft(session: Session, context: Context) -> ContentBrief:
    brief = (
        BriefService(session)
        .create_draft(
            context.work_item_id,
            idea_id=context.idea_id,
            evidence_pack_id=context.pack_id,
            search_intent_analysis_id=context.intent_id,
            draft=draft_input(context),
        )
        .brief
    )
    session.commit()
    return brief


class TestAcceptance:
    def test_happy_path(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            brief = create_default_draft(session, context)
            intent = session.get(SearchIntentAnalysis, context.intent_id)
            assert intent is not None and intent.missing_signals  # UNKNOWN stays UNKNOWN
            result = BriefService(session).accept_for_drafting(
                brief.id, reason="taslak sözleşme eksiksiz", request_id="req-brief-accept-1"
            )
            session.commit()

            assert result.accepted is True
            assert result.brief.status is BriefStatus.ACCEPTED_FOR_DRAFTING
            repo = BriefRepository(session)
            [status_event] = repo.list_status_events(brief.id)
            assert status_event.to_status is BriefStatus.ACCEPTED_FOR_DRAFTING
            assert status_event.reason == "taslak sözleşme eksiksiz"
            assert status_event.request_id == "req-brief-accept-1"
            events = WorkflowRepository(session).list_events(context.work_item_id)
            last = events[-1]
            assert last.from_state is WorkflowState.BRIEFING
            assert last.to_state is WorkflowState.DRAFTING
            assert last.actor_origin is WorkflowActorOrigin.OPERATOR
            assert last.artifact_refs == {
                "content_brief_id": str(brief.id),
                "idea_id": str(context.idea_id),
                "evidence_pack_id": str(context.pack_id),
                "search_intent_analysis_id": str(context.intent_id),
            }
            # Acceptance is NOT publication approval: nothing beyond
            # DRAFTING, no approval vocabulary anywhere.
            assert {status.value for status in BriefStatus} == {
                "draft",
                "accepted_for_drafting",
                "superseded",
            }
            opportunity = OpportunityRepository(session).get_by_id(context.opportunity_id)
            assert opportunity is not None
            assert opportunity.disposition is OpportunityDisposition.COMMISSIONED

    def test_acceptance_is_idempotent(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            brief = create_default_draft(session, context)
            service = BriefService(session)
            service.accept_for_drafting(brief.id, reason="ilk kabul")
            session.commit()
            events_before = len(WorkflowRepository(session).list_events(context.work_item_id))
            retry = service.accept_for_drafting(brief.id, reason="tekrar kabul")
            assert retry.accepted is False
            assert (
                len(WorkflowRepository(session).list_events(context.work_item_id)) == events_before
            )
            assert len(BriefRepository(session).list_status_events(brief.id)) == 1

    def test_gate_failures(self, session_factory: sessionmaker[Session]) -> None:
        # Not commissioned.
        with open_session(session_factory) as session:
            context = seed_context(session, commissioned=False)
            brief = create_default_draft(session, context)
            with pytest.raises(BriefAcceptanceGateError, match="COMMISSIONED"):
                BriefService(session).accept_for_drafting(brief.id, reason="kabul")
            session.rollback()
            assert (
                BriefRepository(session).get_brief(brief.id).status  # type: ignore[union-attr]
                is BriefStatus.DRAFT
            )

    def test_pack_not_ready_fails(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session, pack_items=2)  # INSUFFICIENT pack
            brief = (
                BriefService(session)
                .create_draft(
                    context.work_item_id,
                    idea_id=context.idea_id,
                    evidence_pack_id=context.pack_id,
                    search_intent_analysis_id=context.intent_id,
                    draft=draft_input(
                        context,
                        claims=(
                            BriefClaimInput(
                                claim_key="konsept-detaylari",
                                claim_text="Kaynaklar konsept detaylarını belirtir.",
                                claim_kind=BriefClaimKind.FACTUAL,
                                evidence_ids=(context.evidence_ids[0],),
                            ),
                        ),
                    ),
                )
                .brief
            )
            session.commit()
            with pytest.raises(BriefAcceptanceGateError, match="READY"):
                BriefService(session).accept_for_drafting(brief.id, reason="kabul")

    def test_blocking_contradiction_fails(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session, blocking_contradiction=True)
            brief = (
                BriefService(session)
                .create_draft(
                    context.work_item_id,
                    idea_id=context.idea_id,
                    evidence_pack_id=context.pack_id,
                    search_intent_analysis_id=context.intent_id,
                    draft=draft_input(
                        context,
                        claims=(
                            BriefClaimInput(
                                claim_key="sure-iddiasi",
                                claim_text="Hazırlık süresi hakkında olgusal iddia.",
                                claim_kind=BriefClaimKind.FACTUAL,
                                handling="temkinli ifade",
                                evidence_ids=(context.evidence_ids[1],),
                            ),
                        ),
                    ),
                )
                .brief
            )
            session.commit()
            # Cautious wording cannot bypass an UNRESOLVED BLOCKING
            # contradiction.
            with pytest.raises(BriefAcceptanceGateError, match="BLOCKING"):
                BriefService(session).accept_for_drafting(brief.id, reason="kabul")

    def test_retracted_and_disputed_evidence_gates(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            brief = create_default_draft(session, context)
            evidence = session.get(ResearchEvidence, context.evidence_ids[0])
            assert evidence is not None
            # SQLite-only direct mutation to simulate later review outcomes
            # (the PG trigger forbids this in production).
            evidence.verification_status = VerificationStatus.RETRACTED
            session.commit()
            with pytest.raises(BriefAcceptanceGateError, match="non-retracted"):
                BriefService(session).accept_for_drafting(brief.id, reason="kabul")
            session.rollback()
            evidence.verification_status = VerificationStatus.DISPUTED
            session.commit()
            # DISPUTED-only support without handling keeps the dispute
            # hidden -> gate failure. The claim in draft_input has no
            # handling.
            with pytest.raises(BriefAcceptanceGateError, match="DISPUTED"):
                BriefService(session).accept_for_drafting(brief.id, reason="kabul")

    def test_idea_originality_gate(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            # A near-copy idea title -> originality FAILED.
            context = seed_context(
                session,
                idea_title="Doğum günü partisi fikirleri ve önerileri",
                pack_pins_idea=False,
            )
            brief = create_default_draft(session, context)
            with pytest.raises(BriefAcceptanceGateError, match="originality"):
                BriefService(session).accept_for_drafting(brief.id, reason="kabul")

    def test_structure_copy_fails_guard_and_acceptance(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            mirrored = draft_input(
                context,
                required_sections=tuple(
                    BriefSection(f"bolum-{i}", heading["text"], "Kaynaktan aynen.")
                    for i, heading in enumerate(ROOT_HEADINGS)
                ),
            )
            brief = (
                BriefService(session)
                .create_draft(
                    context.work_item_id,
                    idea_id=context.idea_id,
                    evidence_pack_id=context.pack_id,
                    search_intent_analysis_id=context.intent_id,
                    draft=mirrored,
                )
                .brief
            )
            session.commit()
            guard = brief.structure_guard_result
            assert guard["outcome"] == "failed"
            assert guard["most_similar_document_id"] == str(context.document_ids[0])
            assert guard["max_similarity"] >= guard["threshold"]
            with pytest.raises(BriefStructureGuardError):
                BriefService(session).accept_for_drafting(brief.id, reason="kabul")
            session.rollback()
            # The failed draft remains inspectable, never deleted.
            reread = BriefRepository(session).get_brief(brief.id)
            assert reread is not None and reread.status is BriefStatus.DRAFT

    def test_structure_not_checkable_fails_closed(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session, root_headings=[])
            brief = create_default_draft(session, context)
            assert brief.structure_guard_result["outcome"] == "not_checkable"
            assert brief.structure_guard_result["skipped_documents"]
            with pytest.raises(BriefStructureGuardError):
                BriefService(session).accept_for_drafting(brief.id, reason="kabul")

    def test_out_of_band_mutation_fails_integrity(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            brief = create_default_draft(session, context)
            # Simulate an out-of-band child insert (append-only child tables
            # alone cannot guarantee whole-version immutability).
            session.add(
                BriefClaim(
                    brief_id=brief.id,
                    claim_key="kacak-iddia",
                    claim_text="Sonradan eklenen iddia.",
                    claim_kind=BriefClaimKind.INFERENCE,
                )
            )
            session.commit()
            with pytest.raises(BriefConflictError, match="mutated out of band"):
                BriefService(session).accept_for_drafting(brief.id, reason="kabul")

    def test_superseded_brief_cannot_be_accepted(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            service = BriefService(session)
            first = service.create_draft(
                context.work_item_id,
                idea_id=context.idea_id,
                evidence_pack_id=context.pack_id,
                search_intent_analysis_id=context.intent_id,
                draft=draft_input(context),
            ).brief
            session.commit()
            service.create_draft(
                context.work_item_id,
                idea_id=context.idea_id,
                evidence_pack_id=context.pack_id,
                search_intent_analysis_id=context.intent_id,
                draft=draft_input(context),
                engine_version="2",
                supersede_reason="yenilendi",
            )
            session.commit()
            with pytest.raises(BriefStatusConflictError, match="SUPERSEDED"):
                service.accept_for_drafting(first.id, reason="kabul")

    def test_duplicate_gate_revalidates_current_effective_decision(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            brief = create_default_draft(session, context)
            opportunity = OpportunityRepository(session).get_by_id(context.opportunity_id)
            assert opportunity is not None
            newer = DuplicateDecision(
                normalized_document_id=opportunity.promotion_root_document_id,
                engine_name="duplicate-engine",
                engine_version="2",
                decision=DuplicateDecisionOutcome.REJECT,
                signals={},
                thresholds={},
                matches=[],
                rationale_codes=[],
                evaluated_at=datetime(2026, 9, 2, 12, 0, tzinfo=UTC),
            )
            session.add(newer)
            session.commit()
            with pytest.raises(BriefAcceptanceGateError, match="REJECT"):
                BriefService(session).accept_for_drafting(brief.id, reason="kabul")

    def test_composition_attempt_gate(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            brief = create_default_draft(session, context)
            attempt = AiGenerationAttempt(
                purpose=GenerationPurpose.IDEA_CANDIDATES,
                provider="fake",
                model_name="m",
                model_version=None,
                schema_name="s",
                schema_version="1",
                template_name="t",
                template_version="1",
                input_refs={},
                input_hash="0" * 64,
                attempt_identity_hash="2" * 64,
                status=GenerationStatus.SUCCEEDED,
                error_class=None,
                retry_number=0,
                usage={},
            )
            session.add(attempt)
            session.commit()
            # SQLite-only direct simulation of a Task-12-composed brief
            # carrying a wrong-purpose attempt.
            brief.composition_attempt_id = attempt.id
            session.commit()
            with pytest.raises(BriefAcceptanceGateError, match="BRIEF_COMPOSITION"):
                BriefService(session).accept_for_drafting(brief.id, reason="kabul")

    def test_no_side_effects_and_no_ai(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            brief = create_default_draft(session, context)
            BriefService(session).accept_for_drafting(brief.id, reason="kabul")
            session.commit()
            # No AI attempt was ever created by Task 11 paths.
            assert session.execute(select(AiGenerationAttempt)).scalar_one_or_none() is None
            pack = session.get(EvidencePack, context.pack_id)
            assert pack is not None and pack.organization_attempt_id is None

    def test_repository_exposes_no_update_or_delete_surface(self) -> None:
        exposed = {name for name in dir(BriefRepository) if not name.startswith("_")}
        assert not any("update" in name or "delete" in name for name in exposed)
        # No article body anywhere in the contract.
        brief_columns = {column.name for column in ContentBrief.__table__.columns}
        for forbidden in (
            "article_body",
            "markdown_body",
            "html_body",
            "draft_text",
            "final_title",
        ):
            assert forbidden not in brief_columns
