"""Model-assisted evidence, cross-source research inputs and the autopilot
evidence step. The provider is the deterministic fake: no test invents a
fact — every persisted row is proven against the normalized text."""

import dataclasses
import hashlib
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from contentos.ai.enums import GenerationPurpose, GenerationStatus, ProviderFailureKind
from contentos.ai.fake import FakeStructuredProvider
from contentos.ai.models import AiGenerationAttempt
from contentos.autopilot.enums import AutopilotMode
from contentos.autopilot.planner import (
    ACTION_BUILD_PACK,
    ACTION_EXTRACT_EVIDENCE,
    Snapshot,
    plan,
)
from contentos.db.base import Base
from contentos.discovery.service import DiscoveryService
from contentos.duplicates.enums import DuplicateDecisionOutcome
from contentos.duplicates.models import DuplicateDecision
from contentos.fetching.models import FetchOutcome, FetchResult, RetryClassification, RobotsDecision
from contentos.fetching.snapshot_service import FetchSnapshotService
from contentos.normalization.models import NormalizedDocument
from contentos.normalization.service import NormalizationService
from contentos.opportunities.enums import OpportunityDisposition, ResearchInputRole
from contentos.opportunities.linking import (
    distinct_source_count,
    distinctive_tokens,
    link_related_research_inputs,
)
from contentos.opportunities.models import EditorialOpportunity
from contentos.opportunities.repository import OpportunityRepository
from contentos.opportunities.service import ResearchPromotionService
from contentos.research.enums import EvidenceType, ExtractionMethod, VerificationStatus
from contentos.research.model_extractor import (
    MODEL_EXTRACTOR_NAME,
    ModelEvidenceExtractor,
    locate_excerpt,
)
from contentos.research.models import ResearchEvidence
from contentos.research.pending import documents_pending_model_evidence
from contentos.sources.enums import DiscoveryStrategy, SourceKind, SourceRole, TrustTier
from contentos.sources.models import Source
from contentos.sources.service import SourceRegistryService
from contentos.workflow.enums import WorkflowState

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
TEXT = (
    "Unicorn temalı doğum günü partisi için 12 çocuk davet ettik. "
    "Balonları şişirmek yaklaşık 45 dakika sürdü. "
    "Pastayı bir gün önceden hazırlayın ve buzdolabında saklayın. "
    "Gökkuşağı renkli krema için doğal boyalar kullandık."
)


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db_session:
        yield db_session
    engine.dispose()


def make_source(session: Session, slug: str, role: SourceRole = SourceRole.INSPIRATION) -> Source:
    source = SourceRegistryService(session).register_source(
        slug=slug,
        name=f"Kaynak {slug}",
        kind=SourceKind.MANUAL,
        base_url=f"https://{slug}.example.test/",
        trust_tier=TrustTier.GENERAL,
        discovery_strategy=DiscoveryStrategy.MANUAL,
    )
    source.primary_role = role
    session.flush()
    return source


def make_document(
    session: Session,
    source: Source,
    *,
    title: str,
    text: str = TEXT,
    path: str | None = None,
    decide: bool = True,
) -> NormalizedDocument:
    discoveries = DiscoveryService(session)
    slug = path or title.lower().replace(" ", "-")
    item = discoveries.discover_manual(source.id, f"{source.base_url}{slug}")
    discoveries.accept_item(item.id)
    body = text.encode()
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
        clean_text=text,
        title=title,
        headings=[],
    )
    if decide:
        session.add(
            DuplicateDecision(
                normalized_document_id=document.id,
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
    session.flush()
    return document


def candidate(
    kind: str, statement: str, excerpt: str, basis: str = "metinde geçiyor"
) -> dict[str, Any]:
    return {"evidence_type": kind, "statement": statement, "excerpt": excerpt, "basis": basis}


def provider_with(candidates: list[dict[str, Any]]) -> FakeStructuredProvider:
    return FakeStructuredProvider(payload={"candidates": candidates})


def model_rows(session: Session, document: NormalizedDocument) -> list[ResearchEvidence]:
    return list(
        session.scalars(
            select(ResearchEvidence)
            .where(
                ResearchEvidence.normalized_document_id == document.id,
                ResearchEvidence.extractor_name == MODEL_EXTRACTOR_NAME,
            )
            .order_by(ResearchEvidence.excerpt_start)
        )
    )


# --- extractor ------------------------------------------------------------------------


class TestModelEvidenceExtractor:
    def test_grounded_candidates_become_verified_facts_and_others_are_rejected(
        self, session: Session
    ) -> None:
        source = make_source(session, "ilham")
        document = make_document(session, source, title="Unicorn Birthday Party")
        provider = provider_with(
            [
                candidate("statistic", "Partiye 12 çocuk davet edilmiş.", "12 çocuk davet ettik"),
                candidate(
                    "instruction",
                    "Pasta bir gün önceden hazırlanıp buzdolabında saklanmalı.",
                    "Pastayı bir gün önceden hazırlayın ve buzdolabında saklayın.",
                ),
                candidate("statistic", "Balonlar 45 dakikada şişti.", "balonlar 45 dakika sürdü"),
            ]
        )

        result = ModelEvidenceExtractor(session).extract(document.id, provider=provider, now=NOW)
        session.commit()

        assert result.status is GenerationStatus.SUCCEEDED
        assert result.attempt_created is True
        assert len(result.created) == 2
        assert result.rejected == 1  # paraphrased excerpt is not in the text
        rows = model_rows(session, document)
        assert [row.evidence_type for row in rows] == [
            EvidenceType.STATISTIC,
            EvidenceType.INSTRUCTION,
        ]
        first = rows[0]
        assert first.extraction_method is ExtractionMethod.MODEL_ASSISTED
        assert first.verification_status is VerificationStatus.VERIFIED
        assert first.excerpt == "12 çocuk davet ettik"
        assert TEXT[first.excerpt_start : first.excerpt_end] == first.excerpt
        assert first.metadata_json["generation_attempt_id"] == str(result.attempt.id)
        assert first.metadata_json["basis"] == "metinde geçiyor"
        assert first.statement == "Partiye 12 çocuk davet edilmiş."
        attempt = session.get(AiGenerationAttempt, result.attempt.id)
        assert attempt is not None
        assert attempt.purpose is GenerationPurpose.EVIDENCE_EXTRACTION
        assert attempt.input_refs["normalized_document_id"] == str(document.id)
        # The text itself is never persisted on the attempt.
        assert "text" not in attempt.input_refs

    def test_rerun_reuses_the_attempt_without_calling_the_provider(self, session: Session) -> None:
        source = make_source(session, "ilham")
        document = make_document(session, source, title="Unicorn Birthday Party")
        provider = provider_with([candidate("statistic", "12 çocuk.", "12 çocuk davet ettik")])
        extractor = ModelEvidenceExtractor(session)
        first = extractor.extract(document.id, provider=provider, now=NOW)
        session.commit()
        second = extractor.extract(document.id, provider=provider, now=NOW)

        assert provider.invocations == 1
        assert second.attempt_created is False
        assert second.attempt.id == first.attempt.id
        assert [row.id for row in second.existing] == [row.id for row in first.created]
        assert len(model_rows(session, document)) == 1

    def test_overlapping_oversized_and_empty_excerpts_are_rejected(self, session: Session) -> None:
        source = make_source(session, "ilham")
        document = make_document(session, source, title="Unicorn Birthday Party")
        provider = provider_with(
            [
                candidate("quote", "Alıntı.", "Balonları şişirmek yaklaşık 45 dakika sürdü."),
                candidate("statistic", "45 dakika.", "yaklaşık 45 dakika"),  # overlaps the quote
                candidate("statistic", "Yok.", "x" * 400),  # not in the text
                candidate("statistic", "Boş.", "   "),
            ]
        )

        result = ModelEvidenceExtractor(session).extract(document.id, provider=provider, now=NOW)

        assert len(result.created) == 1
        assert result.rejected == 3
        assert result.created[0].evidence_type is EvidenceType.QUOTE

    def test_signal_only_and_community_sources_never_reach_the_provider(
        self, session: Session
    ) -> None:
        community = make_source(session, "forum", SourceRole.COMMUNITY_INTENT)
        taxonomy = make_source(session, "dukkan", SourceRole.TAXONOMY)
        forum_doc = make_document(session, community, title="Forum sorusu")
        shop_doc = make_document(session, taxonomy, title="Ürün sayfası")
        provider = provider_with([candidate("statistic", "12 çocuk.", "12 çocuk davet ettik")])
        extractor = ModelEvidenceExtractor(session)

        forum = extractor.extract(forum_doc.id, provider=provider)
        shop = extractor.extract(shop_doc.id, provider=provider)

        assert forum.skipped_reason == "community_source"
        assert shop.skipped_reason == "signal_only_source"
        assert provider.invocations == 0
        assert session.scalar(select(ResearchEvidence)) is None

    def test_provider_failure_is_a_durable_attempt_with_no_evidence(self, session: Session) -> None:
        source = make_source(session, "ilham")
        document = make_document(session, source, title="Unicorn Birthday Party")
        provider = FakeStructuredProvider(failure=ProviderFailureKind.TIMEOUT)

        result = ModelEvidenceExtractor(session).extract(document.id, provider=provider)
        session.commit()

        assert result.status is GenerationStatus.TIMEOUT
        assert result.attempt is not None and result.attempt_created is True
        assert result.created == [] and result.rejected == 0
        assert model_rows(session, document) == []

    def test_empty_batch_is_a_success_with_no_rows(self, session: Session) -> None:
        source = make_source(session, "ilham")
        document = make_document(session, source, title="Unicorn Birthday Party")
        result = ModelEvidenceExtractor(session).extract(document.id, provider=provider_with([]))
        assert result.status is GenerationStatus.SUCCEEDED
        assert result.created == []

    def test_long_documents_are_projected_as_bounded_segments(self, session: Session) -> None:
        from contentos.research.model_extractor import MAX_TEXT_CHARS, text_segments

        long_text = (TEXT + " ") * 60  # ~13k chars, beyond the projection bound
        source = make_source(session, "ilham")
        document = make_document(session, source, title="Uzun yazı", text=long_text)
        provider = provider_with([candidate("statistic", "12 çocuk.", "12 çocuk davet ettik")])

        result = ModelEvidenceExtractor(session).extract(document.id, provider=provider, now=NOW)

        assert result.status is GenerationStatus.SUCCEEDED
        assert len(result.created) == 1
        segments = text_segments(long_text[:MAX_TEXT_CHARS])
        assert "".join(segments) == long_text[:MAX_TEXT_CHARS]
        assert all(len(segment) <= 3_000 for segment in segments)

    def test_locate_excerpt_is_exact_after_trimming(self) -> None:
        assert locate_excerpt("abc def", " def ") == (4, 7)
        assert locate_excerpt("abc def", "de f") is None
        assert locate_excerpt("abc def", "") is None


# --- cross-source research inputs ---------------------------------------------------------


def promote(session: Session, document: NormalizedDocument) -> EditorialOpportunity:
    result = ResearchPromotionService(session).promote_research(document.id)
    opportunity = OpportunityRepository(session).get_by_id(result.opportunity_id)
    assert opportunity is not None
    return opportunity


class TestResearchInputLinking:
    def test_distinctive_tokens_drop_generic_domain_words(self) -> None:
        assert distinctive_tokens("Unicorn Birthday Party | Kara's Party Ideas") == ("unicorn",)
        assert distinctive_tokens("Sparkle + Shine Unicorn Party") == (
            "sparkle",
            "shine",
            "unicorn",
        )
        assert distinctive_tokens("Birthday Party Ideas") == ()

    def test_related_documents_from_other_sources_are_linked_on_promotion(
        self, session: Session
    ) -> None:
        karas = make_source(session, "karas")
        pretty = make_source(session, "pretty")
        forum = make_source(session, "forum", SourceRole.COMMUNITY_INTENT)
        root = make_document(session, karas, title="Unicorn Birthday Party")
        related = make_document(session, pretty, title="Sparkle + Shine Unicorn Party")
        make_document(session, pretty, title="Woodland Fox Tea Party")
        make_document(session, forum, title="Unicorn parti nereden alınır?")
        undecided = make_document(
            session, karas, title="Unicorn Cake Ideas", decide=False, path="unicorn-cake"
        )

        opportunity = promote(session, root)
        session.commit()

        inputs = OpportunityRepository(session).list_research_inputs(opportunity.id)
        by_document = {row.normalized_document_id: row for row in inputs}
        assert root.id in by_document and related.id in by_document
        assert undecided.id not in by_document  # no duplicate decision → cannot be pinned
        assert len(inputs) == 2
        linked = by_document[related.id]
        assert linked.role is ResearchInputRole.SUPPORTING
        assert linked.note == "ilişkili konu: unicorn"
        assert distinct_source_count(session, opportunity) == 2

        # Linking again adds nothing: idempotent and bounded.
        outcome = link_related_research_inputs(session, opportunity.id)
        assert outcome.linked == 0
        assert len(OpportunityRepository(session).list_research_inputs(opportunity.id)) == 2

    def test_generic_titles_never_link(self, session: Session) -> None:
        karas = make_source(session, "karas")
        pretty = make_source(session, "pretty")
        root = make_document(session, karas, title="Birthday Party Ideas")
        make_document(session, pretty, title="Best Birthday Party Ideas 2026")

        opportunity = promote(session, root)
        outcome = link_related_research_inputs(session, opportunity.id)

        assert outcome.topic_tokens == ()
        assert outcome.linked == 0
        assert len(OpportunityRepository(session).list_research_inputs(opportunity.id)) == 1


# --- pending documents + planner ----------------------------------------------------------


class TestPendingAndPlanner:
    def test_documents_are_pending_once_until_an_attempt_exists(self, session: Session) -> None:
        karas = make_source(session, "karas")
        root = make_document(session, karas, title="Unicorn Birthday Party")
        opportunity = promote(session, root)
        session.commit()

        assert documents_pending_model_evidence(session, opportunity.id) == (root.id,)

        # A failed attempt is still an attempt: never re-queued automatically.
        ModelEvidenceExtractor(session).extract(
            root.id, provider=FakeStructuredProvider(failure=ProviderFailureKind.PROVIDER_ERROR)
        )
        session.commit()
        assert documents_pending_model_evidence(session, opportunity.id) == ()

    def test_pending_excludes_signal_only_sources(self, session: Session) -> None:
        karas = make_source(session, "karas")
        root = make_document(session, karas, title="Unicorn Birthday Party")
        opportunity = promote(session, root)
        forum = make_source(session, "forum", SourceRole.COMMUNITY_INTENT)
        forum_doc = make_document(session, forum, title="Unicorn soru")
        from contentos.opportunities.enums import OpportunityActor
        from contentos.opportunities.models import OpportunityResearchInput

        decision = session.scalar(
            select(DuplicateDecision).where(
                DuplicateDecision.normalized_document_id == forum_doc.id
            )
        )
        assert decision is not None
        OpportunityRepository(session).insert_research_input(
            OpportunityResearchInput(
                opportunity_id=opportunity.id,
                normalized_document_id=forum_doc.id,
                duplicate_decision_id=decision.id,
                role=ResearchInputRole.CONTEXT,
                added_by=OpportunityActor.OPERATOR,
                note=None,
                added_at=NOW,
            )
        )
        session.flush()
        assert documents_pending_model_evidence(session, opportunity.id) == (root.id,)

    def test_planner_extracts_facts_before_building_a_pack(self) -> None:
        base = Snapshot(
            work_item_id=uuid.uuid4(),
            state=WorkflowState.EVIDENCE_BUILDING,
            opportunity_id=uuid.uuid4(),
            disposition=OpportunityDisposition.COMMISSIONED,
            idea_count=3,
            selected_idea_id=uuid.uuid4(),
            eligible_evidence_count=2,
        )
        pending = uuid.uuid4()
        needs_facts = dataclasses.replace(base, documents_pending_model_evidence=(pending,))
        action = plan(needs_facts, AutopilotMode.AUTONOMOUS)
        assert action.kind == "enqueue" and action.name == ACTION_EXTRACT_EVIDENCE
        assert action.payload["normalized_document_ids"] == [str(pending)]

        has_facts = dataclasses.replace(
            base, documents_pending_model_evidence=(pending,), verified_evidence_count=1
        )
        assert plan(has_facts, AutopilotMode.AUTONOMOUS).name == ACTION_BUILD_PACK

        assert plan(base, AutopilotMode.SUPERVISED).name == ACTION_BUILD_PACK


class TestProjectionDepth:
    def test_over_deep_projections_are_folded_not_refused(self) -> None:
        from contentos.ai.dto import (
            MAX_PROJECTION_DEPTH,
            GenerationRequest,
            clamp_projection_depth,
        )

        deep = {"idea": {"planning": {"dimensions": {"steps": [{"n": 1, "why": "x"}]}}}}
        clamped = clamp_projection_depth(deep, MAX_PROJECTION_DEPTH)
        steps = clamped["idea"]["planning"]["dimensions"]["steps"]
        assert isinstance(steps, str) and steps.startswith("[")
        request = GenerationRequest(
            purpose=GenerationPurpose.EVIDENCE_EXTRACTION,
            schema_name="evidence-candidate-batch",
            schema_version="1",
            template_name="evidence-extraction",
            template_version="1",
            input_projection=deep,
        )
        assert request.input_projection["idea"]["planning"]["dimensions"]["steps"] == steps
        # Deterministic: the same input folds to the same projection.
        assert clamp_projection_depth(deep, MAX_PROJECTION_DEPTH) == clamped
