"""SearchIntentAnalysis tests (real services over SQLite; fake AI provider)."""

import hashlib
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from contentos.ai.enums import GenerationPurpose, GenerationStatus, ProviderFailureKind
from contentos.ai.fake import FakeStructuredProvider
from contentos.ai.models import AiGenerationAttempt
from contentos.db.base import Base
from contentos.discovery.service import DiscoveryService
from contentos.duplicates.enums import DuplicateDecisionOutcome
from contentos.duplicates.models import DuplicateDecision
from contentos.evidence_packs.models import EvidencePack
from contentos.fetching.models import (
    FetchOutcome,
    FetchResult,
    RetryClassification,
    RobotsDecision,
)
from contentos.fetching.snapshot_service import FetchSnapshotService
from contentos.ideas.enums import ContentType
from contentos.ideas.models import Idea, IdeaSelectionEvent
from contentos.ideas.service import IdeaService
from contentos.normalization.service import NormalizationService
from contentos.opportunities.repository import OpportunityRepository
from contentos.opportunities.service import ResearchPromotionService
from contentos.research.models import ResearchEvidence
from contentos.search_intent.enums import CannibalizationStatus
from contentos.search_intent.errors import (
    IdeaNotSelectedError,
    IncompleteAnalysisMaterializationError,
    InvalidAnalysisInputError,
    InvalidCannibalizationError,
    InvalidSynthesisAttemptError,
    SignalNotEligibleError,
)
from contentos.search_intent.models import SearchIntentAnalysis
from contentos.search_intent.repository import SearchIntentRepository
from contentos.search_intent.service import (
    SearchIntentService,
    _validate_synthesis_attempt,
)
from contentos.search_intent.values import (
    CannibalizationInput,
    IntentComposition,
    InternalReference,
)
from contentos.signals.enums import SearchSignalType
from contentos.signals.models import SearchSignal
from contentos.signals.service import SearchSignalService
from contentos.sources.enums import SourceKind, TrustTier
from contentos.sources.service import SourceRegistryService
from contentos.workflow.repository import WorkflowRepository

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

COMPOSITION = IntentComposition(
    primary_intent="Evde doğum günü partisi planlama rehberi arayışı",
    page_purpose="Adım adım uygulanabilir bir planlama rehberi sunmak",
    likely_format="planlama rehberi",
    secondary_intents=("fikir ve ilham arayışı",),
    query_concepts=("evde doğum günü partisi", "balon süsleme fikirleri"),
)

SYNTH_PAYLOAD: dict[str, Any] = {
    "primary_intent": "Ev partisi planlama rehberi arayışı",
    "secondary_intents": ["fikir arayışı"],
    "query_concepts": ["evde doğum günü partisi", "parti hazırlık listesi"],
    "page_purpose": "Kapsamlı, uygulanabilir planlama rehberi sunmak",
    "likely_format": "planlama rehberi",
}


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


def seed_opportunity_with_selected_idea(
    session: Session, *, select_idea: bool = True
) -> tuple[uuid.UUID, uuid.UUID]:
    """One promoted opportunity plus one (optionally selected) operator idea."""
    token = uuid.uuid4().hex[:8]
    source = SourceRegistryService(session).register_source(
        slug=f"kaynak-{token}",
        name="Kaynak",
        kind=SourceKind.MANUAL,
        base_url=f"https://kaynak-{token}.example.test/",
        trust_tier=TrustTier.GENERAL,
    )
    discoveries = DiscoveryService(session)
    item = discoveries.discover_manual(source.id, f"https://kaynak-{token}.example.test/haber")
    discoveries.accept_item(item.id)
    body = f"<html>{token} govdesi</html>".encode()
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
        clean_text="Uzun ve özgün araştırma metni burada.",
        title="Doğum günü partisi fikirleri",
    )
    session.commit()
    decision = DuplicateDecision(
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
    session.add(decision)
    session.commit()
    promo = ResearchPromotionService(session).promote_research(document.id)
    session.commit()

    idea = IdeaService(session).create_operator_idea(
        promo.opportunity_id,
        working_title="Evde balon temalı doğum günü planı",
        angle="Bütçe dostu üç saatlik hazırlık akışına odaklanıyoruz.",
        audience="Küçük çocuklu ebeveynler",
        value_proposition="Tek listeyle eksiksiz parti hazırlığı sağlar.",
        rationale="Kaynaklar genel; biz uygulanabilir zaman çizelgesi veriyoruz.",
        content_type=ContentType.PLANNING_GUIDE,
    )
    session.commit()
    if select_idea:
        IdeaService(session).select_idea(idea.id, reason="tek aday")
        session.commit()
    return promo.opportunity_id, idea.id


def record_signal(
    session: Session,
    signal_type: SearchSignalType,
    value: dict[str, Any],
    *,
    subject: str = "evde doğum günü partisi",
    locale: str = "tr-TR",
    market: str = "TR",
) -> uuid.UUID:
    recorded = SearchSignalService(session).record_manual_signal(
        signal_type=signal_type,
        subject=subject,
        value=value,
        observed_at=NOW,
        locale=locale,
        market=market,
    )
    session.commit()
    return recorded.signal.id


def note_signal(session: Session, note: str = "Operatör niyet notu.") -> uuid.UUID:
    return record_signal(session, SearchSignalType.MANUAL_INTENT_NOTE, {"note": note})


class TestDeterministicComposition:
    def test_basic_deterministic_analysis(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id, idea_id = seed_opportunity_with_selected_idea(session)
            signal_id = note_signal(session)
            result = SearchIntentService(session).compose_deterministic(
                opportunity_id,
                idea_id=idea_id,
                composition=COMPOSITION,
                signal_ids=[signal_id],
            )
            session.commit()

            assert result.created is True
            analysis = result.analysis
            assert analysis.version == 1
            assert analysis.idea_id == idea_id
            assert analysis.target_audience == "Küçük çocuklu ebeveynler"
            assert analysis.locale == "tr-TR" and analysis.market == "TR"
            assert analysis.synthesis_attempt_id is None
            assert analysis.engine_name == "search-intent-analyzer"
            assert analysis.engine_version == "1"
            [ref] = analysis.known_signal_refs
            assert ref["signal_id"] == str(signal_id)
            assert ref["signal_type"] == "manual_intent_note"
            assert ref["provider"] == "manual_operator"
            assert "manual_intent_note" not in analysis.missing_signals
            assert "search_volume" in analysis.missing_signals
            assert analysis.cannibalization_status is CannibalizationStatus.NOT_CHECKED
            # No AI attempt, no workflow event, no selection change.
            assert session.execute(select(AiGenerationAttempt)).scalar_one_or_none() is None
            opportunity = OpportunityRepository(session).get_by_id(opportunity_id)
            assert opportunity is not None
            events = WorkflowRepository(session).list_events(opportunity.work_item_id)
            assert len(events) == 1
            selection_events = list(session.execute(select(IdeaSelectionEvent)).scalars())
            assert len(selection_events) == 1  # only the original selection

    def test_zero_signal_analysis_is_honest(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id, idea_id = seed_opportunity_with_selected_idea(session)
            analysis = (
                SearchIntentService(session)
                .compose_deterministic(opportunity_id, idea_id=idea_id, composition=COMPOSITION)
                .analysis
            )
            session.commit()
            assert analysis.known_signal_refs == []
            assert analysis.missing_signals == sorted(
                signal_type.value for signal_type in SearchSignalType
            )
            assert analysis.cannibalization_status is CannibalizationStatus.NOT_CHECKED
            basis = analysis.cannibalization_basis
            assert basis["checked"] is False
            assert basis["published_inventory"] == "unavailable_not_checked"
            # UNKNOWN != ZERO: no fabricated numeric anywhere.
            import json

            assert '"volume": 0' not in json.dumps(analysis.input_snapshot)

    def test_all_signal_types_snapshot(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id, idea_id = seed_opportunity_with_selected_idea(session)
            signal_ids = [
                record_signal(
                    session,
                    SearchSignalType.SEARCH_VOLUME,
                    {"value": 1200, "unit": "aylık arama", "basis": "operatör tahmini"},
                ),
                record_signal(
                    session,
                    SearchSignalType.TREND,
                    {
                        "observation": "yükseliş",
                        "scale": "düşük/orta/yüksek",
                        "basis": "mevsimsel gözlem",
                    },
                ),
                record_signal(
                    session,
                    SearchSignalType.SERP_OBSERVATION,
                    {"features": ["listeler", "görsel paketi"]},
                ),
                record_signal(
                    session,
                    SearchSignalType.QUERY_SET,
                    {"queries": ["doğum günü süsleme", "parti fikirleri", "balon kemer"]},
                ),
                note_signal(session),
            ]
            analysis = (
                SearchIntentService(session)
                .compose_deterministic(
                    opportunity_id,
                    idea_id=idea_id,
                    composition=COMPOSITION,
                    signal_ids=signal_ids,
                )
                .analysis
            )
            session.commit()
            assert analysis.missing_signals == []
            assert len(analysis.known_signal_refs) == 5
            by_type = {ref["signal_type"]: ref for ref in analysis.known_signal_refs}
            assert by_type["search_volume"]["value"]["unit"] == "aylık arama"
            assert by_type["trend"]["value"]["observation"] == "yükseliş"
            assert by_type["search_volume"]["observed_at"] == NOW.isoformat()
            # QUERY_SET internal order is semantic and preserved as stored.
            assert by_type["query_set"]["value"]["queries"] == [
                "doğum günü süsleme",
                "parti fikirleri",
                "balon kemer",
            ]

    def test_new_observation_is_a_new_input(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id, idea_id = seed_opportunity_with_selected_idea(session)
            service = SearchIntentService(session)
            signal_a = note_signal(session, "İlk gözlem notu.")
            v1 = service.compose_deterministic(
                opportunity_id,
                idea_id=idea_id,
                composition=COMPOSITION,
                signal_ids=[signal_a],
            ).analysis
            session.commit()

            signal_b = note_signal(session, "Daha yeni gözlem notu.")
            reused = service.compose_deterministic(
                opportunity_id,
                idea_id=idea_id,
                composition=COMPOSITION,
                signal_ids=[signal_a],
            )
            assert reused.created is False and reused.analysis.id == v1.id

            v2 = service.compose_deterministic(
                opportunity_id,
                idea_id=idea_id,
                composition=COMPOSITION,
                signal_ids=[signal_b],
            ).analysis
            session.commit()
            assert v2.version == 2
            # v1 keeps its frozen old observation; never magically switched.
            v1_reread = SearchIntentRepository(session).get_by_id(v1.id)
            assert v1_reread is not None
            assert v1_reread.known_signal_refs[0]["signal_id"] == str(signal_a)

    def test_wrong_locale_signal_rejected(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id, idea_id = seed_opportunity_with_selected_idea(session)
            foreign_signal = record_signal(
                session,
                SearchSignalType.MANUAL_INTENT_NOTE,
                {"note": "US context note."},
                locale="en-US",
                market="US",
            )
            with pytest.raises(SignalNotEligibleError, match="locale/market"):
                SearchIntentService(session).compose_deterministic(
                    opportunity_id,
                    idea_id=idea_id,
                    composition=COMPOSITION,
                    signal_ids=[foreign_signal],
                )
            session.rollback()
            assert session.execute(select(SearchIntentAnalysis)).scalar_one_or_none() is None

    def test_missing_and_duplicate_signals_rejected(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, idea_id = seed_opportunity_with_selected_idea(session)
            service = SearchIntentService(session)
            with pytest.raises(SignalNotEligibleError):
                service.compose_deterministic(
                    opportunity_id,
                    idea_id=idea_id,
                    composition=COMPOSITION,
                    signal_ids=[uuid.uuid4()],
                )
            signal_id = note_signal(session)
            with pytest.raises(InvalidAnalysisInputError, match="twice"):
                service.compose_deterministic(
                    opportunity_id,
                    idea_id=idea_id,
                    composition=COMPOSITION,
                    signal_ids=[signal_id, signal_id],
                )


class TestSelectedIdeaPin:
    def test_selection_preconditions(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id, idea_id = seed_opportunity_with_selected_idea(
                session, select_idea=False
            )
            service = SearchIntentService(session)
            with pytest.raises(IdeaNotSelectedError, match="no idea"):
                service.compose_deterministic(
                    opportunity_id, idea_id=idea_id, composition=COMPOSITION
                )
            IdeaService(session).select_idea(idea_id, reason="tek aday")
            session.commit()
            with pytest.raises(IdeaNotSelectedError, match="effective"):
                service.compose_deterministic(
                    opportunity_id, idea_id=uuid.uuid4(), composition=COMPOSITION
                )
            result = service.compose_deterministic(
                opportunity_id, idea_id=idea_id, composition=COMPOSITION
            )
            session.commit()
            assert result.analysis.idea_id == idea_id

    def test_later_selection_change_never_repoints(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, idea_a = seed_opportunity_with_selected_idea(session)
            service = SearchIntentService(session)
            v1 = service.compose_deterministic(
                opportunity_id, idea_id=idea_a, composition=COMPOSITION
            ).analysis
            session.commit()

            idea_b = IdeaService(session).create_operator_idea(
                opportunity_id,
                working_title="Bahçede yaz temalı doğum günü rehberi",
                angle="Açık hava akışına odaklanıyoruz.",
                audience="Küçük çocuklu ebeveynler",
                value_proposition="Bahçe partisi için eksiksiz hazırlık.",
                rationale="Alternatif mekan açısı sunuyoruz.",
                content_type=ContentType.PLANNING_GUIDE,
            )
            session.commit()
            IdeaService(session).select_idea(idea_b.id, reason="mekan açısı daha güçlü")
            session.commit()

            # Old analysis stays permanently pinned to idea A.
            v1_reread = SearchIntentRepository(session).get_by_id(v1.id)
            assert v1_reread is not None and v1_reread.idea_id == idea_a
            # Analyzing A now fails (not effective); analyzing B is new v2.
            with pytest.raises(IdeaNotSelectedError):
                service.compose_deterministic(
                    opportunity_id, idea_id=idea_a, composition=COMPOSITION
                )
            v2 = service.compose_deterministic(
                opportunity_id, idea_id=idea_b.id, composition=COMPOSITION
            ).analysis
            session.commit()
            assert v2.version == 2 and v2.idea_id == idea_b.id


class TestCannibalization:
    def test_internal_no_known_conflict(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id, idea_id = seed_opportunity_with_selected_idea(session)
            other_opportunity, _ = seed_opportunity_with_selected_idea(session)
            analysis = (
                SearchIntentService(session)
                .compose_deterministic(
                    opportunity_id,
                    idea_id=idea_id,
                    composition=COMPOSITION,
                    cannibalization=CannibalizationInput(
                        status=CannibalizationStatus.NO_KNOWN_CONFLICT,
                        checked_references=(
                            InternalReference(kind="opportunity", reference_id=other_opportunity),
                        ),
                        reason="tek benzer fırsat incelendi, örtüşme yok",
                    ),
                )
                .analysis
            )
            session.commit()
            assert analysis.cannibalization_status is CannibalizationStatus.NO_KNOWN_CONFLICT
            basis = analysis.cannibalization_basis
            assert basis["scope"] == "contentos_internal"
            assert basis["checked_references"] == [
                {"kind": "opportunity", "id": str(other_opportunity)}
            ]
            # The missing published-inventory scope stays visible.
            assert basis["published_inventory"] == "unavailable_not_checked"

    def test_potential_conflict_with_related_references(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, idea_id = seed_opportunity_with_selected_idea(session)
            other_opportunity, other_idea = seed_opportunity_with_selected_idea(session)
            analysis = (
                SearchIntentService(session)
                .compose_deterministic(
                    opportunity_id,
                    idea_id=idea_id,
                    composition=COMPOSITION,
                    cannibalization=CannibalizationInput(
                        status=CannibalizationStatus.POTENTIAL_CONFLICT,
                        checked_references=(
                            InternalReference(kind="opportunity", reference_id=other_opportunity),
                            InternalReference(kind="idea", reference_id=other_idea),
                        ),
                    ),
                    related_references=[
                        InternalReference(kind="opportunity", reference_id=other_opportunity)
                    ],
                )
                .analysis
            )
            session.commit()
            assert analysis.cannibalization_status is CannibalizationStatus.POTENTIAL_CONFLICT
            assert analysis.related_references == [
                {"kind": "opportunity", "id": str(other_opportunity)}
            ]

    def test_known_conflict_and_vague_bases_rejected(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, idea_id = seed_opportunity_with_selected_idea(session)
            service = SearchIntentService(session)
            with pytest.raises(InvalidCannibalizationError, match="KNOWN_CONFLICT"):
                service.compose_deterministic(
                    opportunity_id,
                    idea_id=idea_id,
                    composition=COMPOSITION,
                    cannibalization=CannibalizationInput(
                        status=CannibalizationStatus.KNOWN_CONFLICT
                    ),
                )
            with pytest.raises(InvalidCannibalizationError, match="exact internal"):
                service.compose_deterministic(
                    opportunity_id,
                    idea_id=idea_id,
                    composition=COMPOSITION,
                    cannibalization=CannibalizationInput(
                        status=CannibalizationStatus.NO_KNOWN_CONFLICT
                    ),
                )
            with pytest.raises(InvalidCannibalizationError, match="NOT_CHECKED"):
                service.compose_deterministic(
                    opportunity_id,
                    idea_id=idea_id,
                    composition=COMPOSITION,
                    cannibalization=CannibalizationInput(
                        status=CannibalizationStatus.NOT_CHECKED,
                        checked_references=(
                            InternalReference(kind="opportunity", reference_id=opportunity_id),
                        ),
                    ),
                )
            with pytest.raises(InvalidAnalysisInputError, match="does not exist"):
                service.compose_deterministic(
                    opportunity_id,
                    idea_id=idea_id,
                    composition=COMPOSITION,
                    related_references=[InternalReference(kind="idea", reference_id=uuid.uuid4())],
                )
            assert session.execute(select(SearchIntentAnalysis)).scalar_one_or_none() is None


class TestIdempotency:
    def test_exact_deterministic_retry(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id, idea_id = seed_opportunity_with_selected_idea(session)
            signal_id = note_signal(session)
            service = SearchIntentService(session)
            first = service.compose_deterministic(
                opportunity_id,
                idea_id=idea_id,
                composition=COMPOSITION,
                signal_ids=[signal_id],
            )
            session.commit()
            second = service.compose_deterministic(
                opportunity_id,
                idea_id=idea_id,
                composition=COMPOSITION,
                signal_ids=[signal_id],
            )
            assert second.created is False
            assert second.analysis.id == first.analysis.id
            rows = list(session.execute(select(SearchIntentAnalysis)).scalars())
            assert len(rows) == 1

    def test_changed_semantic_inputs_append_versions(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, idea_id = seed_opportunity_with_selected_idea(session)
            other_opportunity, _ = seed_opportunity_with_selected_idea(session)
            service = SearchIntentService(session)
            service.compose_deterministic(opportunity_id, idea_id=idea_id, composition=COMPOSITION)
            session.commit()

            changed_composition = service.compose_deterministic(
                opportunity_id,
                idea_id=idea_id,
                composition=IntentComposition(
                    primary_intent="Farklı birincil niyet ifadesi",
                    page_purpose=COMPOSITION.page_purpose,
                    likely_format=COMPOSITION.likely_format,
                ),
            )
            session.commit()
            assert changed_composition.created and changed_composition.analysis.version == 2

            changed_cannibalization = service.compose_deterministic(
                opportunity_id,
                idea_id=idea_id,
                composition=COMPOSITION,
                cannibalization=CannibalizationInput(
                    status=CannibalizationStatus.NO_KNOWN_CONFLICT,
                    checked_references=(
                        InternalReference(kind="opportunity", reference_id=other_opportunity),
                    ),
                ),
            )
            session.commit()
            assert changed_cannibalization.created and changed_cannibalization.analysis.version == 3

    def test_caller_owns_commit(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id, idea_id = seed_opportunity_with_selected_idea(session)
            SearchIntentService(session).compose_deterministic(
                opportunity_id, idea_id=idea_id, composition=COMPOSITION
            )
            session.rollback()
        with open_session(session_factory) as session:
            assert session.execute(select(SearchIntentAnalysis)).scalar_one_or_none() is None


class TestSynthesis:
    def test_ai_success(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id, idea_id = seed_opportunity_with_selected_idea(session)
            signal_id = note_signal(session)
            provider = FakeStructuredProvider(payload=SYNTH_PAYLOAD)
            result = SearchIntentService(session).synthesize(
                opportunity_id,
                idea_id=idea_id,
                provider=provider,
                signal_ids=[signal_id],
            )
            session.commit()

            assert result.status is GenerationStatus.SUCCEEDED
            assert result.attempt_created and result.analysis_created
            assert result.attempt.purpose is GenerationPurpose.INTENT_SYNTHESIS
            analysis = result.analysis
            assert analysis is not None
            assert analysis.synthesis_attempt_id == result.attempt.id
            # Model fills ONLY semantic fields; system facts stay derived.
            assert analysis.primary_intent == SYNTH_PAYLOAD["primary_intent"]
            assert analysis.target_audience == "Küçük çocuklu ebeveynler"
            assert analysis.known_signal_refs[0]["signal_id"] == str(signal_id)
            assert "search_volume" in analysis.missing_signals
            assert analysis.cannibalization_status is CannibalizationStatus.NOT_CHECKED
            opportunity = OpportunityRepository(session).get_by_id(opportunity_id)
            assert opportunity is not None
            events = WorkflowRepository(session).list_events(opportunity.work_item_id)
            assert len(events) == 1

    def test_ai_validation_failure(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id, idea_id = seed_opportunity_with_selected_idea(session)
            result = SearchIntentService(session).synthesize(
                opportunity_id,
                idea_id=idea_id,
                provider=FakeStructuredProvider(payload={"primary_intent": ""}),
            )
            session.commit()
            assert result.status is GenerationStatus.VALIDATION_FAILED
            assert result.analysis is None
            assert session.execute(select(SearchIntentAnalysis)).scalar_one_or_none() is None

    def test_ai_system_fact_fields_are_schema_rejected(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, idea_id = seed_opportunity_with_selected_idea(session)
            tampered = dict(SYNTH_PAYLOAD)
            tampered["missing_signals"] = []
            result = SearchIntentService(session).synthesize(
                opportunity_id,
                idea_id=idea_id,
                provider=FakeStructuredProvider(payload=tampered),
            )
            assert result.status is GenerationStatus.VALIDATION_FAILED
            assert result.attempt.error_class == "schema_validation"

    @pytest.mark.parametrize(
        ("kind", "status"),
        [
            (ProviderFailureKind.PROVIDER_ERROR, GenerationStatus.PROVIDER_ERROR),
            (ProviderFailureKind.TIMEOUT, GenerationStatus.TIMEOUT),
            (ProviderFailureKind.CANCELLED, GenerationStatus.CANCELLED),
        ],
    )
    def test_ai_provider_failures(
        self,
        session_factory: sessionmaker[Session],
        kind: ProviderFailureKind,
        status: GenerationStatus,
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, idea_id = seed_opportunity_with_selected_idea(session)
            result = SearchIntentService(session).synthesize(
                opportunity_id,
                idea_id=idea_id,
                provider=FakeStructuredProvider(failure=kind, failure_class="upstream"),
            )
            session.commit()
            assert result.status is status
            assert result.analysis is None

    def test_ai_exact_retry_reuses_analysis(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id, idea_id = seed_opportunity_with_selected_idea(session)
            provider = FakeStructuredProvider(payload=SYNTH_PAYLOAD)
            service = SearchIntentService(session)
            first = service.synthesize(opportunity_id, idea_id=idea_id, provider=provider)
            session.commit()
            second = service.synthesize(opportunity_id, idea_id=idea_id, provider=provider)
            assert provider.invocations == 1
            assert second.attempt.id == first.attempt.id
            assert second.analysis is not None and first.analysis is not None
            assert second.analysis.id == first.analysis.id
            assert second.attempt_created is False and second.analysis_created is False
            rows = list(session.execute(select(SearchIntentAnalysis)).scalars())
            assert len(rows) == 1

    def test_ai_pathological_reused_attempt(
        self,
        session_factory: sessionmaker[Session],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, idea_id = seed_opportunity_with_selected_idea(session)
            provider = FakeStructuredProvider(payload=SYNTH_PAYLOAD)
            service = SearchIntentService(session)

            def explode(*args: Any, **kwargs: Any) -> Any:
                raise RuntimeError("materialization interrupted")

            monkeypatch.setattr(SearchIntentService, "_persist", explode)
            with pytest.raises(RuntimeError):
                service.synthesize(opportunity_id, idea_id=idea_id, provider=provider)
            session.commit()
            monkeypatch.undo()
            assert provider.invocations == 1

            with pytest.raises(IncompleteAnalysisMaterializationError):
                service.synthesize(opportunity_id, idea_id=idea_id, provider=provider)
            assert provider.invocations == 1
            assert len(list(session.execute(select(AiGenerationAttempt)).scalars())) == 1

            recovered = service.synthesize(
                opportunity_id, idea_id=idea_id, provider=provider, retry_number=1
            )
            session.commit()
            assert recovered.status is GenerationStatus.SUCCEEDED
            assert recovered.analysis is not None
            assert provider.invocations == 2

    def test_wrong_purpose_or_status_attempt_rejected(self) -> None:
        opportunity_id = uuid.uuid4()
        idea_id = uuid.uuid4()
        good_refs = {
            "schema": "search-intent-synthesis/1",
            "opportunity_id": str(opportunity_id),
            "idea_id": str(idea_id),
        }

        def attempt(**overrides: Any) -> AiGenerationAttempt:
            values: dict[str, Any] = {
                "purpose": GenerationPurpose.INTENT_SYNTHESIS,
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

        _validate_synthesis_attempt(attempt(), opportunity_id, idea_id)
        with pytest.raises(InvalidSynthesisAttemptError, match="purpose"):
            _validate_synthesis_attempt(
                attempt(purpose=GenerationPurpose.IDEA_CANDIDATES),
                opportunity_id,
                idea_id,
            )
        with pytest.raises(InvalidSynthesisAttemptError, match="SUCCEEDED"):
            _validate_synthesis_attempt(
                attempt(status=GenerationStatus.VALIDATION_FAILED),
                opportunity_id,
                idea_id,
            )
        with pytest.raises(InvalidSynthesisAttemptError, match="provenance"):
            _validate_synthesis_attempt(attempt(), uuid.uuid4(), idea_id)


class TestIsolationAndImmutability:
    def test_no_side_effects(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id, idea_id = seed_opportunity_with_selected_idea(session)
            signal_id = note_signal(session)
            SearchIntentService(session).compose_deterministic(
                opportunity_id,
                idea_id=idea_id,
                composition=COMPOSITION,
                signal_ids=[signal_id],
            )
            session.commit()
            opportunity = OpportunityRepository(session).get_by_id(opportunity_id)
            assert opportunity is not None
            assert opportunity.disposition.value == "open"
            assert OpportunityRepository(session).list_scores(opportunity_id) == []
            assert session.execute(select(EvidencePack)).scalar_one_or_none() is None
            assert session.execute(select(ResearchEvidence)).scalar_one_or_none() is None
            # The consumed signal row is untouched.
            signal = session.get(SearchSignal, signal_id)
            assert signal is not None and signal.value == {"note": "Operatör niyet notu."}
            idea_rows = list(session.execute(select(Idea)).scalars())
            assert len(idea_rows) == 1

    def test_repository_exposes_no_update_or_delete_surface(self) -> None:
        exposed = {name for name in dir(SearchIntentRepository) if not name.startswith("_")}
        assert not any("update" in name or "delete" in name for name in exposed)

    def test_semantic_field_bounds(self) -> None:
        with pytest.raises(InvalidAnalysisInputError, match="primary_intent"):
            IntentComposition(primary_intent="  ", page_purpose="x", likely_format="x").cleaned()
        with pytest.raises(InvalidAnalysisInputError, match="duplicate"):
            IntentComposition(
                primary_intent="x",
                page_purpose="x",
                likely_format="x",
                query_concepts=("aynı", "aynı"),
            ).cleaned()
        with pytest.raises(InvalidAnalysisInputError, match="limit"):
            IntentComposition(
                primary_intent="x" * 201, page_purpose="x", likely_format="x"
            ).cleaned()
