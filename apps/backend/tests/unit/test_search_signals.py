"""Provider-neutral search-signal foundation tests (real services, SQLite)."""

import hashlib
import math
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
from contentos.fetching.models import (
    FetchOutcome,
    FetchResult,
    RetryClassification,
    RobotsDecision,
)
from contentos.fetching.snapshot_service import FetchSnapshotService
from contentos.normalization.service import NormalizationService
from contentos.opportunities.models import OpportunityScore
from contentos.opportunities.repository import OpportunityRepository
from contentos.opportunities.scoring_service import OpportunityScoringService
from contentos.opportunities.service import ResearchPromotionService
from contentos.signals.enums import MANUAL_OPERATOR_PROVIDER, SearchSignalType
from contentos.signals.errors import (
    InvalidSignalInputError,
    UnsupportedSignalValueError,
)
from contentos.signals.models import SearchSignal
from contentos.signals.repository import SearchSignalRepository
from contentos.signals.service import SearchSignalService
from contentos.signals.values import validate_signal_value
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

    # pysqlite's legacy mode implicitly commits around SAVEPOINT statements,
    # which would break the service's begin_nested()/rollback contract in
    # tests only; disabling driver transaction handling and emitting BEGIN
    # explicitly is the SQLAlchemy-documented correction (Task 16 pattern).
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


def record_note(
    session: Session,
    subject: str = "doğum günü konseptleri",
    *,
    observed_at: datetime = NOW,
    note: str = "Kullanıcılar pratik planlama listeleri arıyor.",
) -> Any:
    result = SearchSignalService(session).record_manual_signal(
        signal_type=SearchSignalType.MANUAL_INTENT_NOTE,
        subject=subject,
        value={"note": note},
        observed_at=observed_at,
    )
    session.commit()
    return result


class TestManualRecording:
    def test_manual_intent_note_round_trip(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            result = record_note(session, subject="  doğum   günü   konseptleri ")

            assert result.created is True
            signal = result.signal
            assert signal.signal_type is SearchSignalType.MANUAL_INTENT_NOTE
            # Conservative whitespace normalization only; Turkish casing kept.
            assert signal.subject == "doğum günü konseptleri"
            assert signal.locale == "tr-TR"
            assert signal.market == "TR"
            assert signal.provider == MANUAL_OPERATOR_PROVIDER
            assert signal.value == {"note": "Kullanıcılar pratik planlama listeleri arıyor."}
            assert signal.observed_at == NOW
            assert signal.as_of is None
            assert signal.confidence is None  # never defaulted to 1.0
            assert signal.recorded_at is not None
            assert len(signal.observation_hash) == 64

    def test_query_set_cleans_and_deduplicates_preserving_order(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            result = SearchSignalService(session).record_manual_signal(
                signal_type=SearchSignalType.QUERY_SET,
                subject="doğum günü",
                value={
                    "queries": [
                        " doğum günü süsleri ",
                        "",
                        "doğum günü pastası",
                        "doğum günü süsleri",
                        "   ",
                        "ev partisi fikirleri",
                    ]
                },
                observed_at=NOW,
            )
            session.commit()
            assert result.signal.value == {
                "queries": [
                    "doğum günü süsleri",
                    "doğum günü pastası",
                    "ev partisi fikirleri",
                ]
            }

    def test_search_volume_requires_unit_and_basis(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            service = SearchSignalService(session)
            # A naked ambiguous number is rejected.
            with pytest.raises(UnsupportedSignalValueError):
                service.record_manual_signal(
                    signal_type=SearchSignalType.SEARCH_VOLUME,
                    subject="doğum günü",
                    value={"value": 1000},
                    observed_at=NOW,
                )
            # Zero is a legitimate observation with explicit semantics.
            result = service.record_manual_signal(
                signal_type=SearchSignalType.SEARCH_VOLUME,
                subject="doğum günü",
                value={
                    "value": 0,
                    "unit": "searches_per_month",
                    "basis": "operator entry from keyword tool export",
                    "period": "2026-08",
                },
                observed_at=NOW,
                as_of=datetime(2026, 8, 1, tzinfo=UTC),
            )
            session.commit()
            assert result.signal.value["value"] == 0.0
            assert result.signal.value["unit"] == "searches_per_month"
            assert result.signal.as_of == datetime(2026, 8, 1, tzinfo=UTC)

    def test_trend_requires_explicit_scale_and_basis(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            service = SearchSignalService(session)
            with pytest.raises(UnsupportedSignalValueError):
                service.record_manual_signal(
                    signal_type=SearchSignalType.TREND,
                    subject="yılbaşı partisi",
                    value={"observation": 87},
                    observed_at=NOW,
                )
            result = service.record_manual_signal(
                signal_type=SearchSignalType.TREND,
                subject="yılbaşı partisi",
                value={
                    "observation": "rising",
                    "scale": "operator-observed direction",
                    "basis": "manual comparison of seasonal interest",
                },
                observed_at=NOW,
            )
            session.commit()
            assert result.signal.value["scale"] == "operator-observed direction"

    def test_serp_observation_is_bounded_and_rejects_raw_html(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            service = SearchSignalService(session)
            with pytest.raises(UnsupportedSignalValueError, match="unsupported value keys"):
                service.record_manual_signal(
                    signal_type=SearchSignalType.SERP_OBSERVATION,
                    subject="doğum günü",
                    value={"html": "<html>raw serp</html>"},
                    observed_at=NOW,
                )
            with pytest.raises(UnsupportedSignalValueError, match="at least one"):
                service.record_manual_signal(
                    signal_type=SearchSignalType.SERP_OBSERVATION,
                    subject="doğum günü",
                    value={},
                    observed_at=NOW,
                )
            result = service.record_manual_signal(
                signal_type=SearchSignalType.SERP_OBSERVATION,
                subject="doğum günü",
                value={
                    "features": ["görsel paketi", "sorular bölümü"],
                    "intent_pattern": "planlama/rehber ağırlıklı",
                },
                observed_at=NOW,
            )
            session.commit()
            assert result.signal.value["features"] == ["görsel paketi", "sorular bölümü"]


class TestValidation:
    @pytest.mark.parametrize(
        ("field", "kwargs"),
        [
            ("subject", {"subject": "   "}),
            ("subject", {"subject": "x" * 301}),
            ("locale", {"locale": " "}),
            ("market", {"market": "TUR"}),
            ("confidence", {"confidence": 1.5}),
            ("confidence", {"confidence": float("nan")}),
            ("observed_at", {"observed_at": datetime(2026, 9, 1)}),  # naive
        ],
    )
    def test_invalid_inputs_rejected(
        self, session_factory: sessionmaker[Session], field: str, kwargs: dict[str, Any]
    ) -> None:
        base: dict[str, Any] = {
            "signal_type": SearchSignalType.MANUAL_INTENT_NOTE,
            "subject": "geçerli konu",
            "value": {"note": "not"},
            "observed_at": NOW,
        }
        base.update(kwargs)
        with open_session(session_factory) as session:
            with pytest.raises(InvalidSignalInputError):
                SearchSignalService(session).record_manual_signal(**base)

    def test_naive_as_of_rejected(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            with pytest.raises(InvalidSignalInputError):
                SearchSignalService(session).record_manual_signal(
                    signal_type=SearchSignalType.MANUAL_INTENT_NOTE,
                    subject="konu",
                    value={"note": "not"},
                    observed_at=NOW,
                    as_of=datetime(2026, 8, 1),
                )

    def test_malformed_and_oversized_values_rejected(self) -> None:
        with pytest.raises(UnsupportedSignalValueError):
            validate_signal_value(SearchSignalType.MANUAL_INTENT_NOTE, {"note": ""})
        with pytest.raises(UnsupportedSignalValueError):
            validate_signal_value(SearchSignalType.MANUAL_INTENT_NOTE, {"note": "x" * 2001})
        with pytest.raises(UnsupportedSignalValueError):
            validate_signal_value(SearchSignalType.MANUAL_INTENT_NOTE, {"note": "ok", "extra": 1})
        with pytest.raises(UnsupportedSignalValueError):
            validate_signal_value(
                SearchSignalType.QUERY_SET,
                {"queries": [f"soru {i}" for i in range(51)]},
            )
        with pytest.raises(UnsupportedSignalValueError):
            validate_signal_value(SearchSignalType.QUERY_SET, {"queries": ["", "  "]})
        with pytest.raises(UnsupportedSignalValueError):
            validate_signal_value(
                SearchSignalType.SEARCH_VOLUME,
                {"value": math.inf, "unit": "u", "basis": "b"},
            )
        with pytest.raises(UnsupportedSignalValueError):
            validate_signal_value(
                SearchSignalType.TREND, {"observation": True, "scale": "s", "basis": "b"}
            )
        with pytest.raises(UnsupportedSignalValueError):
            validate_signal_value(SearchSignalType.MANUAL_INTENT_NOTE, [])  # type: ignore[arg-type]


class TestIdempotency:
    def test_exact_retry_returns_existing_row(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            first = record_note(session)
            second = record_note(session)

            assert second.created is False
            assert second.signal.id == first.signal.id
            assert len(list(session.execute(select(SearchSignal)).scalars())) == 1

    @pytest.mark.parametrize(
        "change",
        [
            {"observed_at": NOW + timedelta(days=1)},
            {"note": "Farklı bir gözlem notu."},
            {"subject": "başka konu"},
        ],
    )
    def test_changed_observation_appends_new_row(
        self, session_factory: sessionmaker[Session], change: dict[str, Any]
    ) -> None:
        with open_session(session_factory) as session:
            record_note(session)
            record_note(session, **change)  # type: ignore[arg-type]
            assert len(list(session.execute(select(SearchSignal)).scalars())) == 2

    def test_changed_as_of_and_type_append_new_rows(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            service = SearchSignalService(session)
            base: dict[str, Any] = {
                "signal_type": SearchSignalType.SEARCH_VOLUME,
                "subject": "doğum günü",
                "value": {"value": 100, "unit": "u", "basis": "b"},
                "observed_at": NOW,
            }
            service.record_manual_signal(**base)
            service.record_manual_signal(**base, as_of=datetime(2026, 8, 1, tzinfo=UTC))
            session.commit()
            assert len(list(session.execute(select(SearchSignal)).scalars())) == 2

    def test_race_recovers_existing_signal(
        self, session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with open_session(session_factory) as session:
            first = record_note(session)

            original = SearchSignalRepository.get_by_observation_hash
            calls = {"count": 0}

            def racy(self: SearchSignalRepository, observation_hash: str) -> SearchSignal | None:
                calls["count"] += 1
                if calls["count"] == 1:
                    return None  # pre-check misses the concurrent winner
                return original(self, observation_hash)

            monkeypatch.setattr(SearchSignalRepository, "get_by_observation_hash", racy)
            recovered = record_note(session)
            assert recovered.created is False
            assert recovered.signal.id == first.signal.id

    def test_caller_owns_commit(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            SearchSignalService(session).record_manual_signal(
                signal_type=SearchSignalType.MANUAL_INTENT_NOTE,
                subject="kaydedilmeyecek",
                value={"note": "rollback edilecek"},
                observed_at=NOW,
            )
            session.rollback()

        with open_session(session_factory) as session:
            assert session.execute(select(SearchSignal)).scalar_one_or_none() is None


class TestObservationHistory:
    def test_multiple_observations_coexist_in_deterministic_order(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            record_note(session, observed_at=NOW, note="ilk gözlem")
            record_note(session, observed_at=NOW + timedelta(days=1), note="ikinci gözlem")
            record_note(session, observed_at=NOW + timedelta(days=2), note="üçüncü gözlem")

            history = SearchSignalRepository(session).list_for_subject(
                "doğum günü konseptleri", "tr-TR", "TR"
            )
            # History is preserved, newest first — never collapsed into one truth.
            assert [signal.value["note"] for signal in history] == [
                "üçüncü gözlem",
                "ikinci gözlem",
                "ilk gözlem",
            ]

    def test_repository_exposes_no_mutation_or_current_truth_surface(self) -> None:
        exposed = {name for name in dir(SearchSignalRepository) if not name.startswith("_")}
        assert exposed == {
            "add",
            "get_by_id",
            "get_by_observation_hash",
            "list_for_subject",
            "list_by_type",
        }
        assert not any("current" in name or "effective" in name for name in exposed)


class TestIsolation:
    def test_recording_signals_has_no_workflow_or_scoring_side_effects(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            # Build one real promoted + scored opportunity.
            source = SourceRegistryService(session).register_source(
                slug="sinyal-izolasyon",
                name="Sinyal İzolasyon",
                kind=SourceKind.MANUAL,
                base_url="https://sinyal-izolasyon.example.test/",
                trust_tier=TrustTier.GENERAL,
            )
            discoveries = DiscoveryService(session)
            item = discoveries.discover_manual(
                source.id, "https://sinyal-izolasyon.example.test/haber"
            )
            discoveries.accept_item(item.id)
            body = b"<html>izolasyon govdesi</html>"
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
                clean_text="İzolasyon testi için özgün metin.",
                title="İzolasyon Başlığı",
            )
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
            promo = ResearchPromotionService(session).promote_research(document.id)
            session.commit()
            OpportunityScoringService(session).evaluate_opportunity(
                promo.opportunity_id, evaluated_at=NOW
            )
            session.commit()

            record_note(session, subject="izolasyon konusu")

            opportunity = OpportunityRepository(session).get_by_id(promo.opportunity_id)
            assert opportunity is not None
            assert opportunity.disposition.value == "open"
            assert len(list(session.execute(select(OpportunityScore)).scalars())) == 1
            events = WorkflowRepository(session).list_events(promo.work_item_id)
            assert len(events) == 1

    def test_signal_model_has_no_opportunity_or_evidence_fk(self) -> None:
        columns = {column.name for column in SearchSignal.__table__.columns}
        assert "opportunity_id" not in columns
        assert "research_evidence_id" not in columns
        foreign_keys = {
            fk.column.table.name
            for column in SearchSignal.__table__.columns
            for fk in column.foreign_keys
        }
        assert foreign_keys == set()

    def test_missing_signal_lookup(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            assert SearchSignalRepository(session).get_by_id(uuid.uuid4()) is None
