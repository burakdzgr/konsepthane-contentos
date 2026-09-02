"""Draft persistence + provenance foundation tests (SQLite, real services)."""

import uuid

import pytest
from editorial_harness import Context, Harness, seed_draft_brief
from sqlalchemy import func, select

import contentos.drafts.models  # noqa: F401  (register tables before create_all)
from contentos.ai.enums import GenerationPurpose, GenerationStatus
from contentos.ai.models import AiGenerationAttempt
from contentos.briefs.enums import BriefClaimKind
from contentos.briefs.repository import BriefRepository
from contentos.briefs.service import BriefService
from contentos.drafts.enums import DraftBlockKind, DraftOrigin, DraftStatus
from contentos.drafts.errors import (
    DraftInputError,
    DraftPolicyViolationError,
    DraftPreconditionError,
    InvalidDraftAttemptError,
)
from contentos.drafts.models import ContentDraft, DraftClaimUsage, DraftStatusEvent
from contentos.drafts.policies import (
    WriterOriginalityPolicy,
    build_required_handling_manifest,
    validate_originality,
)
from contentos.drafts.repository import DraftRepository
from contentos.drafts.service import DraftService
from contentos.drafts.values import (
    BODY_SCHEMA_VERSION,
    MANUAL_DRAFT_ENGINE_NAME,
    WRITER_ENGINE_NAME,
    DraftBlock,
    DraftBodyInput,
    DraftSection,
)
from contentos.evidence_packs.repository import EvidencePackRepository
from contentos.workflow.enums import WorkflowActorOrigin, WorkflowState
from contentos.workflow.service import WorkflowService


@pytest.fixture()
def harness() -> Harness:
    return Harness()


class AcceptedContext:
    context: Context
    claim_ids: list[uuid.UUID]
    handling_ids: tuple[str, ...]
    inference_claim_id: uuid.UUID


def accepted_context(harness: Harness) -> AcceptedContext:
    """Full Phase 3 chain ending in an ACCEPTED brief + DRAFTING work item."""
    result = AcceptedContext()
    with harness.session() as session:
        context = Context()
        seed_draft_brief(session, context)
        BriefService(session).accept_for_drafting(
            context.brief_id, reason="kapsam ve kanıt haritası eksiksiz"
        )
        session.commit()
        briefs = BriefRepository(session)
        claims = briefs.list_claims(context.brief_id)
        brief = briefs.get_brief(context.brief_id)
        assert brief is not None
        packs = EvidencePackRepository(session)
        pack = packs.get_pack(brief.evidence_pack_id)
        assert pack is not None
        manifest = build_required_handling_manifest(
            brief, pack, packs.list_contradictions(pack.id), claims
        )
        result.context = context
        by_kind = {claim.claim_kind: claim.id for claim in claims}
        # Semantically fixed order: [0]=factual, [1]=source_assertion — the
        # body builder's wording depends on it.
        result.claim_ids = [
            by_kind[BriefClaimKind.FACTUAL],
            by_kind[BriefClaimKind.SOURCE_ASSERTION],
        ]
        result.inference_claim_id = by_kind[BriefClaimKind.INFERENCE]
        result.handling_ids = tuple(entry.handling_id for entry in manifest)
    return result


def block(
    block_id: str,
    text: str = "Bu bölüm konsept planını anlatır.",
    *,
    kind: DraftBlockKind = DraftBlockKind.PARAGRAPH,
    claim_refs: tuple[uuid.UUID, ...] = (),
    **kwargs: object,
) -> DraftBlock:
    return DraftBlock(block_id=block_id, kind=kind, text=text, claim_refs=claim_refs, **kwargs)  # type: ignore[arg-type]


def valid_body(claim_ids: list[uuid.UUID], handling_ids: tuple[str, ...] = ()) -> DraftBodyInput:
    """Covers the harness brief's required sections AND its handling manifest."""
    coverage_blocks: tuple[DraftBlock, ...] = ()
    if handling_ids:
        coverage_blocks = (
            DraftBlock(
                block_id="kapsam-notlari",
                kind=DraftBlockKind.CALLOUT,
                text=(
                    "Bu rehberdeki bilgiler sınırlı kaynak sinyaline dayanır; "
                    "eksik arama verileri ve yerel farklılıklar belirsizlik "
                    "yaratabilir, çelişen süre tahminleri aralık olarak verilir."
                ),
                uncertainty_refs=handling_ids,
            ),
        )
    return DraftBodyInput(
        sections=(
            DraftSection(
                key="giris",
                heading="Neden evde parti?",
                blocks=(
                    block("giris-1", "Evde parti hem samimi hem bütçe dostudur."),
                    block(
                        "giris-2",
                        "Kaynaklara göre konsept detayları netleştirilmelidir.",
                        claim_refs=(claim_ids[0],),
                    ),
                )
                + coverage_blocks,
            ),
            DraftSection(
                key="plan",
                heading="Üç saatlik hazırlık planı",
                blocks=(
                    block(
                        "plan-1",
                        "İlk saat: tema ve alan hazırlığı.",
                        kind=DraftBlockKind.HOW_TO_STEP,
                    ),
                ),
            ),
            DraftSection(
                key="butce",
                heading="Bütçe dostu öneriler",
                blocks=(
                    block(
                        "butce-1",
                        "İkinci kaynağın aktardığı bütçe aralığı planlamada esas alınabilir.",
                        claim_refs=(claim_ids[1],),
                    ),
                ),
            ),
        )
    )


class TestOperatorDraftCreation:
    def test_happy_path_with_mirrored_provenance(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        with harness.session() as session:
            creation = DraftService(session).create_operator_draft(
                accepted.context.brief_id,
                valid_body(accepted.claim_ids, accepted.handling_ids),
                title_proposal="Evde balon temalı parti planı",
            )
            session.commit()
            draft = creation.draft
            assert creation.created is True
            assert creation.superseded_draft_id is None
            assert draft.version == 1
            assert draft.origin is DraftOrigin.OPERATOR
            assert draft.status is DraftStatus.ACTIVE
            assert draft.generation_attempt_id is None
            assert draft.engine_name == MANUAL_DRAFT_ENGINE_NAME
            assert draft.body_schema_version == BODY_SCHEMA_VERSION
            assert draft.body["schema"] == BODY_SCHEMA_VERSION
            assert draft.content_brief_id == accepted.context.brief_id
            assert draft.work_item_id == accepted.context.work_item_id
            assert len(draft.content_hash) == 64
            assert draft.manual_input_hash is not None
            assert len(draft.manual_input_hash) == 64
            # Task-3 policy snapshots + truthful evaluation records.
            assert draft.validation_policy_snapshot["name"] == "writer-validation"
            assert draft.validation_policy_snapshot["version"] == "1"
            assert draft.validation_policy_snapshot["exclusions_mechanically_checked"] is False
            assert draft.originality_policy_snapshot["name"] == "writer-originality"
            assert draft.uncertainty_coverage["status"] == "evaluated"
            assert draft.uncertainty_coverage["total"] == len(accepted.handling_ids)
            assert all(entry["block_ids"] for entry in draft.uncertainty_coverage["entries"])
            assert draft.originality_result["outcome"] == "passed"
            assert (
                draft.originality_result["checks"]["source_structure"]["brief_guard_outcome"]
                == "passed"
            )

            usages = DraftRepository(session).list_claim_usages(draft.id)
            anchors = {(u.brief_claim_id, u.section_key, u.block_id) for u in usages}
            assert anchors == {
                (accepted.claim_ids[0], "giris", "giris-2"),
                (accepted.claim_ids[1], "butce", "butce-1"),
            }

    def test_identical_resubmission_is_idempotent(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        with harness.session() as session:
            service = DraftService(session)
            first = service.create_operator_draft(
                accepted.context.brief_id, valid_body(accepted.claim_ids, accepted.handling_ids)
            )
            session.commit()
            second = service.create_operator_draft(
                accepted.context.brief_id, valid_body(accepted.claim_ids, accepted.handling_ids)
            )
            session.commit()
            assert second.created is False
            assert second.draft.id == first.draft.id
            assert session.scalar(select(func.count()).select_from(ContentDraft)) == 1
            assert session.scalar(select(func.count()).select_from(DraftStatusEvent)) == 0

    def test_changed_submission_supersedes_with_reason(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        with harness.session() as session:
            service = DraftService(session)
            first = service.create_operator_draft(
                accepted.context.brief_id, valid_body(accepted.claim_ids, accepted.handling_ids)
            )
            session.commit()

            # A substantively different body without a reason is refused.
            base = valid_body(accepted.claim_ids, accepted.handling_ids)
            different = DraftBodyInput(
                sections=(
                    base.sections[0],
                    base.sections[1],
                    DraftSection(
                        key="butce",
                        heading="Bütçe dostu öneriler (revize)",
                        blocks=(
                            block(
                                "butce-1",
                                "Bütçe aralığı ikinci kaynağa göre revize edildi.",
                                claim_refs=(accepted.claim_ids[1],),
                            ),
                        ),
                    ),
                )
            )
            with pytest.raises(DraftInputError, match="reason"):
                service.create_operator_draft(accepted.context.brief_id, different)

            second = service.create_operator_draft(
                accepted.context.brief_id,
                different,
                supersede_reason="bütçe bölümü revize edildi",
            )
            session.commit()
            assert second.created is True
            assert second.draft.version == 2
            assert second.superseded_draft_id == first.draft.id

            old = session.get(ContentDraft, first.draft.id)
            assert old is not None
            assert old.status is DraftStatus.SUPERSEDED
            assert old.superseded_by_draft_id == second.draft.id
            [event] = DraftRepository(session).list_status_events(first.draft.id)
            assert event.from_status is DraftStatus.ACTIVE
            assert event.to_status is DraftStatus.SUPERSEDED
            assert event.replacement_draft_id == second.draft.id
            assert event.reason == "bütçe bölümü revize edildi"

    def test_supersession_race_on_active_index_is_a_typed_conflict(self, harness: Harness) -> None:
        # Direct duplicate-active insert attempts collapse at the partial
        # unique index; the service surfaces a typed conflict, never a
        # second active row (full concurrency exercised on real PG).
        accepted = accepted_context(harness)
        with harness.session() as session:
            service = DraftService(session)
            service.create_operator_draft(
                accepted.context.brief_id,
                valid_body(accepted.claim_ids, accepted.handling_ids),
            )
            session.commit()
            actives = session.scalar(
                select(func.count())
                .select_from(ContentDraft)
                .where(ContentDraft.status == DraftStatus.ACTIVE)
            )
            assert actives == 1


class TestStructuralGates:
    def test_missing_required_section_fails(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        body = DraftBodyInput(
            sections=valid_body(accepted.claim_ids, accepted.handling_ids).sections[:2]
        )
        with harness.session() as session:
            with pytest.raises(DraftInputError, match="butce"):
                DraftService(session).create_operator_draft(accepted.context.brief_id, body)

    def test_unknown_section_fails(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        body = DraftBodyInput(
            sections=valid_body(accepted.claim_ids, accepted.handling_ids).sections
            + (DraftSection(key="bonus", heading="Ekstra", blocks=(block("bonus-1"),)),)
        )
        with harness.session() as session:
            with pytest.raises(DraftInputError, match="bonus"):
                DraftService(session).create_operator_draft(accepted.context.brief_id, body)

    def test_foreign_claim_ref_fails(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        body = valid_body([accepted.claim_ids[0], uuid.uuid4()], accepted.handling_ids)
        with harness.session() as session:
            with pytest.raises(DraftInputError, match="not a claim of the pinned brief"):
                DraftService(session).create_operator_draft(accepted.context.brief_id, body)

    @pytest.mark.parametrize(
        "bad_text",
        [
            "Detaylar için https://ornek.example.test adresine bakın.",
            "Detaylar için www.ornek.com sayfasına bakın.",
            "<script>alert(1)</script>",
            "Şu bağlantı javascript:void(0) güvensizdir.",
        ],
    )
    def test_url_html_script_ban(self, harness: Harness, bad_text: str) -> None:
        accepted = accepted_context(harness)
        sections = valid_body(accepted.claim_ids, accepted.handling_ids).sections
        body = DraftBodyInput(
            sections=(
                DraftSection(
                    key="giris",
                    heading="Neden evde parti?",
                    blocks=(block("giris-1", bad_text),),
                ),
            )
            + sections[1:]
        )
        with harness.session() as session:
            with pytest.raises(DraftInputError, match="forbidden"):
                DraftService(session).create_operator_draft(accepted.context.brief_id, body)

    def test_url_in_title_proposal_fails(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        with harness.session() as session:
            with pytest.raises(DraftInputError, match="forbidden"):
                DraftService(session).create_operator_draft(
                    accepted.context.brief_id,
                    valid_body(accepted.claim_ids, accepted.handling_ids),
                    title_proposal="Harika plan https://spam.example",
                )

    def test_duplicate_block_ids_across_sections_fail(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        sections = valid_body(accepted.claim_ids, accepted.handling_ids).sections
        body = DraftBodyInput(
            sections=sections[:2]
            + (
                DraftSection(
                    key="butce",
                    heading="Bütçe",
                    blocks=(block("giris-1", "Tekrarlanan blok kimliği."),),
                ),
            )
        )
        with harness.session() as session:
            with pytest.raises(DraftInputError, match="unique"):
                DraftService(session).create_operator_draft(accepted.context.brief_id, body)

    def test_placeholder_blocks_reference_real_brief_needs(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        base = valid_body(accepted.claim_ids, accepted.handling_ids).sections

        # Positive: the harness brief carries exactly one link and one media need.
        good = DraftBodyInput(
            sections=base[:2]
            + (
                DraftSection(
                    key="butce",
                    heading="Bütçe dostu öneriler",
                    blocks=(
                        block(
                            "butce-1",
                            "Bütçe aralığı kaynağa göre verilir.",
                            claim_refs=(accepted.claim_ids[1],),
                        ),
                        block(
                            "link-1",
                            "İlgili rehber bağlantısı buraya gelecek.",
                            kind=DraftBlockKind.INTERNAL_LINK_NEED,
                            link_need_ref=0,
                        ),
                        block(
                            "media-1",
                            "Balon teması kapak görseli ihtiyacı.",
                            kind=DraftBlockKind.MEDIA_NEED,
                            media_need_ref=0,
                        ),
                    ),
                ),
            )
        )
        with harness.session() as session:
            creation = DraftService(session).create_operator_draft(accepted.context.brief_id, good)
            session.commit()
            assert creation.created is True

        # Negative: an out-of-range need reference fails closed.
        bad = DraftBodyInput(
            sections=base[:2]
            + (
                DraftSection(
                    key="butce",
                    heading="Bütçe",
                    blocks=(
                        block(
                            "link-9",
                            "Var olmayan ihtiyaca bağlantı.",
                            kind=DraftBlockKind.INTERNAL_LINK_NEED,
                            link_need_ref=5,
                        ),
                    ),
                ),
            )
        )
        with harness.session() as session:
            with pytest.raises(DraftInputError, match="internal link need"):
                DraftService(session).create_operator_draft(accepted.context.brief_id, bad)

    def test_placeholder_without_ref_fails_at_dto_level(self, harness: Harness) -> None:
        with pytest.raises(DraftInputError, match="link_need_ref"):
            DraftBodyInput(
                sections=(
                    DraftSection(
                        key="giris",
                        heading="x",
                        blocks=(block("a-1", kind=DraftBlockKind.INTERNAL_LINK_NEED),),
                    ),
                )
            ).cleaned()


class TestPreconditions:
    def test_unaccepted_brief_is_refused(self, harness: Harness) -> None:
        with harness.session() as session:
            context = Context()
            seed_draft_brief(session, context)  # brief stays DRAFT, item BRIEFING
            session.commit()
            claims = BriefRepository(session).list_claims(context.brief_id)
            with pytest.raises(DraftPreconditionError, match="accepted"):
                DraftService(session).create_operator_draft(
                    context.brief_id, valid_body([c.id for c in claims])
                )

    def test_work_item_outside_drafting_is_refused(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        with harness.session() as session:
            WorkflowService(session).transition(
                accepted.context.work_item_id,
                WorkflowState.EDITING,
                actor_origin=WorkflowActorOrigin.SYSTEM,
                reason="test ilerlemesi",
            )
            session.commit()
            with pytest.raises(DraftPreconditionError, match="DRAFTING"):
                DraftService(session).create_operator_draft(
                    accepted.context.brief_id, valid_body(accepted.claim_ids, accepted.handling_ids)
                )

    def test_unknown_brief_is_refused(self, harness: Harness) -> None:
        with harness.session() as session:
            with pytest.raises(DraftPreconditionError, match="no content brief"):
                DraftService(session).create_operator_draft(
                    uuid.uuid4(), DraftBodyInput(sections=())
                )


def writer_attempt(
    brief_id: uuid.UUID,
    *,
    purpose: GenerationPurpose = GenerationPurpose.WRITER_DRAFT,
    status: GenerationStatus = GenerationStatus.SUCCEEDED,
) -> AiGenerationAttempt:
    marker = uuid.uuid4().hex
    return AiGenerationAttempt(
        purpose=purpose,
        provider="fake",
        model_name="deterministic-structured-test-model",
        model_version="1",
        schema_name="writer-draft",
        schema_version="1",
        template_name="writer-draft",
        template_version="1",
        input_refs={"content_brief_id": str(brief_id), "schema": "writer-draft/1"},
        input_hash=(marker + marker)[:64],
        attempt_identity_hash=(uuid.uuid4().hex + uuid.uuid4().hex)[:64],
        status=status,
        error_class=None if status is GenerationStatus.SUCCEEDED else "schema_validation",
        retry_number=0,
        usage={},
    )


class TestGeneratedDraftCreation:
    def test_one_draft_per_succeeded_attempt(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        with harness.session() as session:
            attempt = writer_attempt(accepted.context.brief_id)
            session.add(attempt)
            session.commit()
            service = DraftService(session)
            first = service.create_generated_draft(
                accepted.context.brief_id,
                valid_body(accepted.claim_ids, accepted.handling_ids),
                generation_attempt=attempt,
            )
            session.commit()
            assert first.created is True
            assert first.draft.origin is DraftOrigin.WRITER_ENGINE
            assert first.draft.engine_name == WRITER_ENGINE_NAME
            assert first.draft.manual_input_hash is None
            assert first.draft.generation_attempt_id == attempt.id

            redelivered = service.create_generated_draft(
                accepted.context.brief_id,
                valid_body(accepted.claim_ids, accepted.handling_ids),
                generation_attempt=attempt,
            )
            assert redelivered.created is False
            assert redelivered.draft.id == first.draft.id
            assert session.scalar(select(func.count()).select_from(ContentDraft)) == 1
            usage_count = session.scalar(select(func.count()).select_from(DraftClaimUsage))
            assert usage_count == 2  # mirrored once, never duplicated

    def test_attempt_gates(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        with harness.session() as session:
            wrong_purpose = writer_attempt(
                accepted.context.brief_id, purpose=GenerationPurpose.BRIEF_COMPOSITION
            )
            failed = writer_attempt(
                accepted.context.brief_id, status=GenerationStatus.VALIDATION_FAILED
            )
            foreign = writer_attempt(uuid.uuid4())
            session.add_all([wrong_purpose, failed, foreign])
            session.commit()
            service = DraftService(session)
            body = valid_body(accepted.claim_ids, accepted.handling_ids)
            with pytest.raises(InvalidDraftAttemptError, match="purpose"):
                service.create_generated_draft(
                    accepted.context.brief_id, body, generation_attempt=wrong_purpose
                )
            with pytest.raises(InvalidDraftAttemptError, match="SUCCEEDED"):
                service.create_generated_draft(
                    accepted.context.brief_id, body, generation_attempt=failed
                )
            with pytest.raises(InvalidDraftAttemptError, match="pinned brief"):
                service.create_generated_draft(
                    accepted.context.brief_id, body, generation_attempt=foreign
                )

    def test_mixed_origin_supersession(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        with harness.session() as session:
            service = DraftService(session)
            manual = service.create_operator_draft(
                accepted.context.brief_id, valid_body(accepted.claim_ids, accepted.handling_ids)
            )
            session.commit()
            attempt = writer_attempt(accepted.context.brief_id)
            session.add(attempt)
            session.commit()
            generated = service.create_generated_draft(
                accepted.context.brief_id,
                valid_body(accepted.claim_ids, accepted.handling_ids),
                generation_attempt=attempt,
                supersede_reason="yazar motoru sürümü tercih edildi",
            )
            session.commit()
            assert generated.draft.version == 2
            assert generated.superseded_draft_id == manual.draft.id
            active = DraftRepository(session).get_active_draft(accepted.context.work_item_id)
            assert active is not None and active.id == generated.draft.id


class TestWriterPolicies:
    def base_sections(self, accepted: AcceptedContext) -> tuple[DraftSection, ...]:
        return valid_body(accepted.claim_ids, accepted.handling_ids).sections

    def with_butce(self, accepted: AcceptedContext, extra: DraftBlock) -> DraftBodyInput:
        sections = self.base_sections(accepted)
        butce = sections[2]
        return DraftBodyInput(
            sections=sections[:2]
            + (DraftSection(key="butce", heading=butce.heading, blocks=butce.blocks + (extra,)),)
        )

    def test_missing_handling_coverage_fails_closed(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        body = valid_body(accepted.claim_ids)  # no coverage callout at all
        with harness.session() as session:
            with pytest.raises(DraftPolicyViolationError, match="disappeared"):
                DraftService(session).create_operator_draft(accepted.context.brief_id, body)

    def test_unknown_handling_ref_fails_closed(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        body = self.with_butce(
            accepted,
            DraftBlock(
                block_id="uydurma-not",
                kind=DraftBlockKind.CALLOUT,
                text="Uydurulmuş bir belirsizlik notu.",
                uncertainty_refs=("hayali-not",),
            ),
        )
        with harness.session() as session:
            with pytest.raises(DraftPolicyViolationError, match="unknown handling"):
                DraftService(session).create_operator_draft(accepted.context.brief_id, body)

    def test_numeric_assertion_without_claim_fails(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        body = self.with_butce(
            accepted,
            block("fiyat-1", "Ortalama parti bütçesi 2500 lira tutar."),
        )
        with harness.session() as session:
            with pytest.raises(DraftPolicyViolationError, match="numeric assertion"):
                DraftService(session).create_operator_draft(accepted.context.brief_id, body)

    def test_numeric_with_claim_binding_passes(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        body = self.with_butce(
            accepted,
            block(
                "fiyat-2",
                "Kaynağa göre bütçe kalemleri 3 ana grupta toplanabilir.",
                claim_refs=(accepted.claim_ids[1],),
            ),
        )
        with harness.session() as session:
            creation = DraftService(session).create_operator_draft(accepted.context.brief_id, body)
            session.commit()
            assert creation.created is True

    def test_step_enumeration_is_not_a_numeric_assertion(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        body = self.with_butce(
            accepted,
            block(
                "adim-1",
                "1. Balonları şişirin\n2. Masayı kurun",
                kind=DraftBlockKind.HOW_TO_STEP,
            ),
        )
        with harness.session() as session:
            creation = DraftService(session).create_operator_draft(accepted.context.brief_id, body)
            session.commit()
            assert creation.created is True

    def test_source_assertion_requires_attribution(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        sections = self.base_sections(accepted)
        # Restate the source assertion as bare fact: no attribution stem.
        bare = DraftSection(
            key="butce",
            heading="Bütçe dostu öneriler",
            blocks=(
                block(
                    "butce-1",
                    "Parti bütçesi her zaman düşük tutulur.",
                    claim_refs=(accepted.claim_ids[1],),
                ),
            ),
        )
        body = DraftBodyInput(sections=sections[:2] + (bare,))
        with harness.session() as session:
            with pytest.raises(DraftPolicyViolationError, match="attribution"):
                DraftService(session).create_operator_draft(accepted.context.brief_id, body)

    def test_inference_requires_hedging(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        hardened = self.with_butce(
            accepted,
            block(
                "cikarim-1",
                "Ev partileri kesinlikle streslidir.",
                claim_refs=(accepted.inference_claim_id,),
            ),
        )
        with harness.session() as session:
            with pytest.raises(DraftPolicyViolationError, match="inference"):
                DraftService(session).create_operator_draft(accepted.context.brief_id, hardened)
        hedged = self.with_butce(
            accepted,
            block(
                "cikarim-2",
                "Ev partileri iyi hazırlıkla stressiz olabilir.",
                claim_refs=(accepted.inference_claim_id,),
            ),
        )
        with harness.session() as session:
            creation = DraftService(session).create_operator_draft(
                accepted.context.brief_id, hedged
            )
            session.commit()
            assert creation.created is True

    def test_verbatim_overlap_cap_is_deterministic(self) -> None:
        statement = (
            "Bu çok uzun bir kaynak cümlesi olup birebir kopyalanması halinde "
            "özgünlük sınırını kesin olarak aşacak kadar karakter içerir ve "
            "testte bunu kanıtlamak için kullanılır."
        )
        body = DraftBodyInput(
            sections=(
                DraftSection(
                    key="giris",
                    heading="Test",
                    blocks=(block("kopya-1", f"Girizgah: {statement} Devamı."),),
                ),
            )
        ).cleaned()

        class _Brief:
            structure_guard_result = {"outcome": "passed"}

        with pytest.raises(DraftPolicyViolationError, match="TRANSLATE-AND-REPUBLISH"):
            validate_originality(
                body,
                None,
                [statement],
                _Brief(),
                WriterOriginalityPolicy(),  # type: ignore[arg-type]
            )
        # A short quotation stays inside the cap.
        result = validate_originality(
            body,
            None,
            ["kısa bir alıntı"],
            _Brief(),  # type: ignore[arg-type]
            WriterOriginalityPolicy(),
        )
        assert result["outcome"] == "passed"
        assert result["checks"]["verbatim_overlap"]["max_observed_chars"] <= 80
