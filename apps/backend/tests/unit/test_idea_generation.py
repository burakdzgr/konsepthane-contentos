"""Model-assisted idea generation engine tests (fake provider, no network)."""

import hashlib
import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import contentos.ideas.generation as generation_module
from contentos.ai.enums import GenerationPurpose, GenerationStatus, ProviderFailureKind
from contentos.ai.fake import FakeStructuredProvider
from contentos.ai.models import AiGenerationAttempt
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
from contentos.ideas.enums import IdeaOrigin, OriginalityStatus
from contentos.ideas.errors import (
    IncompleteMaterializationError,
    InvalidGenerationAttemptError,
    InvalidIdeaInputError,
    OpportunityNotCommissionedError,
)
from contentos.ideas.generation import (
    GENERATION_INPUT_REFS_SCHEMA,
    IDEA_GENERATOR_NAME,
    IdeaGenerationEngine,
    _validate_attempt_for_opportunity,
)
from contentos.ideas.models import Idea, IdeaSelectionEvent
from contentos.ideas.policy import IdeaOriginalityPolicy
from contentos.ideas.repository import IdeaRepository
from contentos.normalization.service import NormalizationService
from contentos.opportunities.enums import (
    OpportunityActor,
    OpportunityDisposition,
    ResearchInputRole,
)
from contentos.opportunities.models import OpportunityResearchInput
from contentos.opportunities.repository import OpportunityRepository
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


def make_opportunity(
    session: Session, specs: list[tuple[str, str | None]], *, commissioned: bool = True
) -> tuple[uuid.UUID, list[uuid.UUID], list[uuid.UUID]]:
    """Seed one opportunity; returns (opportunity_id, document_ids, evidence_ids)."""
    token = uuid.uuid4().hex[:8]
    sources: dict[str, Any] = {}
    registry = SourceRegistryService(session)
    discoveries = DiscoveryService(session)
    document_ids: list[uuid.UUID] = []
    for index, (source_key, title) in enumerate(specs):
        source = sources.get(source_key)
        if source is None:
            source = registry.register_source(
                slug=f"{source_key}-{token}",
                name=f"Kaynak {source_key}",
                kind=SourceKind.MANUAL,
                base_url=f"https://{source_key}-{token}.example.test/",
                trust_tier=TrustTier.GENERAL,
            )
            sources[source_key] = source
        item = discoveries.discover_manual(
            source.id, f"https://{source_key}-{token}.example.test/haber-{index}"
        )
        discoveries.accept_item(item.id)
        body = f"<html>{source_key}-{index} govdesi</html>".encode()
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
            clean_text=f"{source_key}-{index} için uzun ve özgün araştırma metni.",
            title=title,
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

    promo = ResearchPromotionService(session).promote_research(document_ids[0])
    session.commit()
    for document_id, decision_id in zip(document_ids[1:], decisions[1:], strict=True):
        OpportunityRepository(session).insert_research_input(
            OpportunityResearchInput(
                opportunity_id=promo.opportunity_id,
                normalized_document_id=document_id,
                duplicate_decision_id=decision_id,
                role=ResearchInputRole.SUPPORTING,
                added_by=OpportunityActor.OPERATOR,
                note=None,
                added_at=NOW,
            )
        )
    session.commit()

    evidence_ids: list[uuid.UUID] = []
    for index, document_id in enumerate(document_ids):
        evidence = ResearchEvidenceService(session).record_evidence(
            document_id,
            evidence_type=EvidenceType.OBSERVATION,
            statement=f"Kaynak {index} konsept detayını belirtiyor.",
            extraction_method=ExtractionMethod.MACHINE,
            source_locator="structured_metadata.author",
        )
        evidence_ids.append(evidence.id)
    session.commit()

    if commissioned:
        opportunity = OpportunityRepository(session).get_by_id(promo.opportunity_id)
        assert opportunity is not None
        # Seeded directly: no commissioning command exists yet (a later
        # task); the engine only VALIDATES the design-§18 precondition.
        opportunity.disposition = OpportunityDisposition.COMMISSIONED
        opportunity.disposition_reason = "test komisyonu"
        opportunity.disposition_at = NOW
        opportunity.disposition_by = OpportunityActor.OPERATOR
        session.commit()
    return promo.opportunity_id, document_ids, evidence_ids


def default_opportunity(session: Session, **kwargs: Any) -> uuid.UUID:
    opportunity_id, _, _ = make_opportunity(
        session,
        [
            ("ana-kaynak", "Doğum günü partisi fikirleri ve önerileri"),
            ("destek-kaynak", "Ev partisi süsleme örnekleri"),
        ],
        **kwargs,
    )
    return opportunity_id


def planning_dims(**overrides: Any) -> dict[str, Any]:
    dims: dict[str, Any] = {
        "theme": None,
        "cake": None,
        "budget_band": None,
        "space": None,
        "preparation_time": None,
        "diy_level": None,
        "suitability": None,
        "color_palette": None,
        "decorations": None,
        "menu": None,
        "shopping_list": None,
        "practical_steps": None,
    }
    dims.update(overrides)
    return dims


def candidate(index: int, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "working_title": f"Evde balon temalı plan {index}",
        "angle": f"Aday {index}: bütçe dostu üç saatlik hazırlık akışı.",
        "audience": "Küçük çocuklu ebeveynler",
        "value_proposition": "Tek listeyle eksiksiz parti hazırlığı sağlar.",
        "rationale": "Kaynaklar genel; biz uygulanabilir zaman çizelgesi veriyoruz.",
        "content_type": "planning_guide",
        "exclusions": ["marka önerme"],
        "planning_dimensions": planning_dims(theme="balon teması"),
    }
    values.update(overrides)
    return values


def batch_payload(count: int = 3) -> dict[str, Any]:
    return {"candidates": [candidate(index) for index in range(count)]}


class TestSuccessfulGeneration:
    def test_end_to_end_with_fake_provider(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            provider = FakeStructuredProvider(payload=batch_payload(3))
            result = IdeaGenerationEngine(session).generate_candidates(
                opportunity_id, provider=provider, candidate_count=3
            )
            session.commit()

            assert result.status is GenerationStatus.SUCCEEDED
            assert result.attempt_created and result.ideas_created
            attempt = result.attempt
            assert attempt.purpose is GenerationPurpose.IDEA_CANDIDATES
            assert attempt.template_name == "idea-candidates"
            assert attempt.template_version == "1"
            refs = attempt.input_refs
            assert refs["schema"] == GENERATION_INPUT_REFS_SCHEMA
            assert refs["opportunity_id"] == str(opportunity_id)
            assert refs["generator_name"] == IDEA_GENERATOR_NAME
            assert len(refs["research_evidence_ids"]) == 2
            assert refs["originality_policy_version"] == "1"

            ideas = result.ideas
            assert len(ideas) == 3
            logical_ids = {idea.logical_idea_id for idea in ideas}
            assert len(logical_ids) == 3
            for idea in ideas:
                assert idea.origin is IdeaOrigin.MODEL_ASSISTED
                assert idea.generation_attempt_id == attempt.id
                assert idea.version == 1
                assert idea.locale == "tr-TR" and idea.market == "TR"
                assert idea.originality_status is OriginalityStatus.PASSED
                assert idea.originality_policy_snapshot["policy_name"] == "default"
                assert idea.planning_dimensions["dimensions"] == {"theme": "balon teması"}

            # Generation never selects, commissions further, or transitions.
            assert IdeaRepository(session).list_selection_events(opportunity_id) == []
            opportunity = OpportunityRepository(session).get_by_id(opportunity_id)
            assert opportunity is not None
            assert opportunity.disposition is OpportunityDisposition.COMMISSIONED
            events = WorkflowRepository(session).list_events(opportunity.work_item_id)
            assert len(events) == 1

    def test_instruction_text_is_never_persisted(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            result = IdeaGenerationEngine(session).generate_candidates(
                opportunity_id,
                provider=FakeStructuredProvider(payload=batch_payload(3)),
            )
            session.commit()
            persisted = json.dumps(
                {"refs": result.attempt.input_refs, "usage": result.attempt.usage}
            )
            assert "Konsepthane" not in persisted
            assert "MUST NOT" not in persisted

    def test_not_commissioned_opportunity_is_refused(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session, commissioned=False)
            provider = FakeStructuredProvider(payload=batch_payload(3))
            with pytest.raises(OpportunityNotCommissionedError):
                IdeaGenerationEngine(session).generate_candidates(opportunity_id, provider=provider)
            assert provider.invocations == 0

    def test_candidate_count_bounds(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            provider = FakeStructuredProvider(payload=batch_payload(3))
            engine = IdeaGenerationEngine(session)
            for bad_count in (0, 6, "3"):
                with pytest.raises(InvalidIdeaInputError):
                    engine.generate_candidates(
                        opportunity_id, provider=provider, candidate_count=bad_count
                    )
            assert provider.invocations == 0


class TestIdempotency:
    def test_exact_retry_returns_same_ideas_without_provider_call(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            provider = FakeStructuredProvider(payload=batch_payload(3))
            engine = IdeaGenerationEngine(session)
            first = engine.generate_candidates(opportunity_id, provider=provider)
            session.commit()
            second = engine.generate_candidates(opportunity_id, provider=provider)

            assert provider.invocations == 1
            assert second.attempt.id == first.attempt.id
            assert second.attempt_created is False and second.ideas_created is False
            assert {idea.id for idea in second.ideas} == {idea.id for idea in first.ideas}
            all_rows = list(session.execute(select(Idea)).scalars())
            assert len(all_rows) == 3
            assert session.execute(select(IdeaSelectionEvent)).scalar_one_or_none() is None

    def test_retry_number_produces_a_new_batch_and_keeps_the_old(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            provider = FakeStructuredProvider(payload=batch_payload(3))
            engine = IdeaGenerationEngine(session)
            first = engine.generate_candidates(opportunity_id, provider=provider)
            session.commit()
            second = engine.generate_candidates(opportunity_id, provider=provider, retry_number=1)
            session.commit()
            assert provider.invocations == 2
            assert second.attempt.id != first.attempt.id
            assert len(second.ideas) == 3
            assert {idea.id for idea in second.ideas}.isdisjoint({idea.id for idea in first.ideas})
            assert len(list(session.execute(select(Idea)).scalars())) == 6

    def test_policy_change_changes_generation_identity(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            provider = FakeStructuredProvider(payload=batch_payload(3))
            engine = IdeaGenerationEngine(session)
            first = engine.generate_candidates(opportunity_id, provider=provider)
            session.commit()
            stricter = IdeaOriginalityPolicy(
                name="default",
                version="1-strict-test",
                min_distinct_sources=2,
                title_similarity_failure_threshold=0.80,
            )
            second = engine.generate_candidates(opportunity_id, provider=provider, policy=stricter)
            session.commit()
            assert second.attempt.id != first.attempt.id
            assert provider.invocations == 2
            assert second.ideas[0].originality_policy_snapshot["policy_version"] == (
                "1-strict-test"
            )

    def test_template_version_change_changes_identity(
        self,
        session_factory: sessionmaker[Session],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            provider = FakeStructuredProvider(payload=batch_payload(3))
            engine = IdeaGenerationEngine(session)
            first = engine.generate_candidates(opportunity_id, provider=provider)
            session.commit()
            monkeypatch.setattr(generation_module, "IDEA_TEMPLATE_VERSION", "2")
            second = engine.generate_candidates(opportunity_id, provider=provider)
            session.commit()
            assert second.attempt.id != first.attempt.id
            assert second.attempt.template_version == "2"

    def test_provider_identity_change_changes_identity(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        from contentos.ai.dto import ProviderIdentity

        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            engine = IdeaGenerationEngine(session)
            provider_a = FakeStructuredProvider(payload=batch_payload(3))
            provider_b = FakeStructuredProvider(
                payload=batch_payload(3),
                declared_identity=ProviderIdentity(
                    provider="fake", model_name="another-test-model", model_version=None
                ),
            )
            first = engine.generate_candidates(opportunity_id, provider=provider_a)
            session.commit()
            second = engine.generate_candidates(opportunity_id, provider=provider_b)
            session.commit()
            assert second.attempt.id != first.attempt.id
            assert second.attempt.model_name == "another-test-model"
            assert second.attempt.model_version is None


class TestValidationOutcomes:
    def test_fake_ugc_candidate_fails_the_whole_batch(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            payload = batch_payload(3)
            payload["candidates"][1]["angle"] = (
                "Gerçek kullanıcı yorumları ile güçlendirilmiş öneriler."
            )
            result = IdeaGenerationEngine(session).generate_candidates(
                opportunity_id, provider=FakeStructuredProvider(payload=payload)
            )
            session.commit()
            assert result.status is GenerationStatus.VALIDATION_FAILED
            assert result.attempt.error_class == "domain_validation"
            assert result.ideas == []
            assert session.execute(select(Idea)).scalar_one_or_none() is None

    def test_candidate_count_mismatch_fails_validation(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            result = IdeaGenerationEngine(session).generate_candidates(
                opportunity_id,
                provider=FakeStructuredProvider(payload=batch_payload(2)),
                candidate_count=3,
            )
            assert result.status is GenerationStatus.VALIDATION_FAILED
            assert result.ideas == []

    def test_exact_duplicate_candidates_fail_validation(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            payload = {"candidates": [candidate(1), candidate(1), candidate(2)]}
            result = IdeaGenerationEngine(session).generate_candidates(
                opportunity_id, provider=FakeStructuredProvider(payload=payload)
            )
            assert result.status is GenerationStatus.VALIDATION_FAILED
            assert result.ideas == []

    def test_schema_invalid_payload(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            result = IdeaGenerationEngine(session).generate_candidates(
                opportunity_id,
                provider=FakeStructuredProvider(payload={"candidates": "not-a-list"}),
            )
            session.commit()
            assert result.status is GenerationStatus.VALIDATION_FAILED
            assert result.attempt.error_class == "schema_validation"
            assert result.ideas == []

    def test_near_copy_title_persists_as_failed_originality(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            payload = batch_payload(3)
            payload["candidates"][0]["working_title"] = "Doğum günü partisi fikirleri ve önerileri"
            result = IdeaGenerationEngine(session).generate_candidates(
                opportunity_id, provider=FakeStructuredProvider(payload=payload)
            )
            session.commit()
            # Attempt SUCCEEDED; the near-copy is recorded, never hidden.
            assert result.status is GenerationStatus.SUCCEEDED
            assert len(result.ideas) == 3
            statuses = [idea.originality_status for idea in result.ideas]
            assert statuses.count(OriginalityStatus.FAILED) == 1
            failed = next(
                idea for idea in result.ideas if idea.originality_status is OriginalityStatus.FAILED
            )
            title_check = failed.originality_detail["checks"]["title_similarity"]
            assert title_check["status"] == "failed"

    def test_single_source_persists_as_failed_originality(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, _, _ = make_opportunity(
                session, [("tek-kaynak", "Parti fikirleri yazısı")]
            )
            result = IdeaGenerationEngine(session).generate_candidates(
                opportunity_id, provider=FakeStructuredProvider(payload=batch_payload(3))
            )
            session.commit()
            assert result.status is GenerationStatus.SUCCEEDED
            for idea in result.ideas:
                assert idea.originality_status is OriginalityStatus.FAILED
                source_check = idea.originality_detail["checks"]["source_diversity"]
                assert source_check == {
                    "status": "failed",
                    "distinct_sources": 1,
                    "required": 2,
                }

    @pytest.mark.parametrize(
        ("kind", "status"),
        [
            (ProviderFailureKind.PROVIDER_ERROR, GenerationStatus.PROVIDER_ERROR),
            (ProviderFailureKind.TIMEOUT, GenerationStatus.TIMEOUT),
            (ProviderFailureKind.CANCELLED, GenerationStatus.CANCELLED),
        ],
    )
    def test_provider_failures_produce_durable_attempt_and_zero_ideas(
        self,
        session_factory: sessionmaker[Session],
        kind: ProviderFailureKind,
        status: GenerationStatus,
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            result = IdeaGenerationEngine(session).generate_candidates(
                opportunity_id,
                provider=FakeStructuredProvider(failure=kind, failure_class="upstream"),
            )
            session.commit()
            assert result.status is status
            assert result.ideas == []
            assert session.execute(select(Idea)).scalar_one_or_none() is None
            stored = session.execute(select(AiGenerationAttempt)).scalar_one()
            assert stored.status is status


class TestAttemptValidation:
    def test_wrong_purpose_status_or_refs_are_refused(self) -> None:
        opportunity_id = uuid.uuid4()
        good_refs = {
            "schema": GENERATION_INPUT_REFS_SCHEMA,
            "opportunity_id": str(opportunity_id),
            "generator_name": IDEA_GENERATOR_NAME,
        }

        def attempt(**overrides: Any) -> AiGenerationAttempt:
            values: dict[str, Any] = {
                "purpose": GenerationPurpose.IDEA_CANDIDATES,
                "status": GenerationStatus.SUCCEEDED,
                "input_refs": good_refs,
            }
            values.update(overrides)
            return AiGenerationAttempt(
                purpose=values["purpose"],
                provider="fake",
                model_name="m",
                model_version=None,
                schema_name="s",
                schema_version="1",
                template_name="t",
                template_version="1",
                input_refs=values["input_refs"],
                input_hash="0" * 64,
                attempt_identity_hash=uuid.uuid4().hex + uuid.uuid4().hex,
                status=values["status"],
                error_class=(None if values["status"] is GenerationStatus.SUCCEEDED else "x"),
                retry_number=0,
                usage={},
            )

        _validate_attempt_for_opportunity(attempt(), opportunity_id)
        with pytest.raises(InvalidGenerationAttemptError, match="purpose"):
            _validate_attempt_for_opportunity(
                attempt(purpose=GenerationPurpose.BRIEF_COMPOSITION), opportunity_id
            )
        with pytest.raises(InvalidGenerationAttemptError, match="SUCCEEDED"):
            _validate_attempt_for_opportunity(
                attempt(status=GenerationStatus.VALIDATION_FAILED), opportunity_id
            )
        with pytest.raises(InvalidGenerationAttemptError, match="provenance"):
            _validate_attempt_for_opportunity(attempt(), uuid.uuid4())
        with pytest.raises(InvalidGenerationAttemptError, match="provenance"):
            _validate_attempt_for_opportunity(
                attempt(input_refs={"schema": "other"}), opportunity_id
            )

    def test_pathological_reused_attempt_without_ideas(
        self,
        session_factory: sessionmaker[Session],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            provider = FakeStructuredProvider(payload=batch_payload(3))
            engine = IdeaGenerationEngine(session)

            # Seed the pathological state: a committed SUCCEEDED attempt
            # whose materialization was lost before insert.
            def explode(*args: Any, **kwargs: Any) -> Any:
                raise RuntimeError("materialization interrupted")

            monkeypatch.setattr(IdeaGenerationEngine, "_materialize", explode)
            with pytest.raises(RuntimeError):
                engine.generate_candidates(opportunity_id, provider=provider)
            session.commit()  # the attempt row survives; no ideas exist
            monkeypatch.undo()
            assert provider.invocations == 1
            assert session.execute(select(Idea)).scalar_one_or_none() is None

            # The exact identity must NOT re-invoke the provider or invent
            # candidates: typed incomplete-materialization condition.
            with pytest.raises(IncompleteMaterializationError):
                engine.generate_candidates(opportunity_id, provider=provider)
            assert provider.invocations == 1
            assert len(list(session.execute(select(AiGenerationAttempt)).scalars())) == 1

            # An explicit new retry number proceeds normally.
            recovered = engine.generate_candidates(
                opportunity_id, provider=provider, retry_number=1
            )
            session.commit()
            assert recovered.status is GenerationStatus.SUCCEEDED
            assert len(recovered.ideas) == 3
            assert provider.invocations == 2

    def test_caller_owns_commit_atomically(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            IdeaGenerationEngine(session).generate_candidates(
                opportunity_id, provider=FakeStructuredProvider(payload=batch_payload(3))
            )
            session.rollback()
        with open_session(session_factory) as session:
            # Attempt and ideas disappear together on rollback.
            assert session.execute(select(AiGenerationAttempt)).scalar_one_or_none() is None
            assert session.execute(select(Idea)).scalar_one_or_none() is None
