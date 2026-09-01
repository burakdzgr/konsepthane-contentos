"""Opportunity persistence + Phase 2 -> Phase 3 promotion tests (real services)."""

import hashlib
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from contentos.db.base import Base
from contentos.discovery.service import DiscoveryService
from contentos.duplicates.enums import DuplicateDecisionOutcome
from contentos.duplicates.models import DuplicateDecision
from contentos.duplicates.repository import DuplicateDecisionRepository
from contentos.fetching.models import (
    FetchOutcome,
    FetchResult,
    RetryClassification,
    RobotsDecision,
)
from contentos.fetching.snapshot_service import FetchSnapshotService
from contentos.normalization.enums import NormalizationFailureCode
from contentos.normalization.service import NormalizationService
from contentos.opportunities.enums import (
    OpportunityActor,
    OpportunityDisposition,
    ResearchInputRole,
)
from contentos.opportunities.errors import (
    InvalidPromotionInputError,
    PromotionConflictError,
    PromotionNotEligibleError,
    PromotionRootNotFoundError,
)
from contentos.opportunities.models import EditorialOpportunity, OpportunityResearchInput
from contentos.opportunities.repository import OpportunityRepository
from contentos.opportunities.service import ResearchPromotionService
from contentos.sources.enums import SourceKind, TrustTier
from contentos.sources.service import SourceRegistryService
from contentos.workflow.enums import WorkflowActorOrigin, WorkflowState, WorkItemOrigin
from contentos.workflow.models import EditorialWorkflowEvent, EditorialWorkItem
from contentos.workflow.repository import WorkflowRepository

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


@pytest.fixture()
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
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


def seed_document(
    session: Session,
    slug: str,
    *,
    title: str | None = "İstanbul Doğum Günü Rehberi",
    succeed_normalization: bool = True,
) -> uuid.UUID:
    """Full real Phase 2 chain: source -> item -> snapshot -> document."""
    source = SourceRegistryService(session).register_source(
        slug=slug,
        name=f"Kaynak {slug}",
        kind=SourceKind.MANUAL,
        base_url=f"https://{slug}.example.test/",
        trust_tier=TrustTier.GENERAL,
    )
    discoveries = DiscoveryService(session)
    item = discoveries.discover_manual(source.id, f"https://{slug}.example.test/haber")
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
    normalization = NormalizationService(session)
    if succeed_normalization:
        document = normalization.record_success(
            snapshot.id,
            extractor_name="html-basic",
            extractor_version="1",
            clean_text=f"{slug} için uzun ve özgün araştırma metni burada.",
            title=title,
        )
    else:
        document = normalization.record_failure(
            snapshot.id,
            extractor_name="html-basic",
            extractor_version="1",
            failure_code=NormalizationFailureCode.UNSUPPORTED_CONTENT,
        )
    session.commit()
    return document.id


def record_decision(
    session: Session,
    document_id: uuid.UUID,
    outcome: DuplicateDecisionOutcome,
    *,
    engine_version: str = "1",
    evaluated_at: datetime = NOW,
) -> uuid.UUID:
    decision = DuplicateDecision(
        normalized_document_id=document_id,
        engine_name="duplicate-engine",
        engine_version=engine_version,
        decision=outcome,
        signals={},
        thresholds={},
        matches=[],
        rationale_codes=[],
        evaluated_at=evaluated_at,
    )
    session.add(decision)
    session.commit()
    return decision.id


def promoted_root(
    factory: sessionmaker[Session],
    slug: str,
    outcome: DuplicateDecisionOutcome = DuplicateDecisionOutcome.UNIQUE,
) -> tuple[uuid.UUID, uuid.UUID]:
    with open_session(factory) as session:
        document_id = seed_document(session, slug)
        decision_id = record_decision(session, document_id, outcome)
        return document_id, decision_id


class TestEligibilityGate:
    def test_missing_document_raises_not_found(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            with pytest.raises(PromotionRootNotFoundError):
                ResearchPromotionService(session).promote_research(uuid.uuid4())

    def test_failed_normalization_is_not_eligible(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            document_id = seed_document(session, "bozuk", succeed_normalization=False)
            record_decision(session, document_id, DuplicateDecisionOutcome.UNIQUE)
            with pytest.raises(PromotionNotEligibleError, match="SUCCEEDED"):
                ResearchPromotionService(session).promote_research(document_id)

    def test_missing_decision_is_a_hard_stop(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            document_id = seed_document(session, "kararsiz")
            with pytest.raises(PromotionNotEligibleError, match="not a pass"):
                ResearchPromotionService(session).promote_research(document_id)

    @pytest.mark.parametrize(
        "outcome",
        [DuplicateDecisionOutcome.DUPLICATE, DuplicateDecisionOutcome.REJECT],
    )
    def test_hard_stop_outcomes_create_nothing(
        self, session_factory: sessionmaker[Session], outcome: DuplicateDecisionOutcome
    ) -> None:
        document_id, _ = promoted_root(session_factory, f"dur-{outcome.value}", outcome)
        with open_session(session_factory) as session:
            with pytest.raises(PromotionNotEligibleError, match="hard stop"):
                ResearchPromotionService(session).promote_research(document_id)
            session.rollback()

        with open_session(session_factory) as session:
            assert session.execute(select(EditorialWorkItem)).scalar_one_or_none() is None
            assert session.execute(select(EditorialOpportunity)).scalar_one_or_none() is None

    def test_effective_decision_is_deterministic_latest(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            document_id = seed_document(session, "surumlu")
            record_decision(session, document_id, DuplicateDecisionOutcome.UNIQUE, evaluated_at=NOW)
            record_decision(
                session,
                document_id,
                DuplicateDecisionOutcome.DUPLICATE,
                engine_version="2",
                evaluated_at=NOW + timedelta(minutes=5),
            )
            effective = DuplicateDecisionRepository(session).get_effective_for_document(document_id)
            assert effective is not None
            assert effective.decision is DuplicateDecisionOutcome.DUPLICATE
            # The newer DUPLICATE decision governs: promotion is a hard stop.
            with pytest.raises(PromotionNotEligibleError):
                ResearchPromotionService(session).promote_research(document_id)


class TestStandardPromotion:
    def test_unique_promotion_creates_full_chain(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        document_id, decision_id = promoted_root(session_factory, "ozgun")
        with open_session(session_factory) as session:
            result = ResearchPromotionService(session).promote_research(
                document_id, request_id="promo-req-1"
            )
            session.commit()

            assert result.created is True
            assert result.duplicate_outcome is DuplicateDecisionOutcome.UNIQUE

            work_item = WorkflowRepository(session).get_by_id(result.work_item_id)
            assert work_item is not None
            assert work_item.current_state is WorkflowState.IDEA_SCORING
            assert work_item.origin is WorkItemOrigin.RESEARCH_INTAKE
            assert work_item.locale == "tr-TR"
            assert work_item.market == "TR"
            assert work_item.title_working_label == "İstanbul Doğum Günü Rehberi"

            events = WorkflowRepository(session).list_events(result.work_item_id)
            assert len(events) == 1
            creation = events[0]
            assert creation.from_state is None
            assert creation.to_state is WorkflowState.IDEA_SCORING
            assert creation.actor_origin is WorkflowActorOrigin.SYSTEM
            assert "unique" in creation.reason
            assert creation.request_id == "promo-req-1"
            refs = creation.artifact_refs
            assert refs["promotion"] == "research_intake"
            assert refs["normalized_document_id"] == str(document_id)
            assert refs["duplicate_decision_id"] == str(decision_id)
            assert refs["duplicate_outcome"] == "unique"
            for key in ("fetch_snapshot_id", "discovery_item_id", "source_id"):
                assert uuid.UUID(refs[key])

            opportunity = OpportunityRepository(session).get_by_id(result.opportunity_id)
            assert opportunity is not None
            assert opportunity.work_item_id == result.work_item_id
            assert opportunity.promotion_root_document_id == document_id
            assert opportunity.disposition is OpportunityDisposition.OPEN
            assert opportunity.disposition_reason is None
            assert opportunity.topic_summary == "İstanbul Doğum Günü Rehberi"
            assert opportunity.update_of_reference is None

            inputs = OpportunityRepository(session).list_research_inputs(opportunity.id)
            assert len(inputs) == 1
            research_input = inputs[0]
            assert research_input.normalized_document_id == document_id
            assert research_input.duplicate_decision_id == decision_id
            assert research_input.role is ResearchInputRole.PRIMARY_SIGNAL
            assert research_input.added_by is OpportunityActor.SYSTEM
            assert research_input.note is None

    def test_related_promotion_is_eligible_and_relationship_stays_visible(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        document_id, decision_id = promoted_root(
            session_factory, "iliskili", DuplicateDecisionOutcome.RELATED
        )
        with open_session(session_factory) as session:
            result = ResearchPromotionService(session).promote_research(document_id)
            session.commit()

            assert result.duplicate_outcome is DuplicateDecisionOutcome.RELATED
            creation = WorkflowRepository(session).list_events(result.work_item_id)[0]
            assert creation.artifact_refs["duplicate_outcome"] == "related"
            [research_input] = OpportunityRepository(session).list_research_inputs(
                result.opportunity_id
            )
            # RELATED is never converted to UNIQUE: the exact decision stays pinned.
            assert research_input.duplicate_decision_id == decision_id
            assert research_input.role is ResearchInputRole.PRIMARY_SIGNAL

    def test_update_existing_promotion_is_an_update_signal(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        document_id, decision_id = promoted_root(
            session_factory, "guncelleme", DuplicateDecisionOutcome.UPDATE_EXISTING
        )
        with open_session(session_factory) as session:
            result = ResearchPromotionService(session).promote_research(document_id)
            session.commit()

            opportunity = OpportunityRepository(session).get_by_id(result.opportunity_id)
            assert opportunity is not None
            assert opportunity.update_of_reference == (
                f"update/refresh signal per duplicate decision {decision_id}"
            )
            [research_input] = OpportunityRepository(session).list_research_inputs(
                result.opportunity_id
            )
            assert research_input.role is ResearchInputRole.UPDATE_SIGNAL
            # No production inventory exists: no article identity is claimed.
            assert "article" not in (opportunity.update_of_reference or "")

    def test_label_falls_back_when_document_has_no_title(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            document_id = seed_document(session, "bassiz", title=None)
            record_decision(session, document_id, DuplicateDecisionOutcome.UNIQUE)
            result = ResearchPromotionService(session).promote_research(document_id)
            session.commit()
            work_item = WorkflowRepository(session).get_by_id(result.work_item_id)
            assert work_item is not None
            assert work_item.title_working_label == "https://bassiz.example.test/haber"

    def test_invalid_optional_inputs_rejected(self, session_factory: sessionmaker[Session]) -> None:
        document_id, _ = promoted_root(session_factory, "gecersiz-girdi")
        with open_session(session_factory) as session:
            service = ResearchPromotionService(session)
            with pytest.raises(InvalidPromotionInputError):
                service.promote_research(document_id, title_working_label="   ")
            with pytest.raises(InvalidPromotionInputError):
                service.promote_research(document_id, topic_summary="x" * 1001)


class TestIdempotencyAndConflicts:
    def test_identical_retry_returns_existing_result(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        document_id, _ = promoted_root(session_factory, "tekrar")
        with open_session(session_factory) as session:
            service = ResearchPromotionService(session)
            first = service.promote_research(document_id)
            session.commit()
            second = service.promote_research(document_id)
            session.commit()

            assert second.created is False
            assert second.work_item_id == first.work_item_id
            assert second.opportunity_id == first.opportunity_id
            # No second creation event, opportunity, or input appeared.
            assert len(WorkflowRepository(session).list_events(first.work_item_id)) == 1
            assert len(list(session.execute(select(EditorialOpportunity)).scalars())) == 1
            assert len(list(session.execute(select(OpportunityResearchInput)).scalars())) == 1

    def test_race_recovers_existing_promotion(
        self, session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        document_id, _ = promoted_root(session_factory, "yaris")
        with open_session(session_factory) as session:
            first = ResearchPromotionService(session).promote_research(document_id)
            session.commit()

        with open_session(session_factory) as session:
            service = ResearchPromotionService(session)
            # Simulate the race window: the pre-check misses the winner, so
            # the insert hits the DB uniqueness and must recover.
            original = OpportunityRepository.get_by_promotion_root
            calls = {"count": 0}

            def racy_lookup(
                self: OpportunityRepository, normalized_document_id: uuid.UUID
            ) -> EditorialOpportunity | None:
                calls["count"] += 1
                if calls["count"] == 1:
                    return None  # pre-check misses the concurrent winner
                return original(self, normalized_document_id)

            monkeypatch.setattr(OpportunityRepository, "get_by_promotion_root", racy_lookup)
            recovered = service.promote_research(document_id)
            session.commit()

            assert recovered.created is False
            assert recovered.work_item_id == first.work_item_id
            assert len(WorkflowRepository(session).list_events(first.work_item_id)) == 1

    def test_incompatible_retry_conflicts_instead_of_overwriting(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        document_id, _ = promoted_root(session_factory, "uyumsuz")
        with open_session(session_factory) as session:
            service = ResearchPromotionService(session)
            service.promote_research(document_id)
            session.commit()
            # Later, a newer engine version marks the document DUPLICATE.
            # The operator override now applies outcome-wise, but the root is
            # already promoted with research-intake semantics: conflict, no
            # silent overwrite.
            record_decision(
                session,
                document_id,
                DuplicateDecisionOutcome.DUPLICATE,
                engine_version="2",
                evaluated_at=NOW + timedelta(minutes=10),
            )
            with pytest.raises(PromotionConflictError):
                service.promote_duplicate_override(
                    document_id,
                    reason="operator wants override",
                    distinct_angle="tamamen farklı bir açı",
                )
            # The existing promotion is untouched.
            assert len(list(session.execute(select(EditorialOpportunity)).scalars())) == 1

    def test_atomic_rollback_leaves_no_orphans(
        self, session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        document_id, _ = promoted_root(session_factory, "atomik")

        def boom(
            self: OpportunityRepository, research_input: OpportunityResearchInput
        ) -> OpportunityResearchInput:
            raise RuntimeError("simulated failure after work item creation")

        monkeypatch.setattr(OpportunityRepository, "insert_research_input", boom)
        with open_session(session_factory) as session:
            with pytest.raises(RuntimeError):
                ResearchPromotionService(session).promote_research(document_id)
            session.rollback()

        with open_session(session_factory) as session:
            assert session.execute(select(EditorialWorkItem)).scalar_one_or_none() is None
            assert session.execute(select(EditorialWorkflowEvent)).scalar_one_or_none() is None
            assert session.execute(select(EditorialOpportunity)).scalar_one_or_none() is None
            assert session.execute(select(OpportunityResearchInput)).scalar_one_or_none() is None

    def test_promoted_document_can_still_support_another_opportunity(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        document_a, decision_a = promoted_root(session_factory, "kok-a")
        document_b, _ = promoted_root(session_factory, "kok-b")
        with open_session(session_factory) as session:
            service = ResearchPromotionService(session)
            service.promote_research(document_a)
            result_b = service.promote_research(document_b)
            session.commit()

            # Promotion identity does not block document A from becoming a
            # supporting input on opportunity B.
            repository = OpportunityRepository(session)
            repository.insert_research_input(
                OpportunityResearchInput(
                    opportunity_id=result_b.opportunity_id,
                    normalized_document_id=document_a,
                    duplicate_decision_id=decision_a,
                    role=ResearchInputRole.SUPPORTING,
                    added_by=OpportunityActor.OPERATOR,
                    note="destekleyici kaynak",
                    added_at=NOW,
                )
            )
            session.commit()
            inputs = repository.list_research_inputs(result_b.opportunity_id)
            assert {i.role for i in inputs} == {
                ResearchInputRole.PRIMARY_SIGNAL,
                ResearchInputRole.SUPPORTING,
            }
            assert {i.normalized_document_id for i in inputs} == {
                document_a,
                document_b,
            }


class TestDuplicateOverride:
    def test_operator_override_promotes_duplicate_with_pinned_decision(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        document_id, decision_id = promoted_root(
            session_factory, "cift", DuplicateDecisionOutcome.DUPLICATE
        )
        with open_session(session_factory) as session:
            result = ResearchPromotionService(session).promote_duplicate_override(
                document_id,
                reason="operatör kararı: kaynak aynı ama açı bambaşka",
                distinct_angle="Aynı mekân, tamamen farklı bütçe planlama açısı",
                request_id="override-req-1",
            )
            session.commit()

            work_item = WorkflowRepository(session).get_by_id(result.work_item_id)
            assert work_item is not None
            assert work_item.origin is WorkItemOrigin.OPERATOR
            assert work_item.title_working_label.startswith("Aynı mekân")

            [creation] = WorkflowRepository(session).list_events(result.work_item_id)
            assert creation.actor_origin is WorkflowActorOrigin.OPERATOR
            assert creation.reason == "operatör kararı: kaynak aynı ama açı bambaşka"
            assert creation.artifact_refs["promotion"] == "duplicate_override"
            assert creation.artifact_refs["duplicate_decision_id"] == str(decision_id)
            assert creation.artifact_refs["duplicate_outcome"] == "duplicate"

            opportunity = OpportunityRepository(session).get_by_id(result.opportunity_id)
            assert opportunity is not None
            assert opportunity.topic_summary == ("Aynı mekân, tamamen farklı bütçe planlama açısı")
            [research_input] = OpportunityRepository(session).list_research_inputs(
                result.opportunity_id
            )
            assert research_input.duplicate_decision_id == decision_id
            assert research_input.added_by is OpportunityActor.OPERATOR
            assert research_input.note is not None
            assert "duplicate override" in research_input.note

            # The DUPLICATE decision itself is untouched.
            decision = session.get(DuplicateDecision, decision_id)
            assert decision is not None
            assert decision.decision is DuplicateDecisionOutcome.DUPLICATE

    def test_override_requires_reason_and_distinct_angle(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        document_id, _ = promoted_root(
            session_factory, "cift-eksik", DuplicateDecisionOutcome.DUPLICATE
        )
        with open_session(session_factory) as session:
            service = ResearchPromotionService(session)
            with pytest.raises(InvalidPromotionInputError):
                service.promote_duplicate_override(document_id, reason="  ", distinct_angle="açı")
            with pytest.raises(InvalidPromotionInputError):
                service.promote_duplicate_override(document_id, reason="sebep", distinct_angle="")

    def test_override_refused_for_non_duplicate_outcomes(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        unique_doc, _ = promoted_root(session_factory, "cift-degil")
        with open_session(session_factory) as session:
            with pytest.raises(InvalidPromotionInputError, match="promote_research"):
                ResearchPromotionService(session).promote_duplicate_override(
                    unique_doc, reason="sebep", distinct_angle="açı"
                )

    def test_reject_has_no_override(self, session_factory: sessionmaker[Session]) -> None:
        reject_doc, _ = promoted_root(session_factory, "ret-kok", DuplicateDecisionOutcome.REJECT)
        with open_session(session_factory) as session:
            with pytest.raises(PromotionNotEligibleError, match="no override"):
                ResearchPromotionService(session).promote_duplicate_override(
                    reject_doc, reason="sebep", distinct_angle="açı"
                )

    def test_override_retry_is_idempotent(self, session_factory: sessionmaker[Session]) -> None:
        document_id, _ = promoted_root(
            session_factory, "cift-tekrar", DuplicateDecisionOutcome.DUPLICATE
        )
        with open_session(session_factory) as session:
            service = ResearchPromotionService(session)
            first = service.promote_duplicate_override(
                document_id, reason="sebep", distinct_angle="farklı açı"
            )
            session.commit()
            second = service.promote_duplicate_override(
                document_id, reason="sebep", distinct_angle="farklı açı"
            )
            assert second.created is False
            assert second.work_item_id == first.work_item_id
            # The standard path still hard-stops on the DUPLICATE outcome
            # before ever reaching the existing promotion.
            with pytest.raises(PromotionNotEligibleError):
                service.promote_research(document_id)
