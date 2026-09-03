"""Brief Composition Engine tests (fake provider, no network)."""

import hashlib
import json
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

from contentos.ai.dto import GenerationRequest, ProviderOutputSchema, ProviderResult
from contentos.ai.enums import GenerationPurpose, GenerationStatus, ProviderFailureKind
from contentos.ai.fake import FakeStructuredProvider
from contentos.ai.models import AiGenerationAttempt
from contentos.briefs.composition import (
    MANDATORY_ACCEPTANCE_CRITERIA,
    BriefCompositionEngine,
)
from contentos.briefs.enums import BriefClaimKind, BriefStatus
from contentos.briefs.errors import (
    BriefCompositionMaterializationError,
    BriefInputError,
    CompositionPreconditionError,
    IncompleteBriefMaterializationError,
)
from contentos.briefs.models import ContentBrief
from contentos.briefs.repository import BriefRepository
from contentos.briefs.service import BriefService
from contentos.briefs.values import BriefClaimInput, BriefDraftInput, BriefSection
from contentos.db.base import Base
from contentos.discovery.service import DiscoveryService
from contentos.duplicates.enums import DuplicateDecisionOutcome
from contentos.duplicates.models import DuplicateDecision
from contentos.evidence_packs.enums import EvidenceItemRole
from contentos.evidence_packs.service import EvidencePackService, EvidenceSelection
from contentos.fetching.models import (
    FetchOutcome,
    FetchResult,
    RetryClassification,
    RobotsDecision,
)
from contentos.fetching.snapshot_service import FetchSnapshotService
from contentos.ideas.enums import ContentType
from contentos.ideas.service import IdeaService
from contentos.inspiration.service import InspirationIntelligenceService
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
from contentos.search_intent.service import SearchIntentService
from contentos.search_intent.values import IntentComposition
from contentos.sources.enums import SourceKind, TrustTier
from contentos.sources.service import SourceRegistryService
from contentos.strategy.service import StrategyService
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


@dataclass
class CapturingFake(FakeStructuredProvider):
    """Fake provider that also captures the request it received."""

    last_request: GenerationRequest | None = None

    def generate(
        self, request: GenerationRequest, output_schema: ProviderOutputSchema
    ) -> ProviderResult:
        self.last_request = request
        return super().generate(request, output_schema)


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
    support_trust: TrustTier = TrustTier.GENERAL,
    fetched_at: datetime = NOW,
    pack_items: int = 3,
) -> Context:
    token = uuid.uuid4().hex[:8]
    document_ids: list[uuid.UUID] = []
    for index, (slug, title, headings, trust) in enumerate(
        (
            (f"ana-{token}", "Doğum günü partisi fikirleri", ROOT_HEADINGS, TrustTier.GENERAL),
            (f"destek-{token}", "Ev partisi süsleme örnekleri", [], support_trust),
        )
    ):
        source = SourceRegistryService(session).register_source(
            slug=slug,
            name=f"Kaynak {slug}",
            kind=SourceKind.MANUAL,
            base_url=f"https://{slug}.example.test/",
            trust_tier=trust,
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
                fetched_at=fetched_at,
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
        working_title="Evde balon temalı doğum günü planı",
        angle="Bütçe dostu üç saatlik hazırlık akışına odaklanıyoruz.",
        audience="Küçük çocuklu ebeveynler",
        value_proposition="Tek listeyle eksiksiz parti hazırlığı sağlar.",
        rationale="Kaynaklar genel; biz uygulanabilir zaman çizelgesi veriyoruz.",
        content_type=ContentType.PLANNING_GUIDE,
        planning_dimensions={"theme": "balon teması"},
    )
    session.commit()
    IdeaService(session).select_idea(idea.id, reason="tek aday")
    session.commit()

    pack = (
        EvidencePackService(session)
        .assemble_pack(
            promo.opportunity_id,
            [
                EvidenceSelection(evidence_ids[0], EvidenceItemRole.KEY_FACT, "detaylar"),
                EvidenceSelection(evidence_ids[1], EvidenceItemRole.SUPPORTING, "sure"),
                EvidenceSelection(evidence_ids[2], EvidenceItemRole.SUPPORTING, "butce"),
            ][:pack_items],
            idea_id=idea.id,
        )
        .pack
    )
    session.commit()

    intent = (
        SearchIntentService(session)
        .compose_deterministic(
            promo.opportunity_id,
            idea_id=idea.id,
            composition=IntentComposition(
                primary_intent="Evde doğum günü partisi planlama rehberi arayışı",
                page_purpose="Adım adım uygulanabilir bir planlama rehberi sunmak",
                likely_format="planlama rehberi",
            ),
        )
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
    if walk_to_briefing:
        workflow = WorkflowService(session)
        for target in (
            WorkflowState.EVIDENCE_BUILDING,
            WorkflowState.SEO_RESEARCH,
            WorkflowState.BRIEFING,
        ):
            workflow.transition(
                opportunity.work_item_id,
                target,
                actor_origin=WorkflowActorOrigin.SYSTEM,
                reason=f"test ilerlemesi: {target.value}",
            )
        session.commit()
    return Context(
        work_item_id=opportunity.work_item_id,
        opportunity_id=promo.opportunity_id,
        idea_id=idea.id,
        pack_id=pack.id,
        intent_id=intent.id,
        evidence_ids=evidence_ids,
        document_ids=document_ids,
    )


def composition_payload(context: Context, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
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
                "evidence_ids": [str(context.evidence_ids[0])],
            },
            {
                "claim_key": "butce-araligi",
                "claim_text": "İkinci kaynak bir bütçe aralığı aktarır.",
                "claim_kind": "source_assertion",
                "handling": None,
                "evidence_ids": [str(context.evidence_ids[2])],
            },
            {
                "claim_key": "editoryal-cikirim",
                "claim_text": "Ev partileri hazırlıkla stressiz olabilir.",
                "claim_kind": "inference",
                "handling": None,
                "evidence_ids": [],
            },
            {
                "claim_key": "editoryal-tercih",
                "claim_text": "Tema seçimini ilk adım olarak öneriyoruz.",
                "claim_kind": "editorial_judgment",
                "handling": None,
                "evidence_ids": [],
            },
        ],
    }
    values.update(overrides)
    return values


def compose(
    session: Session, context: Context, provider: FakeStructuredProvider, **kwargs: Any
) -> Any:
    return BriefCompositionEngine(session).compose(
        context.work_item_id,
        idea_id=context.idea_id,
        evidence_pack_id=context.pack_id,
        search_intent_analysis_id=context.intent_id,
        provider=provider,
        **kwargs,
    )


class TestSuccessfulComposition:
    def test_end_to_end_with_fake_provider(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            provider = CapturingFake(payload=composition_payload(context))
            result = compose(session, context, provider)
            session.commit()

            assert result.status is GenerationStatus.SUCCEEDED
            assert result.attempt.purpose is GenerationPurpose.BRIEF_COMPOSITION
            assert result.attempt_created and result.brief_created
            brief = result.brief
            assert brief is not None
            assert brief.status is BriefStatus.DRAFT
            assert brief.engine_name == "brief-composer"
            assert brief.engine_version == "1"
            assert brief.composition_attempt_id == result.attempt.id
            assert brief.idea_id == context.idea_id
            assert brief.evidence_pack_id == context.pack_id
            assert brief.search_intent_analysis_id == context.intent_id
            # Claims + exact evidence links persisted relationally.
            repo = BriefRepository(session)
            claims = {claim.claim_key: claim for claim in repo.list_claims(brief.id)}
            assert set(claims) == {
                "konsept-detaylari",
                "butce-araligi",
                "editoryal-cikirim",
                "editoryal-tercih",
            }
            factual_links = repo.list_claim_evidence(claims["konsept-detaylari"].id)
            assert [link.research_evidence_id for link in factual_links] == [
                context.evidence_ids[0]
            ]
            # Mandatory system-derived context survived the merge.
            assert any("Eksik arama sinyalleri" in note for note in brief.uncertainty_notes)
            assert any("envanteri doğrulanmadı" in note for note in brief.uncertainty_notes)
            criterion_keys = {entry["key"] for entry in brief.acceptance_criteria}
            assert {key for key, _ in MANDATORY_ACCEPTANCE_CRITERIA} <= criterion_keys
            # Planning dimensions derived from the pinned idea.
            assert brief.practical_requirements["dimensions"] == {"theme": "balon teması"}
            assert result.structure_guard_outcome == "passed"
            # No acceptance, no workflow transition, still BRIEFING.
            events = WorkflowRepository(session).list_events(context.work_item_id)
            assert events[-1].to_state is WorkflowState.BRIEFING
            assert len(events) == 4
            assert repo.list_status_events(brief.id) == []

    def test_attempt_input_refs_shape(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            provider = CapturingFake(payload=composition_payload(context))
            result = compose(session, context, provider)
            session.commit()
            refs = result.attempt.input_refs
            assert refs["schema"] == "brief-composition/1"
            assert refs["work_item_id"] == str(context.work_item_id)
            assert refs["idea_id"] == str(context.idea_id)
            assert refs["evidence_pack_id"] == str(context.pack_id)
            assert refs["search_intent_analysis_id"] == str(context.intent_id)
            assert sorted(refs["projected_evidence_ids"]) == sorted(
                str(evidence_id) for evidence_id in context.evidence_ids
            )
            assert refs["composer_name"] == "brief-composer"
            assert refs["structure_policy_name"] == "default"
            assert refs["projection_policy_name"] == "brief-evidence-projection"
            assert refs["omitted_evidence_count"] == 0

    def test_projection_is_bounded_and_clean(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            provider = CapturingFake(payload=composition_payload(context))
            compose(session, context, provider)
            request = provider.last_request
            assert request is not None
            serialized = json.dumps(request.input_projection, ensure_ascii=False)
            # Bounded upstream context is present...
            assert "Evde balon temalı doğum günü planı" in serialized
            assert str(context.evidence_ids[0]) in serialized
            # ...raw bodies/HTML/clean text and workflow state are not.
            assert "<html" not in serialized
            assert "govdesi" not in serialized
            assert "uzun ve özgün araştırma metni" not in serialized
            assert "clean_text" not in serialized
            assert "current_state" not in serialized

    def test_relevant_strategy_reaches_brief_without_keyword_quota(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            strategy = StrategyService(session)
            cluster = strategy.create_cluster(name="Çocuk Doğum Günü", priority=95)
            strategy.create_keyword(
                phrase="doğum günü partisi",
                priority=100,
                topic_cluster_id=cluster.id,
            )
            InspirationIntelligenceService(session).evaluate(context.opportunity_id)
            session.commit()

            provider = CapturingFake(payload=composition_payload(context))
            result = compose(session, context, provider)
            session.commit()

            assert provider.last_request is not None
            projection = provider.last_request.input_projection["strategy"]
            assert projection["bounded"] is True
            assert [entry["phrase"] for entry in projection["keywords"]] == ["doğum günü partisi"]
            assert "repeat" not in json.dumps(projection).casefold()
            assert result.brief is not None
            assert any(
                need["topic"] == "doğum günü partisi" for need in result.brief.internal_link_needs
            )

    def test_manual_path_regression(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            manual = (
                BriefService(session)
                .create_draft(
                    context.work_item_id,
                    idea_id=context.idea_id,
                    evidence_pack_id=context.pack_id,
                    search_intent_analysis_id=context.intent_id,
                    draft=BriefDraftInput(
                        intent_summary="Elle hazırlanan özet.",
                        content_objective="Elle hazırlanan hedef.",
                        required_sections=(
                            BriefSection("giris", "Neden evde parti?", "Bağlam."),
                            BriefSection("plan", "Hazırlık planı", "Adımlar."),
                        ),
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
            assert manual.engine_name == "manual-brief-input"
            assert manual.composition_attempt_id is None
            assert session.execute(select(AiGenerationAttempt)).scalar_one_or_none() is None
            # The automated composer identity is reserved for the engine.
            with pytest.raises(BriefInputError, match="composition engine"):
                BriefService(session).create_draft(
                    context.work_item_id,
                    idea_id=context.idea_id,
                    evidence_pack_id=context.pack_id,
                    search_intent_analysis_id=context.intent_id,
                    draft=BriefDraftInput(
                        intent_summary="x",
                        content_objective="x",
                        required_sections=(BriefSection("a", "Başlık", "Amaç"),),
                        claims=(),
                    ),
                    engine_name="brief-composer",
                )


class TestValidationFailures:
    @pytest.mark.parametrize(
        "mutate",
        [
            # Unknown evidence id.
            lambda payload, context: payload["claims"][0].update(
                {"evidence_ids": [str(uuid.uuid4())]}
            ),
            # Factual with no evidence.
            lambda payload, context: payload["claims"][0].update({"evidence_ids": []}),
            # Source assertion with no evidence.
            lambda payload, context: payload["claims"][1].update({"evidence_ids": []}),
            # Duplicate claim keys.
            lambda payload, context: payload["claims"][1].update(
                {"claim_key": "konsept-detaylari"}
            ),
            # Mandatory criterion override.
            lambda payload, context: payload.update(
                {
                    "acceptance_criteria": [
                        {"key": "policy-claims", "requirement": "Zayıflatılmış gereklilik."}
                    ]
                }
            ),
            # Duplicate section keys across required + optional.
            lambda payload, context: payload.update(
                {
                    "optional_sections": [
                        {
                            "key": "giris",
                            "heading_guidance": "Tekrarlanan bölüm",
                            "purpose": "Çakışan anahtar.",
                        }
                    ]
                }
            ),
            # Fake UGC framing.
            lambda payload, context: payload["claims"][0].update(
                {"claim_text": "Gerçek kullanıcı yorumları partiyi öneriyor."}
            ),
        ],
    )
    def test_domain_violations_fail_validation(
        self, session_factory: sessionmaker[Session], mutate: Any
    ) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            payload = composition_payload(context)
            mutate(payload, context)
            result = compose(session, context, CapturingFake(payload=payload))
            session.commit()
            assert result.status is GenerationStatus.VALIDATION_FAILED
            assert result.attempt.error_class == "domain_validation"
            assert result.brief is None
            assert session.execute(select(ContentBrief)).scalar_one_or_none() is None

    def test_outside_projection_evidence_rejected(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            # Real evidence in the same opportunity, but NOT in the pack, so
            # never in the projection: the model cannot cite it.
            foreign = ResearchEvidenceService(session).record_evidence(
                context.document_ids[0],
                evidence_type=EvidenceType.OBSERVATION,
                statement="Pakete alınmamış kanıt.",
                extraction_method=ExtractionMethod.MACHINE,
                source_locator="structured_metadata.author",
            )
            session.commit()
            payload = composition_payload(context)
            payload["claims"][0]["evidence_ids"] = [str(foreign.id)]
            result = compose(session, context, CapturingFake(payload=payload))
            assert result.status is GenerationStatus.VALIDATION_FAILED
            assert result.brief is None

    def test_system_field_smuggling_is_schema_rejected(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            payload = composition_payload(context)
            payload["locale"] = "en-US"
            result = compose(session, context, CapturingFake(payload=payload))
            assert result.status is GenerationStatus.VALIDATION_FAILED
            assert result.attempt.error_class == "schema_validation"

    def test_retracted_evidence_is_excluded_and_uncitable(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            evidence = session.get(ResearchEvidence, context.evidence_ids[0])
            assert evidence is not None
            # SQLite-only direct mutation simulating a later review outcome.
            evidence.verification_status = VerificationStatus.RETRACTED
            session.commit()
            provider = CapturingFake(payload=composition_payload(context))
            result = compose(session, context, provider)
            session.commit()
            # The retracted unit never reached the projection...
            refs = result.attempt.input_refs
            assert str(context.evidence_ids[0]) not in refs["projected_evidence_ids"]
            assert refs["excluded_retracted_count"] == 1
            # ...so citing it is a validation failure.
            assert result.status is GenerationStatus.VALIDATION_FAILED
            assert result.brief is None

    def test_disputed_evidence_needs_handling(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            evidence = session.get(ResearchEvidence, context.evidence_ids[0])
            assert evidence is not None
            evidence.verification_status = VerificationStatus.DISPUTED
            session.commit()
            without_handling = compose(
                session, context, CapturingFake(payload=composition_payload(context))
            )
            session.commit()
            assert without_handling.status is GenerationStatus.VALIDATION_FAILED

            payload = composition_payload(context)
            payload["claims"][0]["handling"] = "temkinli ifade; tartışmalı kaynak belirt"
            with_handling = compose(
                session,
                context,
                CapturingFake(payload=payload),
                retry_number=1,
            )
            session.commit()
            assert with_handling.status is GenerationStatus.SUCCEEDED
            assert with_handling.brief is not None


class TestDeterministicMerges:
    def test_licensing_caution_survives_model_omission(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session, support_trust=TrustTier.REFERENCE_ONLY)
            result = compose(session, context, CapturingFake(payload=composition_payload(context)))
            session.commit()
            brief = result.brief
            assert brief is not None
            assert any(
                exclusion.startswith("Lisans/kullanım uyarısı:") for exclusion in brief.exclusions
            )

    def test_staleness_note_survives(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session, fetched_at=datetime(2025, 1, 1, 12, 0, tzinfo=UTC))
            result = compose(session, context, CapturingFake(payload=composition_payload(context)))
            session.commit()
            brief = result.brief
            assert brief is not None
            assert any(
                note.startswith("Kanıt tazeliği sınırlı") for note in brief.uncertainty_notes
            )

    def test_structure_copy_persists_failed_draft(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            payload = composition_payload(
                context,
                required_sections=[
                    {
                        "key": f"bolum-{index}",
                        "heading_guidance": heading["text"],
                        "purpose": "Kaynaktan aynen alınan yapı.",
                    }
                    for index, heading in enumerate(ROOT_HEADINGS)
                ],
            )
            result = compose(session, context, CapturingFake(payload=payload))
            session.commit()
            # Valid structured output => SUCCEEDED attempt; the deterministic
            # copyright guard is an artifact/gate result on the DRAFT.
            assert result.status is GenerationStatus.SUCCEEDED
            assert result.brief is not None
            assert result.structure_guard_outcome == "failed"
            assert result.brief.status is BriefStatus.DRAFT
            events = WorkflowRepository(session).list_events(context.work_item_id)
            assert events[-1].to_state is WorkflowState.BRIEFING


class TestIdempotencyAndRecovery:
    def test_exact_retry_and_short_circuit(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            provider = CapturingFake(payload=composition_payload(context))
            first = compose(session, context, provider)
            session.commit()
            second = compose(session, context, provider)
            assert provider.invocations == 1
            assert second.reused is True
            assert second.brief is not None and first.brief is not None
            assert second.brief.id == first.brief.id
            # retry_number cannot regenerate a materialized same-identity
            # brief: the pre-provider short-circuit answers first.
            fresh_provider = CapturingFake(payload=composition_payload(context))
            bumped = compose(session, context, fresh_provider, retry_number=1)
            assert fresh_provider.invocations == 0
            assert bumped.reused is True and bumped.brief.id == first.brief.id
            rows = list(session.execute(select(ContentBrief)).scalars())
            assert len(rows) == 1

    def test_failed_attempt_then_retry(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            failed = compose(
                session,
                context,
                CapturingFake(failure=ProviderFailureKind.TIMEOUT, failure_class="deadline"),
            )
            session.commit()
            assert failed.status is GenerationStatus.TIMEOUT
            assert failed.brief is None
            assert session.execute(select(ContentBrief)).scalar_one_or_none() is None

            recovered = compose(
                session,
                context,
                CapturingFake(payload=composition_payload(context)),
                retry_number=1,
            )
            session.commit()
            assert recovered.status is GenerationStatus.SUCCEEDED
            assert recovered.brief is not None

    def test_pathological_reused_attempt(
        self,
        session_factory: sessionmaker[Session],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            provider = CapturingFake(payload=composition_payload(context))
            engine = BriefCompositionEngine(session)

            def explode(*args: Any, **kwargs: Any) -> Any:
                raise RuntimeError("materialization interrupted")

            monkeypatch.setattr(BriefService, "create_composed_draft", explode)
            with pytest.raises(RuntimeError):
                compose(session, context, provider)
            session.commit()
            monkeypatch.undo()
            assert provider.invocations == 1

            with pytest.raises(IncompleteBriefMaterializationError):
                compose(session, context, provider)
            assert provider.invocations == 1
            assert len(list(session.execute(select(AiGenerationAttempt)).scalars())) == 1

            recovered = engine.compose(
                context.work_item_id,
                idea_id=context.idea_id,
                evidence_pack_id=context.pack_id,
                search_intent_analysis_id=context.intent_id,
                provider=provider,
                retry_number=1,
            )
            session.commit()
            assert recovered.status is GenerationStatus.SUCCEEDED
            assert recovered.brief is not None
            assert provider.invocations == 2

    def test_materialization_failure_keeps_attempt_status(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            context = seed_context(session)
            # Seed an active manual draft so the composed draft would need a
            # supersede reason -> deterministic persistence-time rejection.
            BriefService(session).create_draft(
                context.work_item_id,
                idea_id=context.idea_id,
                evidence_pack_id=context.pack_id,
                search_intent_analysis_id=context.intent_id,
                draft=BriefDraftInput(
                    intent_summary="Elle hazırlanan özet.",
                    content_objective="Elle hazırlanan hedef.",
                    required_sections=(BriefSection("giris", "Neden evde parti?", "Bağlam."),),
                    claims=(
                        BriefClaimInput(
                            claim_key="editoryal-cikirim",
                            claim_text="Hazırlıkla stres azalır.",
                            claim_kind=BriefClaimKind.INFERENCE,
                        ),
                    ),
                ),
            )
            session.commit()
            provider = CapturingFake(payload=composition_payload(context))
            with pytest.raises(BriefCompositionMaterializationError):
                compose(session, context, provider)
            session.commit()
            # The attempt keeps its REAL status: it is never retroactively
            # relabeled a provider/validation failure.
            attempt = session.execute(select(AiGenerationAttempt)).scalar_one()
            assert attempt.status is GenerationStatus.SUCCEEDED
            # The committed attempt's raw output is gone by design, so the
            # exact identity cannot re-materialize; recovery is an explicit
            # new provider invocation with retry_number + 1.
            with pytest.raises(IncompleteBriefMaterializationError):
                compose(session, context, provider, supersede_reason="otomatik kompozisyon")
            recovered = compose(
                session,
                context,
                provider,
                retry_number=1,
                supersede_reason="otomatik kompozisyon",
            )
            session.commit()
            assert provider.invocations == 2
            assert recovered.brief is not None
            assert recovered.brief.engine_name == "brief-composer"


class TestPreconditions:
    def test_preconditions_fail_before_provider(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        # Non-READY pack.
        with open_session(session_factory) as session:
            context = seed_context(session, pack_items=2)
            provider = CapturingFake(payload=composition_payload(context))
            with pytest.raises(CompositionPreconditionError, match="READY"):
                compose(session, context, provider)
            assert provider.invocations == 0
        # Not commissioned.
        with open_session(session_factory) as session:
            context = seed_context(session, commissioned=False)
            provider = CapturingFake(payload=composition_payload(context))
            with pytest.raises(CompositionPreconditionError, match="COMMISSIONED"):
                compose(session, context, provider)
            assert provider.invocations == 0
        # Wrong workflow state.
        with open_session(session_factory) as session:
            context = seed_context(session, walk_to_briefing=False)
            provider = CapturingFake(payload=composition_payload(context))
            with pytest.raises(CompositionPreconditionError, match="BRIEFING"):
                compose(session, context, provider)
            assert provider.invocations == 0
