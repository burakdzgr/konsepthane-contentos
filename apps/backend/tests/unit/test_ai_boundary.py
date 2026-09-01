"""Provider-neutral structured-generation boundary tests (no network)."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from contentos.ai.dto import (
    GenerationRequest,
    GenerationUsage,
    ProviderIdentity,
    ProviderResult,
)
from contentos.ai.enums import GenerationPurpose, GenerationStatus, ProviderFailureKind
from contentos.ai.errors import (
    InvalidGenerationRequestError,
    InvalidProviderIdentityError,
    InvalidSchemaSpecError,
    InvalidUsageError,
)
from contentos.ai.fake import (
    FAKE_MODEL_NAME,
    FAKE_MODEL_VERSION,
    FAKE_PROVIDER_NAME,
    FakeStructuredProvider,
)
from contentos.ai.hashing import attempt_identity_hash, generation_input_hash
from contentos.ai.models import AiGenerationAttempt
from contentos.ai.repository import AiGenerationAttemptRepository
from contentos.ai.service import (
    PROVIDER_IDENTITY_MISMATCH_ERROR_CLASS,
    StructuredGenerationService,
)
from contentos.ai.validation import StructuredOutputSpec
from contentos.db.base import Base
from contentos.research.models import ResearchEvidence


class OutlineTestPayload(BaseModel):
    """Tiny test-only structured output schema (NOT a real domain schema)."""

    title: str = Field(min_length=1, max_length=200)
    items: list[str] = Field(default_factory=list, max_length=20)


TEST_SPEC: StructuredOutputSpec[OutlineTestPayload] = StructuredOutputSpec(
    schema_name="outline-test",
    schema_version="1",
    model_type=OutlineTestPayload,
)

VALID_PAYLOAD = {"title": "Deterministik başlık", "items": ["bir", "iki"]}


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


def make_request(**overrides: Any) -> GenerationRequest:
    values: dict[str, Any] = {
        "purpose": GenerationPurpose.IDEA_CANDIDATES,
        "schema_name": "outline-test",
        "schema_version": "1",
        "template_name": "outline-template",
        "template_version": "1",
        "input_refs": {"opportunity_score_id": "score-1", "policy_version": "1"},
        "input_projection": {"topic": "doğum günü partisi", "signals": ["a", "b"]},
        "generation_bounds": {"max_items": 5},
        "retry_number": 0,
    }
    values.update(overrides)
    return GenerationRequest(**values)


class TestSuccess:
    def test_valid_generation_succeeds_with_safe_metadata_only(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            provider = FakeStructuredProvider(
                payload=VALID_PAYLOAD,
                usage=GenerationUsage(input_tokens=100, output_tokens=20, total_tokens=120),
            )
            execution = StructuredGenerationService(session).execute(
                make_request(), TEST_SPEC, provider
            )
            session.commit()

            assert execution.created is True
            assert execution.status is GenerationStatus.SUCCEEDED
            assert execution.payload is not None
            assert execution.payload.title == "Deterministik başlık"
            attempt = execution.attempt
            assert attempt.provider == FAKE_PROVIDER_NAME
            assert attempt.model_name == FAKE_MODEL_NAME
            assert attempt.model_version == FAKE_MODEL_VERSION
            assert attempt.status is GenerationStatus.SUCCEEDED
            assert attempt.error_class is None
            assert attempt.usage == {
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
                "finish_reason": "stop",
            }
            assert attempt.input_refs == {
                "opportunity_score_id": "score-1",
                "policy_version": "1",
            }
            assert len(attempt.input_hash) == 64
            assert len(attempt.attempt_identity_hash) == 64
            # SUCCEEDED means schema+domain validity only: no domain
            # artifact, no workflow, no selection was created anywhere.
            assert provider.invocations == 1

    def test_cost_stays_absent_unless_configured(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            provider = FakeStructuredProvider(payload=VALID_PAYLOAD)
            execution = StructuredGenerationService(session).execute(
                make_request(), TEST_SPEC, provider
            )
            assert "cost_amount" not in execution.attempt.usage
            assert "cost_currency" not in execution.attempt.usage


class TestValidationFailures:
    def test_schema_invalid_output_is_a_durable_failed_attempt(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            provider = FakeStructuredProvider(payload={"title": "", "items": "not-a-list"})
            execution = StructuredGenerationService(session).execute(
                make_request(), TEST_SPEC, provider
            )
            session.commit()

            assert execution.status is GenerationStatus.VALIDATION_FAILED
            assert execution.payload is None
            attempt = execution.attempt
            assert attempt.error_class == "schema_validation"
            # The rejected raw payload is never persisted anywhere.
            stored = session.execute(select(AiGenerationAttempt)).scalar_one()
            for value in (stored.input_refs, stored.usage):
                assert "not-a-list" not in str(value)

    def test_domain_validation_failure(self, session_factory: sessionmaker[Session]) -> None:
        def reject_short_titles(payload: OutlineTestPayload) -> str | None:
            return "title_too_generic" if len(payload.title) < 30 else None

        spec = StructuredOutputSpec(
            schema_name="outline-test",
            schema_version="1",
            model_type=OutlineTestPayload,
            domain_validator=reject_short_titles,
        )
        with open_session(session_factory) as session:
            provider = FakeStructuredProvider(payload=VALID_PAYLOAD)
            execution = StructuredGenerationService(session).execute(make_request(), spec, provider)
            session.commit()

            assert execution.status is GenerationStatus.VALIDATION_FAILED
            assert execution.attempt.error_class == "domain_validation"
            assert execution.payload is None
            # Durable after the caller's commit.
            with open_session(session_factory) as check:
                stored = check.execute(select(AiGenerationAttempt)).scalar_one()
                assert stored.status is GenerationStatus.VALIDATION_FAILED


class TestProviderFailures:
    @pytest.mark.parametrize(
        ("kind", "status"),
        [
            (ProviderFailureKind.PROVIDER_ERROR, GenerationStatus.PROVIDER_ERROR),
            (ProviderFailureKind.TIMEOUT, GenerationStatus.TIMEOUT),
            (ProviderFailureKind.CANCELLED, GenerationStatus.CANCELLED),
        ],
    )
    def test_provider_failures_become_attempt_facts(
        self,
        session_factory: sessionmaker[Session],
        kind: ProviderFailureKind,
        status: GenerationStatus,
    ) -> None:
        with open_session(session_factory) as session:
            provider = FakeStructuredProvider(failure=kind, failure_class="upstream_unavailable")
            execution = StructuredGenerationService(session).execute(
                make_request(), TEST_SPEC, provider
            )
            session.commit()
            assert execution.status is status
            assert execution.attempt.error_class == "upstream_unavailable"
            assert execution.payload is None

    def test_provider_identity_mismatch_is_detected(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            provider = FakeStructuredProvider(
                payload=VALID_PAYLOAD,
                claimed_identity=ProviderIdentity(
                    provider="fake-b", model_name="other-model", model_version="9"
                ),
            )
            execution = StructuredGenerationService(session).execute(
                make_request(), TEST_SPEC, provider
            )
            assert execution.status is GenerationStatus.PROVIDER_ERROR
            assert execution.attempt.error_class == PROVIDER_IDENTITY_MISMATCH_ERROR_CLASS
            # The DECLARED identity is what gets recorded.
            assert execution.attempt.provider == FAKE_PROVIDER_NAME


class TestIdempotency:
    def test_exact_retry_reuses_attempt_without_second_invocation(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            provider = FakeStructuredProvider(payload=VALID_PAYLOAD)
            service = StructuredGenerationService(session)
            first = service.execute(make_request(), TEST_SPEC, provider)
            session.commit()
            second = service.execute(make_request(), TEST_SPEC, provider)

            assert first.created is True
            assert second.created is False
            assert second.attempt.id == first.attempt.id
            # Raw output is never persisted, so a reused attempt carries no
            # payload: engines replay from their own artifact tables.
            assert second.payload is None
            assert provider.invocations == 1
            rows = list(session.execute(select(AiGenerationAttempt)).scalars())
            assert len(rows) == 1

    def test_failed_attempts_are_idempotent_too(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            provider = FakeStructuredProvider(
                failure=ProviderFailureKind.TIMEOUT, failure_class="deadline"
            )
            service = StructuredGenerationService(session)
            first = service.execute(make_request(), TEST_SPEC, provider)
            session.commit()
            second = service.execute(make_request(), TEST_SPEC, provider)
            assert second.created is False
            assert second.attempt.id == first.attempt.id
            assert provider.invocations == 1

    def test_changed_retry_number_creates_new_attempt(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            provider = FakeStructuredProvider(payload=VALID_PAYLOAD)
            service = StructuredGenerationService(session)
            first = service.execute(make_request(retry_number=0), TEST_SPEC, provider)
            session.commit()
            second = service.execute(make_request(retry_number=1), TEST_SPEC, provider)
            session.commit()
            assert second.created is True
            assert second.attempt.id != first.attempt.id
            assert provider.invocations == 2
            rows = list(session.execute(select(AiGenerationAttempt)).scalars())
            assert len(rows) == 2

    def test_different_input_refs_change_identity_despite_same_projection(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            provider = FakeStructuredProvider(payload=VALID_PAYLOAD)
            service = StructuredGenerationService(session)
            first = service.execute(
                make_request(input_refs={"opportunity_score_id": "score-1"}),
                TEST_SPEC,
                provider,
            )
            session.commit()
            second = service.execute(
                make_request(input_refs={"opportunity_score_id": "score-2"}),
                TEST_SPEC,
                provider,
            )
            session.commit()
            assert second.created is True
            assert second.attempt.input_hash != first.attempt.input_hash
            assert second.attempt.attempt_identity_hash != first.attempt.attempt_identity_hash

    def test_race_recovers_concurrent_winner(
        self, session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with open_session(session_factory) as session:
            provider = FakeStructuredProvider(payload=VALID_PAYLOAD)
            service = StructuredGenerationService(session)
            first = service.execute(make_request(), TEST_SPEC, provider)
            session.commit()

            original = AiGenerationAttemptRepository.get_by_identity_hash
            calls = {"count": 0}

            def racy(self: AiGenerationAttemptRepository, value: str) -> AiGenerationAttempt | None:
                calls["count"] += 1
                if calls["count"] == 1:
                    return None
                return original(self, value)

            monkeypatch.setattr(AiGenerationAttemptRepository, "get_by_identity_hash", racy)
            recovered = service.execute(make_request(), TEST_SPEC, provider)
            assert recovered.created is False
            assert recovered.attempt.id == first.attempt.id


class TestHashing:
    def test_dict_key_order_never_matters(self) -> None:
        left = generation_input_hash(
            input_refs={"a": "1", "b": "2"},
            input_projection={"x": 1, "y": 2},
            generation_bounds={},
        )
        right = generation_input_hash(
            input_refs={"b": "2", "a": "1"},
            input_projection={"y": 2, "x": 1},
            generation_bounds={},
        )
        assert left == right

    def test_list_order_is_semantic(self) -> None:
        left = generation_input_hash(
            input_refs={}, input_projection={"items": ["a", "b"]}, generation_bounds={}
        )
        right = generation_input_hash(
            input_refs={}, input_projection={"items": ["b", "a"]}, generation_bounds={}
        )
        assert left != right

    def test_model_version_null_is_explicit_in_identity(self) -> None:
        base = {
            "purpose": "idea_candidates",
            "input_hash": "0" * 64,
            "provider": "fake",
            "model_name": "m",
            "schema_name": "s",
            "schema_version": "1",
            "template_name": "t",
            "template_version": "1",
            "retry_number": 0,
        }
        with_null = attempt_identity_hash(model_version=None, **base)
        with_version = attempt_identity_hash(model_version="1", **base)
        assert with_null != with_version
        assert with_null == attempt_identity_hash(model_version=None, **base)


class TestContractValidation:
    def test_schema_spec_request_mismatch_rejected_before_invocation(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            provider = FakeStructuredProvider(payload=VALID_PAYLOAD)
            with pytest.raises(InvalidSchemaSpecError):
                StructuredGenerationService(session).execute(
                    make_request(schema_version="2"), TEST_SPEC, provider
                )
            assert provider.invocations == 0
            assert session.execute(select(AiGenerationAttempt)).scalar_one_or_none() is None

    def test_request_validation(self) -> None:
        for overrides in (
            {"schema_name": "  "},
            {"template_version": ""},
            {"retry_number": -1},
            {"retry_number": "1"},
            {"input_refs": {"deep": {"deeper": {"deepest": {"too-deep": "x"}}}}},
            {"input_refs": {"big": "x" * 201}},
            {"input_refs": {"nan": float("nan")}},
            {"input_projection": {"inf": float("inf")}},
            {"input_projection": {"objects": [object()]}},
            {"generation_bounds": {"max_items": 0}},
            {"generation_bounds": {"max_items": "5"}},
        ):
            with pytest.raises(InvalidGenerationRequestError):
                make_request(**overrides)

    def test_provider_identity_validation(self) -> None:
        for kwargs in (
            {"provider": " ", "model_name": "m", "model_version": None},
            {"provider": "p", "model_name": "", "model_version": None},
            {"provider": "p", "model_name": "m", "model_version": "  "},
            {"provider": " padded ", "model_name": "m", "model_version": None},
        ):
            with pytest.raises(InvalidProviderIdentityError):
                ProviderIdentity(**kwargs)

    def test_usage_validation(self) -> None:
        for kwargs in (
            {"input_tokens": -1},
            {"latency_ms": -0.5},
            {"latency_ms": float("nan")},
            {"cost_amount": 1.0},
            {"cost_amount": float("inf"), "cost_currency": "USD"},
            {"cost_amount": 1.0, "cost_currency": "usd"},
        ):
            with pytest.raises(InvalidUsageError):
                GenerationUsage(**kwargs)
        absent = GenerationUsage()
        assert absent.to_persisted() == {}

    def test_provider_result_rejects_non_object_payload(self) -> None:
        with pytest.raises(InvalidGenerationRequestError):
            ProviderResult(
                payload=["not", "an", "object"],  # type: ignore[arg-type]
                provider="fake",
                model_name="m",
                model_version=None,
            )


class TestBoundaryIsolation:
    def test_repository_exposes_no_update_or_delete_surface(self) -> None:
        exposed = {name for name in dir(AiGenerationAttemptRepository) if not name.startswith("_")}
        assert not any("update" in name or "delete" in name for name in exposed)
        assert not any("latest" in name or "current" in name for name in exposed)

    def test_attempt_table_is_not_a_payload_archive(self) -> None:
        columns = {column.name for column in AiGenerationAttempt.__table__.columns}
        for forbidden in (
            "raw_response",
            "raw_output",
            "prompt",
            "messages",
            "completion_text",
            "provider_payload",
            "api_key",
            "output",
        ):
            assert forbidden not in columns

    def test_ai_output_is_never_research_evidence(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        # No attempt FK exists in research_evidence, and running the
        # boundary creates no evidence rows.
        research_columns = {column.name for column in ResearchEvidence.__table__.columns}
        assert not any("attempt" in name or "generation" in name for name in research_columns)
        with open_session(session_factory) as session:
            StructuredGenerationService(session).execute(
                make_request(), TEST_SPEC, FakeStructuredProvider(payload=VALID_PAYLOAD)
            )
            session.commit()
            assert session.execute(select(ResearchEvidence)).scalar_one_or_none() is None

    def test_no_workflow_or_domain_side_effects(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        from contentos.ideas.models import Idea, IdeaSelectionEvent
        from contentos.opportunities.models import EditorialOpportunity
        from contentos.workflow.models import EditorialWorkflowEvent, EditorialWorkItem

        with open_session(session_factory) as session:
            StructuredGenerationService(session).execute(
                make_request(), TEST_SPEC, FakeStructuredProvider(payload=VALID_PAYLOAD)
            )
            session.commit()
            for model in (
                EditorialWorkItem,
                EditorialWorkflowEvent,
                EditorialOpportunity,
                Idea,
                IdeaSelectionEvent,
            ):
                assert session.execute(select(model)).scalar_one_or_none() is None

    def test_caller_owns_commit(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            StructuredGenerationService(session).execute(
                make_request(), TEST_SPEC, FakeStructuredProvider(payload=VALID_PAYLOAD)
            )
            session.rollback()
        with open_session(session_factory) as session:
            assert session.execute(select(AiGenerationAttempt)).scalar_one_or_none() is None

    def test_fake_provider_is_deterministic(self) -> None:
        provider = FakeStructuredProvider(payload=VALID_PAYLOAD)
        first = provider.generate(make_request())
        second = provider.generate(make_request())
        assert first.payload == second.payload
        assert first.provider == FAKE_PROVIDER_NAME
        assert provider.invocations == 2
        # Mutating a returned payload never leaks into later calls.
        first.payload["title"] = "tampered"
        assert provider.generate(make_request()).payload == VALID_PAYLOAD
