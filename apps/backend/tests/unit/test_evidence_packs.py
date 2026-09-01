"""EvidencePack foundation tests (real services over SQLite)."""

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
from contentos.evidence_packs.enums import (
    ContradictionResolutionStatus,
    ContradictionResolver,
    ContradictionSeverity,
    EvidenceItemRole,
    EvidencePackSufficiency,
)
from contentos.evidence_packs.errors import (
    EvidenceNotEligibleError,
    InvalidContradictionError,
    InvalidPackInputError,
    PackNotFoundError,
)
from contentos.evidence_packs.models import EvidencePack, EvidencePackItem
from contentos.evidence_packs.policy import (
    DEFAULT_EVIDENCE_POLICY,
    EvidenceSufficiencyPolicy,
)
from contentos.evidence_packs.repository import EvidencePackRepository
from contentos.evidence_packs.service import (
    ContradictionDeclaration,
    EvidencePackService,
    EvidenceSelection,
)
from contentos.fetching.models import (
    FetchOutcome,
    FetchResult,
    RetryClassification,
    RobotsDecision,
)
from contentos.fetching.snapshot_service import FetchSnapshotService
from contentos.ideas.enums import ContentType
from contentos.ideas.models import Idea
from contentos.ideas.service import IdeaService
from contentos.normalization.service import NormalizationService
from contentos.opportunities.enums import OpportunityActor, ResearchInputRole
from contentos.opportunities.errors import OpportunityNotFoundError
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


def seed_document(
    session: Session,
    slug: str,
    *,
    trust_tier: TrustTier = TrustTier.GENERAL,
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
    )
    session.commit()
    return document.id


def record_decision(session: Session, document_id: uuid.UUID) -> uuid.UUID:
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
    session.commit()
    return decision.id


def add_evidence(
    session: Session,
    document_id: uuid.UUID,
    statement: str,
    *,
    licensing_notes: str | None = None,
) -> uuid.UUID:
    evidence = ResearchEvidenceService(session).record_evidence(
        document_id,
        evidence_type=EvidenceType.OBSERVATION,
        statement=statement,
        extraction_method=ExtractionMethod.MACHINE,
        source_locator="structured_metadata.author",
        licensing_notes=licensing_notes,
    )
    session.commit()
    return evidence.id


def build_opportunity(
    session: Session, *, second_source: bool = True
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    root_doc = seed_document(session, f"paket-{uuid.uuid4().hex[:8]}")
    record_decision(session, root_doc)
    promo = ResearchPromotionService(session).promote_research(root_doc)
    session.commit()
    evidence_ids = [
        add_evidence(session, root_doc, "Kaynak, konsept detaylarını belirtiyor."),
        add_evidence(session, root_doc, "Kaynak, hazırlık süresini belirtiyor."),
    ]
    if second_source:
        support_doc = seed_document(
            session, f"destek-{uuid.uuid4().hex[:8]}", trust_tier=TrustTier.REPUTABLE
        )
        support_decision = record_decision(session, support_doc)
        OpportunityRepository(session).insert_research_input(
            OpportunityResearchInput(
                opportunity_id=promo.opportunity_id,
                normalized_document_id=support_doc,
                duplicate_decision_id=support_decision,
                role=ResearchInputRole.SUPPORTING,
                added_by=OpportunityActor.OPERATOR,
                note=None,
                added_at=NOW,
            )
        )
        session.commit()
        evidence_ids.append(
            add_evidence(session, support_doc, "İkinci kaynak, bütçe aralığını doğruluyor.")
        )
    return promo.opportunity_id, evidence_ids


def selections_for(
    evidence_ids: list[uuid.UUID], *, key_fact_first: bool = True
) -> list[EvidenceSelection]:
    selections = []
    for index, evidence_id in enumerate(evidence_ids):
        role = (
            EvidenceItemRole.KEY_FACT
            if key_fact_first and index == 0
            else EvidenceItemRole.SUPPORTING
        )
        selections.append(
            EvidenceSelection(
                research_evidence_id=evidence_id,
                role=role,
                claim_cluster="konsept-detaylari",
            )
        )
    return selections


def make_idea(session: Session, opportunity_id: uuid.UUID, *, title_suffix: str = "") -> Idea:
    idea = IdeaService(session).create_operator_idea(
        opportunity_id,
        working_title=f"Evde balon temalı doğum günü planı{title_suffix}",
        angle="Bütçe dostu üç saatlik hazırlık akışına odaklanıyoruz.",
        audience="Küçük çocuklu ebeveynler",
        value_proposition="Tek listeyle eksiksiz parti hazırlığı sağlar.",
        rationale="Kaynaklar genel kalıyor; biz uygulanabilir plan veriyoruz.",
        content_type=ContentType.PLANNING_GUIDE,
    )
    session.commit()
    return idea


def blocking_declaration(side_a: uuid.UUID, side_b: uuid.UUID) -> ContradictionDeclaration:
    return ContradictionDeclaration(
        claim_key="hazirlik-suresi",
        evidence_side_a=(side_a,),
        evidence_side_b=(side_b,),
        nature="Kaynaklar hazırlık süresi konusunda çelişiyor.",
        severity=ContradictionSeverity.BLOCKING,
    )


class TestAssembly:
    def test_assembly_creates_ready_pack_with_full_context(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, evidence_ids = build_opportunity(session)
            result = EvidencePackService(session).assemble_pack(
                opportunity_id, selections_for(evidence_ids)
            )
            session.commit()

            assert result.created is True
            pack = result.pack
            assert pack.version == 1
            assert pack.assembler_name == "evidence-pack-assembler"
            assert pack.sufficiency is EvidencePackSufficiency.READY
            assert pack.sufficiency_detail["missing"] == []
            assert pack.sufficiency_detail["policy_name"] == "default"
            assert pack.sufficiency_detail["policy_version"] == "1"
            assert pack.source_diversity["distinct_sources"] == 2
            assert pack.policy_snapshot["policy_name"] == "default"
            assert pack.policy_snapshot["min_evidence_items"] == 3
            assert pack.policy_snapshot["staleness_days"] == 180
            # The WHOLE semantic identity is stored and hashed: selections,
            # exact policy snapshot, and contradiction state.
            snapshot = pack.assembly_input_snapshot
            assert snapshot["policy"] == pack.policy_snapshot
            assert len(snapshot["selections"]) == 3
            assert snapshot["contradictions"] == []
            assert len(pack.assembly_input_hash) == 64

            items = EvidencePackRepository(session).list_items(pack.id)
            assert {item.research_evidence_id for item in items} == set(evidence_ids)

    def test_no_evidence_text_field_exists(self) -> None:
        columns = {column.name for column in EvidencePackItem.__table__.columns}
        assert "evidence_text" not in columns
        assert "statement" not in columns
        assert "excerpt" not in columns

    def test_licensing_cautions_travel_with_the_pack(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            root_doc = seed_document(session, "ref-kaynak", trust_tier=TrustTier.REFERENCE_ONLY)
            record_decision(session, root_doc)
            promo = ResearchPromotionService(session).promote_research(root_doc)
            session.commit()
            evidence_id = add_evidence(
                session,
                root_doc,
                "Referans kaynak bir iddia belirtiyor.",
                licensing_notes="yalnızca referans; ifade yeniden kullanılamaz",
            )
            result = EvidencePackService(session).assemble_pack(
                promo.opportunity_id,
                [
                    EvidenceSelection(
                        research_evidence_id=evidence_id,
                        role=EvidenceItemRole.KEY_FACT,
                        claim_cluster="iddia",
                    )
                ],
            )
            session.commit()
            cautions = result.pack.licensing_cautions
            assert any("reference_only" in c.get("caution", "") for c in cautions)
            assert any(
                c.get("caution") == "yalnızca referans; ifade yeniden kullanılamaz"
                for c in cautions
            )

    def test_evidence_outside_the_opportunity_inputs_is_rejected(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, _ = build_opportunity(session, second_source=False)
            foreign_doc = seed_document(session, "yabanci-kaynak")
            record_decision(session, foreign_doc)
            foreign_evidence = add_evidence(session, foreign_doc, "Bu kanıt başka bir belgeye ait.")
            with pytest.raises(EvidenceNotEligibleError):
                EvidencePackService(session).assemble_pack(
                    opportunity_id,
                    [
                        EvidenceSelection(
                            research_evidence_id=foreign_evidence,
                            role=EvidenceItemRole.KEY_FACT,
                            claim_cluster="kume",
                        )
                    ],
                )

    def test_selection_and_declaration_validation(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, evidence_ids = build_opportunity(session)
            service = EvidencePackService(session)
            with pytest.raises(InvalidPackInputError):
                service.assemble_pack(opportunity_id, [])
            with pytest.raises(InvalidPackInputError, match="twice"):
                service.assemble_pack(
                    opportunity_id,
                    [
                        EvidenceSelection(evidence_ids[0], EvidenceItemRole.KEY_FACT, "k"),
                        EvidenceSelection(evidence_ids[0], EvidenceItemRole.SUPPORTING, "k"),
                    ],
                )
            with pytest.raises(OpportunityNotFoundError):
                service.assemble_pack(
                    uuid.uuid4(),
                    [EvidenceSelection(evidence_ids[0], EvidenceItemRole.KEY_FACT, "k")],
                )
            # Declaration sides must reference the selected evidence.
            with pytest.raises(InvalidContradictionError, match="selection"):
                service.assemble_pack(
                    opportunity_id,
                    selections_for(evidence_ids),
                    contradictions=[blocking_declaration(uuid.uuid4(), evidence_ids[0])],
                )
            with pytest.raises(InvalidContradictionError, match="disjoint"):
                service.assemble_pack(
                    opportunity_id,
                    selections_for(evidence_ids),
                    contradictions=[blocking_declaration(evidence_ids[0], evidence_ids[0])],
                )


class TestReproducibility:
    def test_conflicted_version_stays_conflicted_forever(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """The §6 contract: v1 CONFLICTED forever; v2 carries the resolution."""
        with open_session(session_factory) as session:
            opportunity_id, evidence_ids = build_opportunity(session)
            service = EvidencePackService(session)
            v1 = service.assemble_pack(
                opportunity_id,
                selections_for(evidence_ids),
                contradictions=[blocking_declaration(evidence_ids[1], evidence_ids[2])],
            ).pack
            session.commit()
            assert v1.sufficiency is EvidencePackSufficiency.CONFLICTED
            assert v1.sufficiency_detail["unresolved_blocking_contradictions"] == [
                "hazirlik-suresi"
            ]

            [contradiction] = EvidencePackRepository(session).list_contradictions(v1.id)
            service.resolve_contradiction(
                contradiction.id,
                resolution_status=ContradictionResolutionStatus.RESOLVED_CAUTIOUS_WORDING,
                reason="iki süre de aralık olarak verilecek",
            )
            session.commit()

            # Resolution is audited on the row...
            resolved = EvidencePackRepository(session).get_contradiction(contradiction.id)
            assert resolved is not None
            assert resolved.resolved_by is ContradictionResolver.OPERATOR
            assert resolved.resolved_at is not None
            # ...but v1's stored gate meaning NEVER changes.
            v1_reread = EvidencePackRepository(session).get_pack(v1.id)
            assert v1_reread is not None
            assert v1_reread.sufficiency is EvidencePackSufficiency.CONFLICTED

            # An explicit reassembly produces the new version that may be READY.
            v2_result = service.reassemble_pack(v1.id)
            session.commit()
            assert v2_result.created is True
            v2 = v2_result.pack
            assert v2.version == 2
            assert v2.sufficiency is EvidencePackSufficiency.READY
            assert v2.assembly_input_hash != v1.assembly_input_hash

            # v2 is independently explainable: its OWN contradiction row
            # carries the resolved state, frozen at reassembly time.
            [carried] = EvidencePackRepository(session).list_contradictions(v2.id)
            assert carried.id != contradiction.id
            assert carried.claim_key == "hazirlik-suresi"
            assert (
                carried.resolution_status is ContradictionResolutionStatus.RESOLVED_CAUTIOUS_WORDING
            )
            assert carried.resolution_reason == "iki süre de aralık olarak verilecek"
            snapshot_states = v2.assembly_input_snapshot["contradictions"]
            assert snapshot_states[0]["resolution_status"] == "resolved_cautious_wording"

            # And forever after: v1 means CONFLICTED, v2 means READY.
            assert (
                EvidencePackRepository(session).get_pack(v1.id).sufficiency  # type: ignore[union-attr]
                is EvidencePackSufficiency.CONFLICTED
            )

    def test_contradiction_state_participates_in_assembly_identity(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, evidence_ids = build_opportunity(session)
            service = EvidencePackService(session)
            plain = service.assemble_pack(opportunity_id, selections_for(evidence_ids))
            session.commit()
            with_contradiction = service.assemble_pack(
                opportunity_id,
                selections_for(evidence_ids),
                contradictions=[blocking_declaration(evidence_ids[1], evidence_ids[2])],
            )
            session.commit()
            # Same evidence + different contradiction state must NOT dedupe.
            assert with_contradiction.created is True
            assert with_contradiction.pack.id != plain.pack.id
            assert with_contradiction.pack.assembly_input_hash != plain.pack.assembly_input_hash

    def test_reassembly_with_no_semantic_change_is_idempotent(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, evidence_ids = build_opportunity(session)
            service = EvidencePackService(session)
            v1 = service.assemble_pack(opportunity_id, selections_for(evidence_ids)).pack
            session.commit()
            retry = service.reassemble_pack(v1.id)
            assert retry.created is False
            assert retry.pack.id == v1.id

    def test_reassembly_can_add_new_contradictions(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, evidence_ids = build_opportunity(session)
            service = EvidencePackService(session)
            v1 = service.assemble_pack(opportunity_id, selections_for(evidence_ids)).pack
            session.commit()
            assert v1.sufficiency is EvidencePackSufficiency.READY

            v2 = service.reassemble_pack(
                v1.id,
                additional_contradictions=[blocking_declaration(evidence_ids[1], evidence_ids[2])],
            ).pack
            session.commit()
            assert v2.version == 2
            assert v2.sufficiency is EvidencePackSufficiency.CONFLICTED
            # v1 remains READY forever.
            assert (
                EvidencePackRepository(session).get_pack(v1.id).sufficiency  # type: ignore[union-attr]
                is EvidencePackSufficiency.READY
            )

    def test_no_live_sufficiency_helper_exists(self) -> None:
        exposed = {name for name in dir(EvidencePackService) if not name.startswith("_")}
        assert "evaluate_pack_sufficiency" not in exposed
        assert not any("current" in name or "effective" in name for name in exposed)


class TestPolicy:
    def test_policy_change_creates_new_version_and_retry_is_idempotent(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """§2: a policy threshold/version change is a new assembly identity."""
        with open_session(session_factory) as session:
            opportunity_id, evidence_ids = build_opportunity(session)
            service = EvidencePackService(session)
            selections = selections_for(evidence_ids)

            v1 = service.assemble_pack(opportunity_id, selections)
            session.commit()
            assert v1.pack.version == 1

            stricter = EvidenceSufficiencyPolicy(
                name="default",
                version="1-strict-test",
                min_evidence_items=5,
                min_distinct_sources=2,
                min_key_facts=1,
                staleness_days=180,
            )
            v2 = service.assemble_pack(opportunity_id, selections, policy=stricter)
            session.commit()

            assert v2.created is True
            assert v2.pack.version == 2
            assert v2.pack.assembly_input_hash != v1.pack.assembly_input_hash
            # The stricter policy honestly changes the outcome and is pinned.
            assert v2.pack.sufficiency is EvidencePackSufficiency.INSUFFICIENT
            assert v2.pack.policy_snapshot["min_evidence_items"] == 5
            assert v2.pack.policy_snapshot["policy_version"] == "1-strict-test"
            # The old pack is untouched.
            v1_reread = EvidencePackRepository(session).get_pack(v1.pack.id)
            assert v1_reread is not None
            assert v1_reread.sufficiency is EvidencePackSufficiency.READY
            assert v1_reread.policy_snapshot["min_evidence_items"] == 3

            # Exact retry with the ORIGINAL policy returns the original pack.
            retry = service.assemble_pack(opportunity_id, selections)
            assert retry.created is False
            assert retry.pack.id == v1.pack.id
            assert len(list(session.execute(select(EvidencePack)).scalars())) == 2

    def test_default_policy_is_named_versioned_and_explicit(self) -> None:
        assert DEFAULT_EVIDENCE_POLICY.name == "default"
        assert DEFAULT_EVIDENCE_POLICY.version == "1"
        snapshot = DEFAULT_EVIDENCE_POLICY.snapshot()
        assert snapshot["staleness_days"] == 180
        assert "not universal truth" in snapshot["note"]
        assert EvidenceSufficiencyPolicy.from_snapshot(snapshot) == DEFAULT_EVIDENCE_POLICY

    def test_insufficient_when_below_minimums(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id, evidence_ids = build_opportunity(session, second_source=False)
            result = EvidencePackService(session).assemble_pack(
                opportunity_id, selections_for(evidence_ids, key_fact_first=False)
            )
            session.commit()
            pack = result.pack
            assert pack.sufficiency is EvidencePackSufficiency.INSUFFICIENT
            missing = pack.sufficiency_detail["missing"]
            assert any("evidence items 2" in entry for entry in missing)
            assert any("distinct sources 1" in entry for entry in missing)
            assert any("key facts 0" in entry for entry in missing)


class TestContradictionResolution:
    def test_resolution_rules(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id, evidence_ids = build_opportunity(session)
            service = EvidencePackService(session)
            pack = service.assemble_pack(
                opportunity_id,
                selections_for(evidence_ids),
                contradictions=[blocking_declaration(evidence_ids[1], evidence_ids[2])],
            ).pack
            session.commit()
            [contradiction] = EvidencePackRepository(session).list_contradictions(pack.id)

            with pytest.raises(InvalidContradictionError, match="cannot be 'unresolved'"):
                service.resolve_contradiction(
                    contradiction.id,
                    resolution_status=ContradictionResolutionStatus.UNRESOLVED,
                    reason="x",
                )
            with pytest.raises(InvalidPackInputError):
                service.resolve_contradiction(
                    contradiction.id,
                    resolution_status=(ContradictionResolutionStatus.RESOLVED_NEEDS_RESEARCH),
                    reason="   ",
                )
            service.resolve_contradiction(
                contradiction.id,
                resolution_status=ContradictionResolutionStatus.RESOLVED_NEEDS_RESEARCH,
                reason="ek kaynak gerekiyor",
            )
            session.commit()
            with pytest.raises(InvalidContradictionError, match="already resolved"):
                service.resolve_contradiction(
                    contradiction.id,
                    resolution_status=(ContradictionResolutionStatus.RESOLVED_EDITORIAL_JUDGMENT),
                    reason="tekrar",
                )

    def test_reassemble_missing_pack(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            with pytest.raises(PackNotFoundError):
                EvidencePackService(session).reassemble_pack(uuid.uuid4())


class TestIdempotencyAndVersions:
    def test_exact_retry_returns_existing_pack(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, evidence_ids = build_opportunity(session)
            service = EvidencePackService(session)
            first = service.assemble_pack(opportunity_id, selections_for(evidence_ids))
            session.commit()
            second = service.assemble_pack(opportunity_id, selections_for(evidence_ids))

            assert second.created is False
            assert second.pack.id == first.pack.id
            assert len(list(session.execute(select(EvidencePack)).scalars())) == 1

    def test_display_note_is_formally_cosmetic(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, evidence_ids = build_opportunity(session)
            service = EvidencePackService(session)
            first = service.assemble_pack(opportunity_id, selections_for(evidence_ids))
            session.commit()
            noted = [
                EvidenceSelection(
                    research_evidence_id=selection.research_evidence_id,
                    role=selection.role,
                    claim_cluster=selection.claim_cluster,
                    display_note="kozmetik not",
                )
                for selection in selections_for(evidence_ids)
            ]
            retry = service.assemble_pack(opportunity_id, noted)
            # Notes never affect sufficiency/domain semantics (documented),
            # so they are excluded from the assembly identity.
            assert retry.created is False
            assert retry.pack.id == first.pack.id

    def test_changed_set_or_roles_appends_new_version(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, evidence_ids = build_opportunity(session)
            service = EvidencePackService(session)
            service.assemble_pack(opportunity_id, selections_for(evidence_ids))
            session.commit()
            reduced = service.assemble_pack(opportunity_id, selections_for(evidence_ids[:2]))
            session.commit()
            assert reduced.created is True and reduced.pack.version == 2
            reroled = service.assemble_pack(
                opportunity_id, selections_for(evidence_ids, key_fact_first=False)
            )
            session.commit()
            assert reroled.created is True and reroled.pack.version == 3
            packs = EvidencePackRepository(session).list_packs(opportunity_id)
            assert [pack.version for pack in packs] == [1, 2, 3]

    def test_race_recovers_existing_pack(
        self, session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, evidence_ids = build_opportunity(session)
            service = EvidencePackService(session)
            first = service.assemble_pack(opportunity_id, selections_for(evidence_ids))
            session.commit()

            original = EvidencePackRepository.get_pack_by_identity
            calls = {"count": 0}

            def racy(
                self: EvidencePackRepository, *args: Any, **kwargs: Any
            ) -> EvidencePack | None:
                calls["count"] += 1
                if calls["count"] == 1:
                    return None
                return original(self, *args, **kwargs)

            monkeypatch.setattr(EvidencePackRepository, "get_pack_by_identity", racy)
            recovered = service.assemble_pack(opportunity_id, selections_for(evidence_ids))
            assert recovered.created is False
            assert recovered.pack.id == first.pack.id

    def test_caller_owns_commit(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id, evidence_ids = build_opportunity(session)
            EvidencePackService(session).assemble_pack(opportunity_id, selections_for(evidence_ids))
            session.rollback()

        with open_session(session_factory) as session:
            assert session.execute(select(EvidencePack)).scalar_one_or_none() is None
            assert session.execute(select(EvidencePackItem)).scalar_one_or_none() is None


class TestIsolation:
    def test_assembly_has_no_workflow_or_disposition_side_effects(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, evidence_ids = build_opportunity(session)
            EvidencePackService(session).assemble_pack(opportunity_id, selections_for(evidence_ids))
            session.commit()

            opportunity = OpportunityRepository(session).get_by_id(opportunity_id)
            assert opportunity is not None
            assert opportunity.disposition.value == "open"
            events = WorkflowRepository(session).list_events(opportunity.work_item_id)
            assert len(events) == 1

    def test_repository_exposes_no_update_or_delete_surface(self) -> None:
        exposed = {name for name in dir(EvidencePackRepository) if not name.startswith("_")}
        assert not any("update" in name or "delete" in name for name in exposed)

    def test_list_eligible_evidence(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            opportunity_id, evidence_ids = build_opportunity(session)
            eligible = EvidencePackService(session).list_eligible_evidence(opportunity_id)
            assert {evidence.id for evidence in eligible} == set(evidence_ids)


class TestIdeaLink:
    def test_pack_without_idea_stays_valid_and_unpinned(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, evidence_ids = build_opportunity(session)
            pack = (
                EvidencePackService(session)
                .assemble_pack(opportunity_id, selections_for(evidence_ids))
                .pack
            )
            session.commit()
            assert pack.idea_id is None
            assert pack.assembly_input_snapshot["idea_id"] is None

    def test_pack_pins_exact_idea_version_in_identity(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, evidence_ids = build_opportunity(session)
            service = EvidencePackService(session)
            plain = service.assemble_pack(opportunity_id, selections_for(evidence_ids)).pack
            session.commit()
            idea = make_idea(session, opportunity_id)
            pinned = service.assemble_pack(
                opportunity_id, selections_for(evidence_ids), idea_id=idea.id
            ).pack
            session.commit()
            # Same evidence + policy but a different pinned idea is a
            # DIFFERENT pack identity — never deduped, never mutated.
            assert pinned.id != plain.id
            assert pinned.idea_id == idea.id
            assert pinned.assembly_input_snapshot["idea_id"] == str(idea.id)
            assert pinned.assembly_input_hash != plain.assembly_input_hash

            v2 = IdeaService(session).revise_operator_idea(
                idea.id,
                working_title="Evde balon temalı parti: saat saat plan",
                angle="Bütçe dostu üç saatlik hazırlık akışına odaklanıyoruz.",
                audience="Küçük çocuklu ebeveynler",
                value_proposition="Tek listeyle eksiksiz parti hazırlığı sağlar.",
                rationale="Kaynaklar genel kalıyor; biz uygulanabilir plan veriyoruz.",
                content_type=ContentType.PLANNING_GUIDE,
            )
            session.commit()
            repinned = service.assemble_pack(
                opportunity_id, selections_for(evidence_ids), idea_id=v2.id
            ).pack
            session.commit()
            assert repinned.id != pinned.id
            assert repinned.assembly_input_hash != pinned.assembly_input_hash

    def test_idea_from_another_opportunity_rejected(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, evidence_ids = build_opportunity(session)
            other_opportunity_id, _ = build_opportunity(session)
            foreign_idea = make_idea(session, other_opportunity_id)
            service = EvidencePackService(session)
            with pytest.raises(InvalidPackInputError, match="different opportunity"):
                service.assemble_pack(
                    opportunity_id, selections_for(evidence_ids), idea_id=foreign_idea.id
                )
            with pytest.raises(InvalidPackInputError, match="no idea"):
                service.assemble_pack(
                    opportunity_id, selections_for(evidence_ids), idea_id=uuid.uuid4()
                )

    def test_reassembly_carries_idea_unless_explicitly_replaced(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, evidence_ids = build_opportunity(session)
            service = EvidencePackService(session)
            idea = make_idea(session, opportunity_id)
            v1 = service.assemble_pack(
                opportunity_id,
                selections_for(evidence_ids),
                contradictions=[blocking_declaration(evidence_ids[1], evidence_ids[2])],
                idea_id=idea.id,
            ).pack
            session.commit()
            [contradiction] = EvidencePackRepository(session).list_contradictions(v1.id)
            service.resolve_contradiction(
                contradiction.id,
                resolution_status=ContradictionResolutionStatus.RESOLVED_CAUTIOUS_WORDING,
                reason="aralık olarak ifade edilecek",
            )
            session.commit()
            v2 = service.reassemble_pack(v1.id).pack
            session.commit()
            # The pinned idea carries forward by default...
            assert v2.idea_id == idea.id

            # ...an accidental idea_id without replace_idea is refused...
            other_idea = make_idea(session, opportunity_id, title_suffix=" farklı aday")
            with pytest.raises(InvalidPackInputError, match="replace_idea"):
                service.reassemble_pack(v2.id, idea_id=other_idea.id)

            # ...and an explicit replacement creates a new distinct version.
            v3 = service.reassemble_pack(v2.id, idea_id=other_idea.id, replace_idea=True).pack
            session.commit()
            assert v3.idea_id == other_idea.id
            assert v3.assembly_input_hash != v2.assembly_input_hash
            # Existing packs are never mutated or repointed.
            assert EvidencePackRepository(session).get_pack(v1.id).idea_id == idea.id  # type: ignore[union-attr]

    def test_selection_change_never_mutates_or_repoints_a_pack(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            opportunity_id, evidence_ids = build_opportunity(session)
            service = EvidencePackService(session)
            idea = make_idea(session, opportunity_id)
            other = make_idea(session, opportunity_id, title_suffix=" farklı aday")
            pack = service.assemble_pack(
                opportunity_id, selections_for(evidence_ids), idea_id=idea.id
            ).pack
            session.commit()
            ideas = IdeaService(session)
            ideas.select_idea(other.id, reason="farklı aday seçildi")
            session.commit()
            reread = EvidencePackRepository(session).get_pack(pack.id)
            assert reread is not None
            assert reread.idea_id == idea.id
