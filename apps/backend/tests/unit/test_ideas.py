"""Idea persistence, originality guards, and selection tests (real services)."""

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
from contentos.ideas.enums import (
    ContentType,
    IdeaOrigin,
    IdeaSelectionAction,
    OriginalityStatus,
)
from contentos.ideas.errors import (
    FakeUgcRejectionError,
    IdeaNotFoundError,
    InvalidIdeaInputError,
    InvalidPlanningDimensionsError,
    InvalidSelectionError,
    SelectionConflictError,
)
from contentos.ideas.models import Idea, IdeaSelectionEvent
from contentos.ideas.policy import DEFAULT_IDEA_ORIGINALITY_POLICY, IdeaOriginalityPolicy
from contentos.ideas.repository import IdeaRepository
from contentos.ideas.service import IdeaService
from contentos.normalization.service import NormalizationService
from contentos.opportunities.enums import OpportunityActor, ResearchInputRole
from contentos.opportunities.errors import OpportunityNotFoundError
from contentos.opportunities.models import OpportunityResearchInput
from contentos.opportunities.repository import OpportunityRepository
from contentos.opportunities.service import ResearchPromotionService
from contentos.research.models import ResearchEvidence
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
    session: Session, specs: list[tuple[str, str | None]]
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """Seed one opportunity from (source_key, document_title) specs.

    The first spec is the promotion root; specs sharing a source_key share
    ONE registered Source, so source diversity is derived, never claimed.
    """
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
    return promo.opportunity_id, document_ids


def default_opportunity(session: Session) -> uuid.UUID:
    opportunity_id, _ = make_opportunity(
        session,
        [
            ("ana-kaynak", "Doğum günü partisi fikirleri ve önerileri"),
            ("destek-kaynak", "Ev partisi süsleme örnekleri"),
        ],
    )
    return opportunity_id


def idea_kwargs(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "working_title": "Evde balon temalı doğum günü planı",
        "angle": "Bütçe dostu üç saatlik hazırlık akışına odaklanıyoruz.",
        "audience": "Küçük çocuklu ebeveynler",
        "value_proposition": "Tek listeyle eksiksiz parti hazırlığı sağlar.",
        "rationale": "Kaynaklar genel kalıyor; biz uygulanabilir zaman çizelgesi veriyoruz.",
        "content_type": ContentType.PLANNING_GUIDE,
    }
    values.update(overrides)
    return values


class TestIdeaCreation:
    def test_create_operator_idea_v1(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            idea = IdeaService(session).create_operator_idea(opportunity_id, **idea_kwargs())
            session.commit()

            assert idea.version == 1
            assert idea.opportunity_id == opportunity_id
            assert isinstance(idea.logical_idea_id, uuid.UUID)
            assert idea.origin is IdeaOrigin.OPERATOR
            assert idea.content_type is ContentType.PLANNING_GUIDE
            # Locale/market derive from the parent editorial context.
            assert idea.locale == "tr-TR"
            assert idea.market == "TR"
            assert idea.originality_status is OriginalityStatus.PASSED
            snapshot = idea.originality_policy_snapshot
            assert snapshot["policy_name"] == "default"
            assert snapshot["policy_version"] == "1"
            assert idea.planning_dimensions == {"schema_version": 1, "dimensions": {}}
            assert idea.exclusions == []

    def test_multiple_independent_candidates(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            service = IdeaService(session)
            first = service.create_operator_idea(opportunity_id, **idea_kwargs())
            second = service.create_operator_idea(
                opportunity_id,
                **idea_kwargs(working_title="Bahçede yaz temalı doğum günü rehberi"),
            )
            session.commit()
            assert first.logical_idea_id != second.logical_idea_id
            assert first.version == 1 and second.version == 1
            # Similar independent candidates are never globally deduped.
            third = service.create_operator_idea(opportunity_id, **idea_kwargs())
            session.commit()
            assert third.logical_idea_id != first.logical_idea_id

    def test_missing_opportunity(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            with pytest.raises(OpportunityNotFoundError):
                IdeaService(session).create_operator_idea(uuid.uuid4(), **idea_kwargs())

    def test_planning_dimensions_and_exclusions_persist(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            idea = IdeaService(session).create_operator_idea(
                opportunity_id,
                **idea_kwargs(
                    exclusions=["fiyat garantisi verme", "marka önerme", "fiyat garantisi verme"],
                    planning_dimensions={
                        "theme": "balonlar ve pastel tonlar",
                        "color_palette": ["pembe", "mint yeşili"],
                        "practical_steps": ["balonları şişir", "masayı hazırla"],
                        "budget_band": "orta bütçe",
                    },
                ),
            )
            session.commit()
            # Deterministic dedupe preserves meaningful operator order.
            assert idea.exclusions == ["fiyat garantisi verme", "marka önerme"]
            assert idea.planning_dimensions["schema_version"] == 1
            dims = idea.planning_dimensions["dimensions"]
            assert dims["color_palette"] == ["pembe", "mint yeşili"]
            assert dims["budget_band"] == "orta bütçe"


class TestRevision:
    def test_revision_creates_next_version_and_leaves_v1_untouched(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            service = IdeaService(session)
            v1 = service.create_operator_idea(opportunity_id, **idea_kwargs())
            session.commit()
            v2 = service.revise_operator_idea(
                v1.id,
                **idea_kwargs(working_title="Evde balon temalı parti: saat saat plan"),
            )
            session.commit()

            assert v2.logical_idea_id == v1.logical_idea_id
            assert v2.opportunity_id == v1.opportunity_id
            assert v2.version == 2
            assert v2.id != v1.id
            v1_reread = IdeaRepository(session).get_idea(v1.id)
            assert v1_reread is not None
            assert v1_reread.working_title == "Evde balon temalı doğum günü planı"
            assert v1_reread.version == 1
            versions = IdeaRepository(session).list_versions(v1.logical_idea_id)
            assert [idea.version for idea in versions] == [1, 2]

    def test_revising_one_candidate_does_not_touch_another(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            service = IdeaService(session)
            first = service.create_operator_idea(opportunity_id, **idea_kwargs())
            second = service.create_operator_idea(
                opportunity_id,
                **idea_kwargs(working_title="Bahçede yaz temalı doğum günü rehberi"),
            )
            session.commit()
            service.revise_operator_idea(
                second.id, **idea_kwargs(working_title="Bahçede yaz partisi: yeni akış")
            )
            session.commit()
            assert IdeaRepository(session).max_version(first.logical_idea_id) == 1
            assert IdeaRepository(session).max_version(second.logical_idea_id) == 2

    def test_revision_of_missing_idea(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            with pytest.raises(IdeaNotFoundError):
                IdeaService(session).revise_operator_idea(uuid.uuid4(), **idea_kwargs())

    def test_revision_stays_on_its_own_opportunity(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            first_opportunity = default_opportunity(session)
            second_opportunity = default_opportunity(session)
            service = IdeaService(session)
            idea = service.create_operator_idea(first_opportunity, **idea_kwargs())
            session.commit()
            revised = service.revise_operator_idea(
                idea.id, **idea_kwargs(working_title="Aynı fırsatta kalan revizyon")
            )
            session.commit()
            assert revised.opportunity_id == first_opportunity
            assert revised.opportunity_id != second_opportunity


class TestContentTypes:
    def test_all_accepted_content_types_persist(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            service = IdeaService(session)
            for content_type in ContentType:
                idea = service.create_operator_idea(
                    opportunity_id, **idea_kwargs(content_type=content_type)
                )
                assert idea.content_type is content_type
            session.commit()
            stored = {
                idea.content_type for idea in IdeaRepository(session).list_ideas(opportunity_id)
            }
            assert stored == set(ContentType)

    def test_free_form_content_type_rejected(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            with pytest.raises(InvalidIdeaInputError, match="editorial choice"):
                IdeaService(session).create_operator_idea(
                    opportunity_id, **idea_kwargs(content_type="listicle")
                )


class TestFieldValidation:
    @pytest.mark.parametrize(
        "field",
        ["working_title", "angle", "audience", "value_proposition", "rationale"],
    )
    def test_blank_required_fields_rejected(
        self, session_factory: sessionmaker[Session], field: str
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            with pytest.raises(InvalidIdeaInputError, match=field):
                IdeaService(session).create_operator_idea(
                    opportunity_id, **idea_kwargs(**{field: "   "})
                )

    def test_oversized_fields_rejected(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            with pytest.raises(InvalidIdeaInputError, match="working_title"):
                IdeaService(session).create_operator_idea(
                    opportunity_id, **idea_kwargs(working_title="u" * 201)
                )
            with pytest.raises(InvalidIdeaInputError, match="angle"):
                IdeaService(session).create_operator_idea(
                    opportunity_id, **idea_kwargs(angle="u" * 2001)
                )

    def test_bad_exclusions_rejected(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            service = IdeaService(session)
            for bad in (
                "not-a-list",
                ["ok", "  "],
                ["ok", 5],
                ["x" * 301],
                [f"madde {i}" for i in range(21)],
            ):
                with pytest.raises(InvalidIdeaInputError):
                    service.create_operator_idea(opportunity_id, **idea_kwargs(exclusions=bad))

    def test_bad_planning_dimensions_rejected(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            service = IdeaService(session)
            for bad in (
                ["not-a-dict"],
                {"vendor_data": "x"},
                {"theme": 5},
                {"theme": float("nan")},
                {"budget_band": float("inf")},
                {"theme": {"nested": "map"}},
                {"color_palette": "not-a-list"},
                {"color_palette": [f"renk {i}" for i in range(13)]},
                {"menu": ["ok", ""]},
                {"theme": "x" * 201},
            ):
                with pytest.raises(InvalidPlanningDimensionsError):
                    service.create_operator_idea(
                        opportunity_id, **idea_kwargs(planning_dimensions=bad)
                    )


class TestOriginality:
    def test_distinct_title_passes_with_recorded_detail(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            idea = IdeaService(session).create_operator_idea(opportunity_id, **idea_kwargs())
            session.commit()
            checks = idea.originality_detail["checks"]
            assert checks["title_similarity"]["status"] == "passed"
            assert checks["title_similarity"]["titles_checked"] == 2
            assert checks["title_similarity"]["threshold"] == 0.90
            assert checks["source_diversity"] == {
                "status": "passed",
                "distinct_sources": 2,
                "required": 2,
            }
            assert checks["fake_ugc"]["status"] == "passed"

    def test_near_copy_title_records_failed_originality(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, document_ids = make_opportunity(
                session,
                [
                    ("ana-kaynak", "Doğum günü partisi fikirleri ve önerileri"),
                    ("destek-kaynak", "Ev partisi süsleme örnekleri"),
                ],
            )
            idea = IdeaService(session).create_operator_idea(
                opportunity_id,
                **idea_kwargs(working_title="Doğum günü partisi fikirleri ve önerileri"),
            )
            session.commit()
            # The near-copy is recorded as a failure — never silently
            # rewritten, never hidden, and the source is never modified.
            assert idea.originality_status is OriginalityStatus.FAILED
            title_check = idea.originality_detail["checks"]["title_similarity"]
            assert title_check["status"] == "failed"
            assert title_check["max_similarity"] == 1.0
            assert title_check["most_similar_document_id"] == str(document_ids[0])
            assert title_check["threshold"] == 0.90

    def test_missing_titles_stay_not_checkable(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, document_ids = make_opportunity(
                session, [("ana-kaynak", None), ("destek-kaynak", None)]
            )
            idea = IdeaService(session).create_operator_idea(opportunity_id, **idea_kwargs())
            session.commit()
            # "Could not evaluate" is never promoted to a pass.
            assert idea.originality_status is OriginalityStatus.NOT_CHECKABLE
            title_check = idea.originality_detail["checks"]["title_similarity"]
            assert title_check["status"] == "not_checkable"
            assert sorted(title_check["skipped_documents"]) == sorted(
                str(document_id) for document_id in document_ids
            )

    def test_partial_titles_are_evaluated_and_skips_recorded(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, document_ids = make_opportunity(
                session,
                [("ana-kaynak", "Doğum günü partisi fikirleri"), ("destek-kaynak", None)],
            )
            idea = IdeaService(session).create_operator_idea(opportunity_id, **idea_kwargs())
            session.commit()
            title_check = idea.originality_detail["checks"]["title_similarity"]
            assert title_check["status"] == "passed"
            assert title_check["titles_checked"] == 1
            assert title_check["skipped_documents"] == [str(document_ids[1])]

    def test_source_diversity_counts_sources_not_documents(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, _ = make_opportunity(
                session,
                [
                    ("tek-kaynak", "Parti fikirleri birinci yazı"),
                    ("tek-kaynak", "Parti fikirleri ikinci yazı"),
                    ("tek-kaynak", "Parti fikirleri üçüncü yazı"),
                ],
            )
            idea = IdeaService(session).create_operator_idea(opportunity_id, **idea_kwargs())
            session.commit()
            assert idea.originality_status is OriginalityStatus.FAILED
            source_check = idea.originality_detail["checks"]["source_diversity"]
            assert source_check == {
                "status": "failed",
                "distinct_sources": 1,
                "required": 2,
            }

    def test_policy_is_explicit_and_changes_the_result(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, _ = make_opportunity(
                session, [("tek-kaynak", "Parti fikirleri birinci yazı")]
            )
            relaxed = IdeaOriginalityPolicy(
                name="default",
                version="1-single-source-test",
                min_distinct_sources=1,
                title_similarity_failure_threshold=0.90,
            )
            idea = IdeaService(session).create_operator_idea(
                opportunity_id, **idea_kwargs(), policy=relaxed
            )
            session.commit()
            assert idea.originality_status is OriginalityStatus.PASSED
            snapshot = idea.originality_policy_snapshot
            assert snapshot["policy_version"] == "1-single-source-test"
            assert snapshot["min_distinct_sources"] == 1
            assert "not universal editorial truth" in snapshot["note"]

    def test_default_policy_is_named_and_versioned(self) -> None:
        assert DEFAULT_IDEA_ORIGINALITY_POLICY.name == "default"
        assert DEFAULT_IDEA_ORIGINALITY_POLICY.version == "1"
        snapshot = DEFAULT_IDEA_ORIGINALITY_POLICY.snapshot()
        assert snapshot["title_similarity_failure_threshold"] == 0.90
        assert snapshot["fake_ugc_patterns"]


class TestFakeUgcGuard:
    @pytest.mark.parametrize(
        ("field", "text"),
        [
            ("working_title", "Gerçek kullanıcı yorumları ile parti fikirleri"),
            ("angle", "Annelerden tavsiyeler derledik ve sıraladık."),
            ("rationale", "Müşteri yorumları bölümü içerecek şekilde planlandı."),
            ("value_proposition", "Kullanıcı puanları ile desteklenen öneriler."),
        ],
    )
    def test_fake_ugc_claims_are_hard_rejected_with_no_row(
        self, session_factory: sessionmaker[Session], field: str, text: str
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            with pytest.raises(FakeUgcRejectionError):
                IdeaService(session).create_operator_idea(
                    opportunity_id, **idea_kwargs(**{field: text})
                )
            session.rollback()
            assert session.execute(select(Idea)).scalar_one_or_none() is None

    def test_ordinary_editorial_wording_does_not_false_trigger(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            idea = IdeaService(session).create_operator_idea(
                opportunity_id,
                **idea_kwargs(
                    angle="Uzman kaynaklara dayanan pratik bir hazırlık akışı sunuyoruz.",
                ),
            )
            session.commit()
            assert idea.originality_detail["checks"]["fake_ugc"]["status"] == "passed"


class TestSelection:
    def test_selection_pins_exact_version_across_revisions(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            service = IdeaService(session)
            v1 = service.create_operator_idea(opportunity_id, **idea_kwargs())
            session.commit()
            service.select_idea(v1.id, reason="en uygulanabilir aday")
            session.commit()

            v2 = service.revise_operator_idea(
                v1.id, **idea_kwargs(working_title="Evde balon temalı parti: yeni akış")
            )
            session.commit()
            # Revision NEVER silently retargets the selection.
            effective = service.get_effective_selection(opportunity_id)
            assert effective is not None and effective.id == v1.id

            service.select_idea(v2.id, reason="revize sürüm daha net")
            session.commit()
            effective = service.get_effective_selection(opportunity_id)
            assert effective is not None and effective.id == v2.id
            # History (including v1's events) remains.
            events = IdeaRepository(session).list_selection_events(opportunity_id)
            assert [event.idea_id for event in events] == [v1.id, v2.id]

    def test_multi_candidate_selection_state_machine(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            service = IdeaService(session)
            a = service.create_operator_idea(opportunity_id, **idea_kwargs())
            b = service.create_operator_idea(
                opportunity_id,
                **idea_kwargs(working_title="Bahçede yaz temalı doğum günü rehberi"),
            )
            session.commit()

            service.select_idea(a.id, reason="ilk tercih")
            session.commit()
            assert service.get_effective_selection(opportunity_id).id == a.id  # type: ignore[union-attr]

            service.select_idea(b.id, reason="daha güçlü açı")
            session.commit()
            assert service.get_effective_selection(opportunity_id).id == b.id  # type: ignore[union-attr]

            # Deselecting A while B is effective is a typed conflict.
            with pytest.raises(SelectionConflictError):
                service.deselect_idea(a.id, reason="geçersiz komut")

            service.deselect_idea(b.id, reason="yeniden değerlendirme")
            session.commit()
            # Nothing is effective; A does NOT silently resurrect.
            assert service.get_effective_selection(opportunity_id) is None

            with pytest.raises(SelectionConflictError):
                service.deselect_idea(a.id, reason="seçili değilken bırakma")

    def test_selection_idempotency(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            service = IdeaService(session)
            idea = service.create_operator_idea(opportunity_id, **idea_kwargs())
            session.commit()
            first = service.select_idea(idea.id, reason="en uygulanabilir aday")
            session.commit()
            retry = service.select_idea(idea.id, reason="tekrar komutu")
            assert first.created is True
            assert retry.created is False
            assert retry.event.id == first.event.id
            events = IdeaRepository(session).list_selection_events(opportunity_id)
            assert len(events) == 1

    def test_selection_history_is_auditable(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            service = IdeaService(session)
            idea = service.create_operator_idea(opportunity_id, **idea_kwargs())
            session.commit()
            created_at = idea.created_at
            service.select_idea(
                idea.id, reason="en uygulanabilir aday", request_id="req-idea-select-1"
            )
            service.deselect_idea(idea.id, reason="kapsam daraltıldı")
            session.commit()

            events = IdeaRepository(session).list_selection_events(opportunity_id)
            assert [event.action.value for event in events] == ["selected", "deselected"]
            assert events[0].reason == "en uygulanabilir aday"
            assert events[0].request_id == "req-idea-select-1"
            assert events[0].actor_origin.value == "operator"
            assert all(event.idea_id == idea.id for event in events)
            # Selection never mutates the idea row itself.
            reread = IdeaRepository(session).get_idea(idea.id)
            assert reread is not None and reread.created_at == created_at
            # The vocabulary contains no publication-approval semantics.
            assert {action.value for action in IdeaSelectionAction} == {
                "selected",
                "deselected",
            }

    def test_selection_input_validation(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            service = IdeaService(session)
            idea = service.create_operator_idea(opportunity_id, **idea_kwargs())
            session.commit()
            with pytest.raises(InvalidSelectionError):
                service.select_idea(idea.id, reason="   ")
            with pytest.raises(InvalidSelectionError):
                service.select_idea(idea.id, reason="ok", request_id="bad id!")
            with pytest.raises(IdeaNotFoundError):
                service.select_idea(uuid.uuid4(), reason="yok")


class TestIsolationAndImmutability:
    def test_no_side_effects_on_workflow_disposition_or_scores(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            service = IdeaService(session)
            idea = service.create_operator_idea(opportunity_id, **idea_kwargs())
            session.commit()
            service.select_idea(idea.id, reason="tek aday")
            service.deselect_idea(idea.id, reason="yeniden bakılacak")
            session.commit()

            opportunity = OpportunityRepository(session).get_by_id(opportunity_id)
            assert opportunity is not None
            assert opportunity.disposition.value == "open"
            assert OpportunityRepository(session).list_scores(opportunity_id) == []
            events = WorkflowRepository(session).list_events(opportunity.work_item_id)
            assert len(events) == 1

    def test_repository_exposes_no_update_or_delete_surface(self) -> None:
        exposed = {name for name in dir(IdeaRepository) if not name.startswith("_")}
        assert not any("update" in name or "delete" in name for name in exposed)

    def test_idea_is_not_evidence(self) -> None:
        # No idea FK belongs inside ResearchEvidence (ADR 0007 intact).
        research_columns = {column.name for column in ResearchEvidence.__table__.columns}
        assert not any("idea" in name for name in research_columns)
        # Idea rows copy no source text.
        idea_columns = {column.name for column in Idea.__table__.columns}
        assert "clean_text" not in idea_columns
        assert "evidence_text" not in idea_columns

    def test_caller_owns_commit(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id = default_opportunity(session)
            IdeaService(session).create_operator_idea(opportunity_id, **idea_kwargs())
            session.rollback()
        with open_session(session_factory) as session:
            assert session.execute(select(Idea)).scalar_one_or_none() is None
            assert session.execute(select(IdeaSelectionEvent)).scalar_one_or_none() is None
