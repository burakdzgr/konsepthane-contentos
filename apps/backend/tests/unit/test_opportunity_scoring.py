"""Deterministic opportunity scoring v1 tests (pure engine + real services)."""

import hashlib
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from contentos.db.base import Base
from contentos.discovery.service import DiscoveryService
from contentos.duplicates.enums import DuplicateDecisionOutcome
from contentos.duplicates.models import DuplicateDecision
from contentos.fetching.models import (
    FetchOutcome,
    FetchResult,
    RetryClassification,
    RobotsDecision,
)
from contentos.fetching.snapshot_service import FetchSnapshotService
from contentos.normalization.service import NormalizationService
from contentos.opportunities.enums import (
    ComponentAvailability,
    OpportunityActor,
    OpportunityDisposition,
    ResearchInputRole,
    ScoreBand,
    ScoreComponent,
    ScoreEligibility,
)
from contentos.opportunities.errors import OpportunityNotFoundError
from contentos.opportunities.models import (
    OpportunityResearchInput,
    OpportunityScore,
    OpportunityScoreComponent,
)
from contentos.opportunities.repository import OpportunityRepository
from contentos.opportunities.scoring import (
    MAX_SNAPSHOT_EVIDENCE_IDS,
    OpportunityScoringEngine,
    ScoringInputDocument,
    ScoringInputs,
    compute_snapshot_hash,
    evidence_snapshot,
)
from contentos.opportunities.scoring_service import OpportunityScoringService
from contentos.opportunities.service import ResearchPromotionService
from contentos.research.enums import EvidenceType, ExtractionMethod
from contentos.research.service import ResearchEvidenceService
from contentos.sources.enums import SourceKind, TrustTier
from contentos.sources.service import SourceRegistryService
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
    trust_tier: TrustTier = TrustTier.GENERAL,
    external_published_at: datetime | None = None,
) -> uuid.UUID:
    source = SourceRegistryService(session).register_source(
        slug=slug,
        name=f"Kaynak {slug}",
        kind=SourceKind.MANUAL,
        base_url=f"https://{slug}.example.test/",
        trust_tier=trust_tier,
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
    document = NormalizationService(session).record_success(
        snapshot.id,
        extractor_name="html-basic",
        extractor_version="1",
        clean_text=f"{slug} için uzun ve özgün araştırma metni burada.",
        title=f"{slug} başlığı",
        external_published_at=external_published_at,
    )
    session.commit()
    return document.id


def record_decision(
    session: Session, document_id: uuid.UUID, outcome: DuplicateDecisionOutcome
) -> uuid.UUID:
    decision = DuplicateDecision(
        normalized_document_id=document_id,
        engine_name="duplicate-engine",
        engine_version="1",
        decision=outcome,
        signals={},
        thresholds={},
        matches=[],
        rationale_codes=[],
        evaluated_at=NOW,
    )
    session.add(decision)
    session.commit()
    return decision.id


def promote(
    session: Session,
    slug: str,
    *,
    trust_tier: TrustTier = TrustTier.GENERAL,
    external_published_at: datetime | None = None,
    outcome: DuplicateDecisionOutcome = DuplicateDecisionOutcome.UNIQUE,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Returns (opportunity_id, document_id)."""
    document_id = seed_document(
        session,
        slug,
        trust_tier=trust_tier,
        external_published_at=external_published_at,
    )
    record_decision(session, document_id, outcome)
    if outcome is DuplicateDecisionOutcome.DUPLICATE:
        result = ResearchPromotionService(session).promote_duplicate_override(
            document_id, reason="operatör kararı", distinct_angle="bambaşka bir açı"
        )
    else:
        result = ResearchPromotionService(session).promote_research(document_id)
    session.commit()
    return result.opportunity_id, document_id


def add_evidence(session: Session, document_id: uuid.UUID, statement: str) -> None:
    ResearchEvidenceService(session).record_evidence(
        document_id,
        evidence_type=EvidenceType.OBSERVATION,
        statement=statement,
        extraction_method=ExtractionMethod.MACHINE,
        source_locator="structured_metadata.author",
    )
    session.commit()


def engine_document(
    *,
    source_id: uuid.UUID | None = None,
    trust_tier: str = "general",
    outcome: str = "unique",
    published: datetime | None = NOW,
    fetched: datetime | None = NOW,
) -> ScoringInputDocument:
    return ScoringInputDocument(
        normalized_document_id=uuid.uuid4(),
        source_id=source_id or uuid.uuid4(),
        trust_tier=trust_tier,
        duplicate_decision_id=uuid.uuid4(),
        duplicate_outcome=outcome,
        external_published_at=published,
        fetched_at=fetched,
    )


def engine_inputs(
    documents: tuple[ScoringInputDocument, ...],
    *,
    evidence_count: int = 0,
    evaluated_at: datetime = NOW,
) -> ScoringInputs:
    return ScoringInputs(
        documents=documents,
        evidence_count=evidence_count,
        documents_with_evidence=min(evidence_count, len(documents)),
        sources_with_evidence=min(evidence_count, len(documents)),
        evaluated_at=evaluated_at,
    )


class TestEngineMath:
    def test_unknown_is_excluded_not_zero(self) -> None:
        """Renormalization: UNKNOWN components never poison the score as 0."""
        engine = OpportunityScoringEngine()
        # One fresh, unique, official source and zero evidence.
        result = engine.evaluate(
            engine_inputs((engine_document(trust_tier="official"),), evidence_count=0)
        )
        # KNOWN: recency 1.0*0.15, evidence 0.0*0.20, diversity 0.3*0.15,
        # trust 1.0*0.15, duplicate 1.0*0.10 over weight 0.75.
        expected = round((1.0 * 0.15 + 0.0 * 0.20 + 0.3 * 0.15 + 1.0 * 0.15 + 1.0 * 0.10) / 0.75, 4)
        assert result.overall_value == expected
        assert expected != round(
            (1.0 * 0.15 + 0.0 * 0.20 + 0.3 * 0.15 + 1.0 * 0.15 + 1.0 * 0.10) / 1.0, 4
        )

    def test_all_twelve_components_are_always_present(self) -> None:
        result = OpportunityScoringEngine().evaluate(engine_inputs((engine_document(),)))
        assert {evaluation.component for evaluation in result.components} == set(ScoreComponent)
        unknown = {
            evaluation.component.value
            for evaluation in result.components
            if evaluation.availability is ComponentAvailability.UNKNOWN
        }
        assert unknown == {
            "audience_fit",
            "competition",
            "search_demand",
            "editorial_value",
            "seasonality",
            "policy_risk",
            "production_cost_estimate",
        }
        assert set(result.missing_signals) == unknown
        for evaluation in result.components:
            if evaluation.availability is not ComponentAvailability.KNOWN:
                assert evaluation.value is None

    @pytest.mark.parametrize(
        ("age_days", "expected"),
        [
            (0, 1.0),
            (7, 1.0),
            (8, 0.8),
            (30, 0.8),
            (31, 0.6),
            (90, 0.6),
            (91, 0.4),
            (365, 0.4),
            (400, 0.2),
        ],
    )
    def test_recency_buckets_pinned(self, age_days: int, expected: float) -> None:
        published = NOW - timedelta(days=age_days)
        result = OpportunityScoringEngine().evaluate(
            engine_inputs((engine_document(published=published),))
        )
        recency = next(e for e in result.components if e.component is ScoreComponent.RECENCY)
        assert recency.value == expected
        assert recency.provenance["basis"] == "external_published_at"

    def test_recency_falls_back_to_fetched_at_and_unknown_without_timestamps(
        self,
    ) -> None:
        engine = OpportunityScoringEngine()
        fallback = engine.evaluate(engine_inputs((engine_document(published=None, fetched=NOW),)))
        recency = next(e for e in fallback.components if e.component is ScoreComponent.RECENCY)
        assert recency.availability is ComponentAvailability.KNOWN
        assert recency.provenance["basis"] == "fetched_at"

        no_timestamps = engine.evaluate(
            engine_inputs((engine_document(published=None, fetched=None),))
        )
        recency = next(e for e in no_timestamps.components if e.component is ScoreComponent.RECENCY)
        # Unknown date is UNKNOWN, never "old".
        assert recency.availability is ComponentAvailability.UNKNOWN
        assert recency.value is None

    @pytest.mark.parametrize(
        ("source_count", "expected"), [(1, 0.3), (2, 0.6), (3, 0.8), (4, 1.0), (5, 1.0)]
    )
    def test_source_diversity_counts_distinct_sources(
        self, source_count: int, expected: float
    ) -> None:
        documents = tuple(engine_document() for _ in range(source_count))
        result = OpportunityScoringEngine().evaluate(engine_inputs(documents))
        diversity = next(
            e for e in result.components if e.component is ScoreComponent.SOURCE_DIVERSITY
        )
        assert diversity.value == expected

    def test_same_source_documents_are_one_source(self) -> None:
        shared = uuid.uuid4()
        documents = tuple(engine_document(source_id=shared) for _ in range(3))
        result = OpportunityScoringEngine().evaluate(engine_inputs(documents))
        diversity = next(
            e for e in result.components if e.component is ScoreComponent.SOURCE_DIVERSITY
        )
        assert diversity.value == 0.3
        assert diversity.provenance["distinct_sources"] == 1

    def test_source_trust_is_mean_over_distinct_sources(self) -> None:
        documents = (
            engine_document(trust_tier="general"),
            engine_document(trust_tier="reputable"),
        )
        result = OpportunityScoringEngine().evaluate(engine_inputs(documents))
        trust = next(e for e in result.components if e.component is ScoreComponent.SOURCE_TRUST)
        assert trust.value == round((0.5 + 0.75) / 2, 4)
        assert trust.provenance["aggregation"] == "mean over distinct sources"

    def test_duplicate_overlap_uses_riskiest_pinned_decision(self) -> None:
        documents = (
            engine_document(outcome="unique"),
            engine_document(outcome="update_existing"),
        )
        result = OpportunityScoringEngine().evaluate(engine_inputs(documents))
        overlap = next(
            e for e in result.components if e.component is ScoreComponent.DUPLICATE_OVERLAP_RISK
        )
        assert overlap.value == 0.5  # min contribution governs
        assert overlap.provenance["value_orientation"].startswith("1.0 means no known")

    def test_zero_evidence_is_known_zero_not_unknown(self) -> None:
        result = OpportunityScoringEngine().evaluate(
            engine_inputs((engine_document(),), evidence_count=0)
        )
        evidence = next(
            e for e in result.components if e.component is ScoreComponent.EVIDENCE_AVAILABILITY
        )
        assert evidence.availability is ComponentAvailability.KNOWN
        assert evidence.value == 0.0

    @pytest.mark.parametrize(
        ("count", "expected"), [(1, 0.4), (2, 0.4), (3, 0.7), (5, 0.7), (6, 1.0)]
    )
    def test_evidence_buckets_pinned(self, count: int, expected: float) -> None:
        result = OpportunityScoringEngine().evaluate(
            engine_inputs((engine_document(),), evidence_count=count)
        )
        evidence = next(
            e for e in result.components if e.component is ScoreComponent.EVIDENCE_AVAILABILITY
        )
        assert evidence.value == expected

    def test_bands_and_eligibility_mapping_pinned(self) -> None:
        engine = OpportunityScoringEngine()
        strong = engine.evaluate(
            engine_inputs(
                (
                    engine_document(trust_tier="official"),
                    engine_document(trust_tier="official"),
                    engine_document(trust_tier="official"),
                    engine_document(trust_tier="official"),
                ),
                evidence_count=6,
            )
        )
        assert strong.overall_value is not None and strong.overall_value >= 0.75
        assert strong.overall_band is ScoreBand.STRONG
        assert strong.eligibility is ScoreEligibility.COMMISSIONABLE

        weak = engine.evaluate(
            engine_inputs(
                (
                    engine_document(
                        trust_tier="reference_only",
                        outcome="duplicate",
                        published=NOW - timedelta(days=400),
                    ),
                ),
                evidence_count=0,
            )
        )
        assert weak.overall_value is not None and weak.overall_value < 0.55
        assert weak.overall_band is ScoreBand.WEAK
        assert weak.eligibility is ScoreEligibility.NOT_COMMISSIONABLE
        # v1 never emits the reserved INELIGIBLE band.
        assert weak.overall_band is not ScoreBand.INELIGIBLE

    def test_low_known_coverage_forces_operator_review(self) -> None:
        # No documents: only evidence availability is KNOWN -> coverage fails.
        result = OpportunityScoringEngine().evaluate(engine_inputs((), evidence_count=6))
        assert result.eligibility is ScoreEligibility.NEEDS_OPERATOR_REVIEW

    def test_snapshots_expose_weights_and_thresholds(self) -> None:
        result = OpportunityScoringEngine().evaluate(engine_inputs((engine_document(),)))
        assert sum(result.weights_snapshot["weights"].values()) == pytest.approx(1.0)
        assert result.threshold_snapshot["bands"] == {"strong": 0.75, "moderate": 0.55}
        assert result.threshold_snapshot["coverage_rule"]["min_known_core_components"] == 3
        assert result.risk_flags == ()


class TestSnapshotHash:
    def test_hash_is_order_independent_and_stable(self) -> None:
        snapshot_a = {"b": [3, 2, 1], "a": {"y": 1, "x": 2}}
        snapshot_b = {"a": {"x": 2, "y": 1}, "b": [3, 2, 1]}
        assert compute_snapshot_hash(snapshot_a) == compute_snapshot_hash(snapshot_b)
        assert len(compute_snapshot_hash(snapshot_a)) == 64

    def test_evidence_snapshot_is_bounded(self) -> None:
        few = [uuid.uuid4() for _ in range(3)]
        small = evidence_snapshot(few)
        assert small["count"] == 3
        assert small["ids"] == sorted(str(i) for i in few)

        many = [uuid.uuid4() for _ in range(MAX_SNAPSHOT_EVIDENCE_IDS + 1)]
        large = evidence_snapshot(many)
        assert "ids" not in large
        assert large["count"] == MAX_SNAPSHOT_EVIDENCE_IDS + 1
        assert len(large["set_hash"]) == 64
        # Order independence.
        assert evidence_snapshot(list(reversed(many))) == large


class TestScoringService:
    def test_full_evaluation_persists_score_and_all_components(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, document_id = promote(session, "puanla")
            add_evidence(session, document_id, "Kaynak, yazarını belirtiyor.")

            evaluation = OpportunityScoringService(session).evaluate_opportunity(
                opportunity_id, evaluated_at=NOW
            )
            session.commit()

            assert evaluation.created is True
            score = evaluation.score
            assert score.engine_name == "opportunity-engine"
            assert score.engine_version == "1"
            assert score.overall_band in (ScoreBand.MODERATE, ScoreBand.WEAK)
            assert score.overall_value is not None
            assert score.input_snapshot["research_inputs"][0]["normalized_document_id"] == str(
                document_id
            )
            assert score.input_snapshot["evidence"]["count"] == 1
            assert score.input_snapshot["evaluated_on"] == "2026-09-01"
            assert len(score.input_snapshot_hash) == 64
            assert set(score.missing_signals) == {
                "audience_fit",
                "competition",
                "search_demand",
                "editorial_value",
                "seasonality",
                "policy_risk",
                "production_cost_estimate",
            }

            components = OpportunityRepository(session).list_score_components(score.id)
            assert len(components) == 12
            by_component = {row.component: row for row in components}
            known = [row for row in components if row.availability is ComponentAvailability.KNOWN]
            assert len(known) == 5
            for row in known:
                assert row.provider == "derived_phase2"
                assert row.observed_at == NOW
            unknown_row = by_component[ScoreComponent.SEARCH_DEMAND]
            assert unknown_row.availability is ComponentAvailability.UNKNOWN
            assert unknown_row.value is None
            assert unknown_row.provider is None

    def test_scoring_never_mutates_disposition_or_workflow(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, _ = promote(session, "dokunma")
            OpportunityScoringService(session).evaluate_opportunity(
                opportunity_id, evaluated_at=NOW
            )
            session.commit()

            opportunity = OpportunityRepository(session).get_by_id(opportunity_id)
            assert opportunity is not None
            assert opportunity.disposition is OpportunityDisposition.OPEN
            events = WorkflowRepository(session).list_events(opportunity.work_item_id)
            assert len(events) == 1  # only the promotion creation event

    def test_identical_retry_returns_existing_score(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, _ = promote(session, "tekrar-puan")
            service = OpportunityScoringService(session)
            first = service.evaluate_opportunity(opportunity_id, evaluated_at=NOW)
            session.commit()
            second = service.evaluate_opportunity(opportunity_id, evaluated_at=NOW)

            assert second.created is False
            assert second.score.id == first.score.id
            assert len(list(session.execute(select(OpportunityScore)).scalars())) == 1
            assert len(list(session.execute(select(OpportunityScoreComponent)).scalars())) == 12

    def test_changed_evidence_appends_new_score_and_effective_is_latest(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, document_id = promote(session, "degisen")
            service = OpportunityScoringService(session)
            first = service.evaluate_opportunity(opportunity_id, evaluated_at=NOW)
            session.commit()

            add_evidence(session, document_id, "Kaynak, tarih belirtiyor.")
            second = service.evaluate_opportunity(
                opportunity_id, evaluated_at=NOW + timedelta(hours=1)
            )
            session.commit()

            assert second.created is True
            assert second.score.id != first.score.id
            scores = OpportunityRepository(session).list_scores(opportunity_id)
            assert len(scores) == 2  # old history retained, never mutated
            effective = OpportunityRepository(session).get_effective_score(opportunity_id)
            assert effective is not None
            assert effective.id == second.score.id

    def test_later_day_reevaluation_appends_new_score(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, _ = promote(session, "gunler")
            service = OpportunityScoringService(session)
            service.evaluate_opportunity(opportunity_id, evaluated_at=NOW)
            session.commit()
            later = service.evaluate_opportunity(
                opportunity_id, evaluated_at=NOW + timedelta(days=40)
            )
            session.commit()
            # Recency legitimately moved: a new day is a new snapshot identity.
            assert later.created is True

    def test_race_recovers_existing_score(
        self, session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, _ = promote(session, "puan-yaris")
            service = OpportunityScoringService(session)
            first = service.evaluate_opportunity(opportunity_id, evaluated_at=NOW)
            session.commit()

            original = OpportunityRepository.get_score_by_identity
            calls = {"count": 0}

            def racy(
                self: OpportunityRepository, *args: Any, **kwargs: Any
            ) -> OpportunityScore | None:
                calls["count"] += 1
                if calls["count"] == 1:
                    return None
                return original(self, *args, **kwargs)

            monkeypatch.setattr(OpportunityRepository, "get_score_by_identity", racy)
            recovered = service.evaluate_opportunity(opportunity_id, evaluated_at=NOW)
            assert recovered.created is False
            assert recovered.score.id == first.score.id

    def test_multi_source_opportunity_scores_diversity_and_trust(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, _ = promote(session, "cok-kaynak")
            supporting_doc = seed_document(
                session, "destek-kaynagi", trust_tier=TrustTier.REPUTABLE
            )
            supporting_decision = record_decision(
                session, supporting_doc, DuplicateDecisionOutcome.RELATED
            )
            repository = OpportunityRepository(session)
            repository.insert_research_input(
                OpportunityResearchInput(
                    opportunity_id=opportunity_id,
                    normalized_document_id=supporting_doc,
                    duplicate_decision_id=supporting_decision,
                    role=ResearchInputRole.SUPPORTING,
                    added_by=OpportunityActor.OPERATOR,
                    note=None,
                    added_at=NOW,
                )
            )
            session.commit()

            evaluation = OpportunityScoringService(session).evaluate_opportunity(
                opportunity_id, evaluated_at=NOW
            )
            session.commit()
            components = {
                row.component: row
                for row in OpportunityRepository(session).list_score_components(evaluation.score.id)
            }
            assert components[ScoreComponent.SOURCE_DIVERSITY].value == 0.6
            assert components[ScoreComponent.SOURCE_TRUST].value == round((0.5 + 0.75) / 2, 4)
            # RELATED input lowers the min duplicate contribution.
            assert components[ScoreComponent.DUPLICATE_OVERLAP_RISK].value == 0.7

    def test_override_duplicate_opportunity_scores_high_overlap_risk(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, _ = promote(
                session, "cift-puan", outcome=DuplicateDecisionOutcome.DUPLICATE
            )
            evaluation = OpportunityScoringService(session).evaluate_opportunity(
                opportunity_id, evaluated_at=NOW
            )
            session.commit()
            components = {
                row.component: row
                for row in OpportunityRepository(session).list_score_components(evaluation.score.id)
            }
            assert components[ScoreComponent.DUPLICATE_OVERLAP_RISK].value == 0.2

    def test_missing_opportunity_raises_not_found(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            with pytest.raises(OpportunityNotFoundError):
                OpportunityScoringService(session).evaluate_opportunity(uuid.uuid4())

    def test_db_enforces_unknown_never_carries_a_value(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, _ = promote(session, "kontrol")
            evaluation = OpportunityScoringService(session).evaluate_opportunity(
                opportunity_id, evaluated_at=NOW
            )
            session.commit()
            # KNOWN without a value violates the DB CHECK.
            session.add(
                OpportunityScoreComponent(
                    score_id=evaluation.score.id,
                    component=ScoreComponent.SEARCH_DEMAND,
                    availability=ComponentAvailability.KNOWN,
                    value=None,
                )
            )
            with pytest.raises(IntegrityError):
                session.flush()
            session.rollback()

    def test_repository_exposes_no_score_mutation_surface(self) -> None:
        exposed = {name for name in dir(OpportunityRepository) if not name.startswith("_")}
        assert not any("update" in name or "delete" in name for name in exposed)
