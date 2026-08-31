"""Deterministic duplicate engine and immutable persistence contract tests."""

import hashlib
import uuid
from collections.abc import Iterator
from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from contentos.db.base import Base
from contentos.discovery.service import DiscoveryService
from contentos.duplicates.engine import (
    DUPLICATE_ENGINE_NAME,
    DUPLICATE_ENGINE_VERSION,
    DuplicateEngineV1,
)
from contentos.duplicates.enums import DuplicateDecisionOutcome
from contentos.duplicates.models import DuplicateDecision
from contentos.duplicates.repository import (
    DuplicateCandidateRepository,
    DuplicateDecisionRepository,
)
from contentos.duplicates.service import (
    DuplicateDecisionConflictError,
    DuplicateDecisionPersistenceError,
    DuplicateDecisionService,
    DuplicateDocumentNotEligibleError,
    DuplicateDocumentNotFoundError,
)
from contentos.duplicates.signals import (
    TITLE_SIMILARITY_METRIC,
    V1_THRESHOLDS,
    ComparisonDocument,
    DuplicateEvaluation,
    DuplicateSignals,
    DuplicateThresholds,
    lexical_similarity,
    title_similarity,
)
from contentos.fetching.models import (
    FetchOutcome,
    FetchResult,
    RetryClassification,
    RobotsDecision,
)
from contentos.fetching.snapshot_service import FetchSnapshotService
from contentos.normalization.enums import NormalizationFailureCode, NormalizationStatus
from contentos.normalization.models import NormalizedDocument
from contentos.normalization.service import NormalizationService
from contentos.sources.enums import DiscoveryStrategy, SourceKind, TrustTier
from contentos.sources.service import SourceRegistryService

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db_session:
        yield db_session
    engine.dispose()


def create_document(
    session: Session,
    suffix: str,
    *,
    clean_text: str,
    title: str | None = None,
    canonical_url: str | None = None,
    final_url: str | None = None,
    raw_body: bytes | None = None,
    failed: bool = False,
) -> NormalizedDocument:
    source = SourceRegistryService(session).register_source(
        slug=f"source-{suffix}",
        name=f"Source {suffix}",
        kind=SourceKind.MANUAL,
        base_url=f"https://source-{suffix}.example.test/",
        trust_tier=TrustTier.GENERAL,
        discovery_strategy=DiscoveryStrategy.MANUAL,
    )
    discoveries = DiscoveryService(session)
    item = discoveries.discover_manual(
        source.id,
        canonical_url or f"https://content-{suffix}.example.test/article",
    )
    discoveries.accept_item(item.id)
    body = raw_body if raw_body is not None else f"raw-{suffix}".encode()
    snapshot = FetchSnapshotService(session).record_fetch_result(
        item.id,
        FetchResult(
            requested_url=item.canonical_url,
            outcome=FetchOutcome.SUCCESS,
            retry=RetryClassification.NOT_APPLICABLE,
            robots_decision=RobotsDecision.ALLOWED,
            fetched_at=NOW,
            duration_ms=2.0,
            final_url=final_url or f"https://final-{suffix}.example.test/article",
            status_code=200,
            content_type="text/plain; charset=utf-8",
            body=body,
        ),
        raw_payload_ref=f"memory:sha256:{hashlib.sha256(body).hexdigest()}",
    )
    normalization = NormalizationService(session)
    if failed:
        return normalization.record_failure(
            snapshot.id,
            extractor_name="text-basic",
            extractor_version="1",
            parser_version="python-text-v1",
            failure_code=NormalizationFailureCode.PARSE_ERROR,
            failure_detail="synthetic failure",
        )
    return normalization.record_success(
        snapshot.id,
        extractor_name="text-basic",
        extractor_version="1",
        parser_version="python-text-v1",
        clean_text=clean_text,
        title=title,
    )


def comparison(
    suffix: str,
    *,
    text: str,
    title: str | None = None,
    canonical_url: str | None = None,
    final_url: str | None = None,
    raw_hash: str | None = None,
    fingerprint: str | None = None,
) -> ComparisonDocument:
    return ComparisonDocument(
        normalized_document_id=uuid.uuid5(uuid.NAMESPACE_URL, f"document-{suffix}"),
        fetch_snapshot_id=uuid.uuid5(uuid.NAMESPACE_URL, f"snapshot-{suffix}"),
        discovery_item_id=uuid.uuid5(uuid.NAMESPACE_URL, f"discovery-{suffix}"),
        normalization_status=NormalizationStatus.SUCCEEDED,
        canonical_url=canonical_url or f"https://{suffix}.example.test/article",
        final_url=final_url or f"https://{suffix}.example.test/final",
        raw_body_sha256=raw_hash or hashlib.sha256(f"raw-{suffix}".encode()).hexdigest(),
        content_fingerprint=fingerprint or hashlib.sha256(text.encode()).hexdigest(),
        title=title,
        clean_text=text,
    )


def decision_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(DuplicateDecision)) or 0


class StaticEngine:
    name = DUPLICATE_ENGINE_NAME
    version = DUPLICATE_ENGINE_VERSION
    thresholds = V1_THRESHOLDS

    def __init__(self, decision: DuplicateDecisionOutcome) -> None:
        self.decision = decision

    def evaluate(
        self,
        target: ComparisonDocument,
        candidates: tuple[ComparisonDocument, ...],
    ) -> DuplicateEvaluation:
        del target, candidates
        return DuplicateEvaluation(
            decision=self.decision,
            signals=DuplicateSignals(
                candidate_count=0,
                exact_canonical_url_matches=0,
                exact_final_url_matches=0,
                exact_raw_body_matches=0,
                exact_content_fingerprint_matches=0,
                highest_title_similarity=0.0,
                highest_lexical_similarity=0.0,
            ),
            thresholds=self.thresholds,
            matches=(),
            rationale_codes=("static_test_result",),
        )


class TestModelAndRepositoryContract:
    def test_model_has_exact_append_only_shape(self) -> None:
        assert set(DuplicateDecision.__table__.columns.keys()) == {
            "id",
            "normalized_document_id",
            "engine_name",
            "engine_version",
            "decision",
            "signals",
            "thresholds",
            "matches",
            "rationale_codes",
            "evaluated_at",
            "created_at",
        }
        assert "updated_at" not in DuplicateDecision.__table__.columns
        foreign_key = next(iter(DuplicateDecision.__table__.foreign_keys))
        assert foreign_key.target_fullname == "normalized_documents.id"
        assert foreign_key.ondelete == "RESTRICT"
        assert any(
            constraint.name == "uq_duplicate_decisions_document_engine"
            for constraint in DuplicateDecision.__table__.constraints
        )

    def test_outcomes_and_engine_identity_are_frozen(self) -> None:
        assert [outcome.value for outcome in DuplicateDecisionOutcome] == [
            "unique",
            "related",
            "update_existing",
            "duplicate",
            "reject",
        ]
        assert (DUPLICATE_ENGINE_NAME, DUPLICATE_ENGINE_VERSION) == (
            "duplicate-engine",
            "1",
        )
        assert V1_THRESHOLDS == DuplicateThresholds(
            max_candidate_documents=200,
            max_lexical_text_chars=100_000,
            max_tokens=10_000,
            max_stored_matches=10,
            max_rationale_codes=20,
            duplicate_title_similarity=0.92,
            duplicate_lexical_similarity=0.85,
            related_title_similarity=0.65,
            related_lexical_similarity=0.45,
            related_title_lexical_floor=0.25,
        )
        with pytest.raises(FrozenInstanceError):
            V1_THRESHOLDS.max_tokens = 1  # type: ignore[misc]

    def test_repository_exposes_append_and_read_only_operations(self, session: Session) -> None:
        repository = DuplicateDecisionRepository(session)
        assert callable(repository.add)
        assert callable(repository.get_by_id)
        assert callable(repository.get_by_document_and_engine)
        assert callable(repository.list_for_document)
        assert not hasattr(repository, "update")
        assert not hasattr(repository, "delete")
        assert not hasattr(repository, "commit")


class TestSimilarityMetrics:
    def test_title_similarity_normalizes_unicode_case_and_whitespace(self) -> None:
        assert title_similarity("  İSTANBUL   Düğünleri ", "istanbul düğünleri") < 1.0
        assert title_similarity("  İSTANBUL   Düğünleri ", "İstanbul düğünleri") == 1.0
        assert TITLE_SIMILARITY_METRIC == "unicode-sequence-matcher-v1"

    def test_lexical_similarity_is_unicode_safe_and_bounded(self) -> None:
        assert (
            lexical_similarity(
                "İSTANBUL düğün fikirleri zarif masa",
                "İstanbul DÜĞÜN fikirleri zarif masa",
                max_chars=100,
                max_tokens=100,
            )
            == 1.0
        )
        assert lexical_similarity("koşmak", "kosmak", max_chars=100, max_tokens=100) == 0.0
        assert lexical_similarity("kitaplar", "kitap", max_chars=100, max_tokens=100) == 0.0
        assert (
            lexical_similarity(
                "same ignored-tail-a",
                "same ignored-tail-b",
                max_chars=4,
                max_tokens=1,
            )
            == 1.0
        )


class TestEnginePolicy:
    def test_exact_fingerprint_overrides_fuzzy_signals(self) -> None:
        target = comparison("target", text="one two three", fingerprint="a" * 64)
        candidate = comparison(
            "candidate",
            text="unrelated words only",
            fingerprint="a" * 64,
        )

        evaluation = DuplicateEngineV1().evaluate(target, (candidate,))

        assert evaluation.decision is DuplicateDecisionOutcome.DUPLICATE
        assert evaluation.rationale_codes == ("exact_content_fingerprint",)
        assert evaluation.matches[0].exact_content_fingerprint is True

    def test_exact_raw_body_is_duplicate_even_when_normalized_content_differs(self) -> None:
        raw_hash = "b" * 64
        target = comparison("target", text="first extraction", raw_hash=raw_hash)
        candidate = comparison("candidate", text="different extraction", raw_hash=raw_hash)

        evaluation = DuplicateEngineV1().evaluate(target, (candidate,))

        assert evaluation.decision is DuplicateDecisionOutcome.DUPLICATE
        assert evaluation.rationale_codes == ("exact_raw_body",)

    @pytest.mark.parametrize("identity", ["canonical", "final"])
    def test_same_resource_with_changed_content_is_update_existing(self, identity: str) -> None:
        shared_canonical = "https://shared.example.test/article"
        shared_final = "https://shared.example.test/final"
        target = comparison(
            "target",
            text="new changed material",
            canonical_url=shared_canonical if identity == "canonical" else None,
            final_url=shared_final if identity == "final" else None,
        )
        candidate = comparison(
            "candidate",
            text="old original material",
            canonical_url=shared_canonical if identity == "canonical" else None,
            final_url=shared_final if identity == "final" else None,
        )

        evaluation = DuplicateEngineV1().evaluate(target, (candidate,))

        assert evaluation.decision is DuplicateDecisionOutcome.UPDATE_EXISTING
        assert "changed_content" in evaluation.rationale_codes[0]

    def test_high_moderate_and_weak_similarity_bands(self) -> None:
        engine = DuplicateEngineV1()
        target = comparison(
            "target",
            title="Zarif İstanbul Düğün Masası Fikirleri",
            text="zarif istanbul düğün masa çiçek mum altın davetli fikir",
        )
        high = comparison(
            "high",
            title="Zarif İstanbul Düğün Masası Fikirleri",
            text="zarif istanbul düğün masa çiçek mum altın davetli fikir ek",
        )
        moderate = comparison(
            "moderate",
            title="Başka bir başlık",
            text="zarif istanbul düğün masa çiçek mum farklı öneri",
        )
        weak = comparison(
            "weak",
            title="Bebek uyku düzeni",
            text="bebek uyku gece rutin sağlık ebeveyn",
        )

        assert engine.evaluate(target, (high,)).decision is DuplicateDecisionOutcome.DUPLICATE
        assert engine.evaluate(target, (moderate,)).decision is DuplicateDecisionOutcome.RELATED
        assert engine.evaluate(target, (weak,)).decision is DuplicateDecisionOutcome.UNIQUE

    def test_exact_signal_priority_is_duplicate_then_update_then_fuzzy(self) -> None:
        target = comparison("target", text="alpha beta gamma delta", fingerprint="c" * 64)
        update = comparison(
            "update",
            text="different changed page",
            canonical_url=target.canonical_url,
        )
        exact = comparison("exact", text="nothing similar", fingerprint="c" * 64)

        evaluation = DuplicateEngineV1().evaluate(target, (update, exact))

        assert evaluation.decision is DuplicateDecisionOutcome.DUPLICATE
        assert evaluation.matches[0].normalized_document_id == exact.normalized_document_id

    def test_match_storage_is_bounded_and_contains_no_content(self) -> None:
        thresholds = replace(V1_THRESHOLDS, max_stored_matches=2)
        target = comparison("target", text="alpha beta gamma", fingerprint="d" * 64)
        candidates = tuple(
            comparison(str(index), text=f"different {index}", fingerprint="d" * 64)
            for index in range(5)
        )

        evaluation = DuplicateEngineV1(thresholds).evaluate(target, candidates)

        assert len(evaluation.matches) == 2
        assert "clean_text" not in {field.name for field in fields(evaluation.matches[0])}
        assert evaluation.signals.candidate_count == 5

    def test_reject_is_not_inferred_for_eligible_low_similarity_content(self) -> None:
        target = comparison("target", text="original subject")
        unrelated = comparison("unrelated", text="completely separate material")
        assert (
            DuplicateEngineV1().evaluate(target, (unrelated,)).decision
            is DuplicateDecisionOutcome.UNIQUE
        )


class TestCandidateGeneration:
    def test_candidates_are_bounded_and_self_or_same_snapshot_is_excluded(
        self, session: Session
    ) -> None:
        first = create_document(session, "first", clean_text="first")
        second = create_document(session, "second", clean_text="second")
        target = create_document(session, "target", clean_text="target")
        same_snapshot = NormalizationService(session).record_success(
            target.fetch_snapshot_id,
            extractor_name="text-basic",
            extractor_version="2",
            clean_text="target version two",
        )
        repository = DuplicateCandidateRepository(session)
        target_view = repository.get_document(target.id)
        assert target_view is not None

        candidates = repository.list_candidates(target_view, limit=2)

        assert len(candidates) == 2
        ids = {candidate.normalized_document_id for candidate in candidates}
        assert target.id not in ids
        assert same_snapshot.id not in ids
        assert ids == {first.id, second.id}

    def test_old_exact_candidate_precedes_recent_fill(self, session: Session) -> None:
        exact = create_document(session, "exact", clean_text="same exact text")
        exact.normalized_at = NOW - timedelta(days=100)
        create_document(session, "recent", clean_text="recent unrelated")
        target = create_document(session, "target", clean_text="same exact text")
        repository = DuplicateCandidateRepository(session)
        target_view = repository.get_document(target.id)
        assert target_view is not None

        candidates = repository.list_candidates(target_view, limit=1)

        assert [candidate.normalized_document_id for candidate in candidates] == [exact.id]


class TestServicePersistence:
    def test_service_uses_the_frozen_candidate_limit(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = create_document(session, "target", clean_text="content")
        service = DuplicateDecisionService(session)
        seen_limits: list[int] = []

        def no_candidates(
            _target: ComparisonDocument, *, limit: int
        ) -> tuple[ComparisonDocument, ...]:
            seen_limits.append(limit)
            return ()

        monkeypatch.setattr(service._candidates, "list_candidates", no_candidates)
        decision = service.evaluate_and_record(target.id)

        assert seen_limits == [V1_THRESHOLDS.max_candidate_documents]
        assert decision.decision is DuplicateDecisionOutcome.UNIQUE

    def test_decision_persists_signals_thresholds_matches_and_provenance(
        self, session: Session
    ) -> None:
        existing = create_document(
            session,
            "existing",
            clean_text="aynı özgün Türkçe içerik",
            title="Özgün Başlık",
        )
        target = create_document(
            session,
            "target",
            clean_text="aynı özgün Türkçe içerik",
            title="Özgün Başlık",
        )

        decision = DuplicateDecisionService(session).evaluate_and_record(target.id)

        assert decision.normalized_document_id == target.id
        assert decision.decision is DuplicateDecisionOutcome.DUPLICATE
        assert decision.engine_name == "duplicate-engine"
        assert decision.engine_version == "1"
        assert decision.signals["exact_content_fingerprint_matches"] == 1
        assert decision.thresholds["max_candidate_documents"] == 200
        assert decision.matches[0]["normalized_document_id"] == str(existing.id)
        assert decision.rationale_codes == ["exact_content_fingerprint"]
        assert "clean_text" not in decision.matches[0]

    def test_raw_hash_same_canonical_update_related_and_unique_service_paths(
        self, session: Session
    ) -> None:
        shared_raw = b"identical raw body"
        create_document(session, "raw-a", clean_text="first parser", raw_body=shared_raw)
        raw_target = create_document(
            session, "raw-b", clean_text="different parser", raw_body=shared_raw
        )
        assert (
            DuplicateDecisionService(session).evaluate_and_record(raw_target.id).decision
            is DuplicateDecisionOutcome.DUPLICATE
        )

        shared_url = "https://logical.example.test/article"
        create_document(
            session,
            "old-resource",
            clean_text="old resource body",
            canonical_url=shared_url,
        )
        changed = create_document(
            session,
            "new-resource",
            clean_text="changed resource body",
            canonical_url=shared_url,
        )
        assert (
            DuplicateDecisionService(session).evaluate_and_record(changed.id).decision
            is DuplicateDecisionOutcome.UPDATE_EXISTING
        )

        create_document(
            session,
            "topic-a",
            clean_text="zarif düğün masa çiçek mum farklı",
            title="İlk başlık",
        )
        related = create_document(
            session,
            "topic-b",
            clean_text="zarif düğün masa çiçek yeni öneri",
            title="İkinci başlık",
        )
        assert (
            DuplicateDecisionService(session).evaluate_and_record(related.id).decision
            is DuplicateDecisionOutcome.RELATED
        )

        unique = create_document(
            session,
            "unique",
            clean_text="bebek uyku sağlık rutin gece",
            title="Bebek uykusu",
        )
        assert (
            DuplicateDecisionService(session).evaluate_and_record(unique.id).decision
            is DuplicateDecisionOutcome.UNIQUE
        )

    def test_exact_retry_is_idempotent_and_engine_v2_coexists(self, session: Session) -> None:
        target = create_document(session, "target", clean_text="standalone unique content")
        service = DuplicateDecisionService(session)

        first = service.evaluate_and_record(target.id)
        create_document(session, "later-corpus-entry", clean_text="later unrelated content")
        second = service.evaluate_and_record(target.id)
        v2 = StaticEngine(DuplicateDecisionOutcome.UNIQUE)
        v2.version = "2"
        third = DuplicateDecisionService(session, v2).evaluate_and_record(target.id)

        assert second is first
        assert third.id != first.id
        assert decision_count(session) == 2
        assert DuplicateDecisionRepository(session).list_for_document(target.id) == [first, third]

    def test_conflicting_same_engine_version_race_is_typed(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = create_document(session, "target", clean_text="content")
        existing = DuplicateDecisionService(
            session, StaticEngine(DuplicateDecisionOutcome.UNIQUE)
        ).evaluate_and_record(target.id)
        service = DuplicateDecisionService(session, StaticEngine(DuplicateDecisionOutcome.RELATED))
        calls = 0

        def race_lookup(*_args: object) -> DuplicateDecision | None:
            nonlocal calls
            calls += 1
            return None if calls == 1 else existing

        monkeypatch.setattr(service._decisions, "get_by_document_and_engine", race_lookup)

        with pytest.raises(DuplicateDecisionConflictError):
            service.evaluate_and_record(target.id)

    def test_uniqueness_race_returns_identical_winner(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = create_document(session, "target", clean_text="content")
        initial = DuplicateDecisionService(session)
        winner = initial.evaluate_and_record(target.id)
        service = DuplicateDecisionService(session)
        calls = 0

        def race_lookup(*_args: object) -> DuplicateDecision | None:
            nonlocal calls
            calls += 1
            return None if calls == 1 else winner

        def fail_add(_decision: DuplicateDecision) -> DuplicateDecision:
            raise IntegrityError("insert", {}, Exception("race"))

        monkeypatch.setattr(service._decisions, "get_by_document_and_engine", race_lookup)
        monkeypatch.setattr(service._decisions, "add", fail_add)

        assert service.evaluate_and_record(target.id) is winner

    def test_unresolved_database_failure_is_sanitized(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = create_document(session, "target", clean_text="content")
        service = DuplicateDecisionService(session)
        monkeypatch.setattr(service._decisions, "get_by_document_and_engine", lambda *_: None)

        def fail_add(_decision: DuplicateDecision) -> DuplicateDecision:
            raise IntegrityError("secret SQL", {}, Exception("database detail"))

        monkeypatch.setattr(service._decisions, "add", fail_add)
        with pytest.raises(
            DuplicateDecisionPersistenceError,
            match="database rejected duplicate decision",
        ):
            service.evaluate_and_record(target.id)

    def test_missing_failed_and_incomplete_documents_are_ineligible(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = DuplicateDecisionService(session)
        with pytest.raises(DuplicateDocumentNotFoundError):
            service.evaluate_and_record(uuid.uuid4())

        failed = create_document(session, "failed", clean_text="unused", failed=True)
        with pytest.raises(DuplicateDocumentNotEligibleError):
            service.evaluate_and_record(failed.id)

        valid = create_document(session, "valid", clean_text="complete")
        view = service._candidates.get_document(valid.id)
        assert view is not None
        monkeypatch.setattr(
            service._candidates,
            "get_document",
            lambda _id: replace(view, content_fingerprint=None),
        )
        with pytest.raises(DuplicateDocumentNotEligibleError):
            service.evaluate_and_record(valid.id)

    def test_service_flushes_without_committing(self, session: Session) -> None:
        target = create_document(session, "target", clean_text="content")
        decision = DuplicateDecisionService(session).evaluate_and_record(target.id)
        assert decision in session.new or decision in session
