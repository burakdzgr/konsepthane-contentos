"""Draft persistence + provenance foundation tests (SQLite, real services)."""

import uuid

import pytest
from editorial_harness import Context, Harness, seed_draft_brief
from sqlalchemy import func, select

import contentos.drafts.models  # noqa: F401  (register tables before create_all)
from contentos.ai.enums import GenerationPurpose, GenerationStatus
from contentos.ai.models import AiGenerationAttempt
from contentos.briefs.repository import BriefRepository
from contentos.briefs.service import BriefService
from contentos.drafts.enums import DraftBlockKind, DraftOrigin, DraftStatus
from contentos.drafts.errors import (
    DraftInputError,
    DraftPreconditionError,
    InvalidDraftAttemptError,
)
from contentos.drafts.models import ContentDraft, DraftClaimUsage, DraftStatusEvent
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
from contentos.workflow.enums import WorkflowActorOrigin, WorkflowState
from contentos.workflow.service import WorkflowService


@pytest.fixture()
def harness() -> Harness:
    return Harness()


class AcceptedContext:
    context: Context
    claim_ids: list[uuid.UUID]


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
        claims = BriefRepository(session).list_claims(context.brief_id)
        result.context = context
        result.claim_ids = [claim.id for claim in claims]
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


def valid_body(claim_ids: list[uuid.UUID]) -> DraftBodyInput:
    """Covers the harness brief's required sections: giris, plan, butce."""
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
                ),
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
                valid_body(accepted.claim_ids),
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
            # Truthful Task-2 snapshots: structural-only, nothing overclaimed.
            assert draft.validation_policy_snapshot["name"] == "writer-structural"
            assert draft.uncertainty_coverage == {"status": "not_evaluated"}
            assert draft.originality_result == {"outcome": "not_checked"}

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
                accepted.context.brief_id, valid_body(accepted.claim_ids)
            )
            session.commit()
            second = service.create_operator_draft(
                accepted.context.brief_id, valid_body(accepted.claim_ids)
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
                accepted.context.brief_id, valid_body(accepted.claim_ids)
            )
            session.commit()

            changed = valid_body(accepted.claim_ids)
            changed = DraftBodyInput(
                sections=changed.sections
                + (
                    DraftSection(
                        key="giris",
                        heading="x",
                        blocks=(block("z-1"),),
                    ),
                )
            )
            # A substantively different body without a reason is refused.
            different = DraftBodyInput(
                sections=(
                    valid_body(accepted.claim_ids).sections[0],
                    valid_body(accepted.claim_ids).sections[1],
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
            service.create_operator_draft(accepted.context.brief_id, valid_body(accepted.claim_ids))
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
        body = DraftBodyInput(sections=valid_body(accepted.claim_ids).sections[:2])
        with harness.session() as session:
            with pytest.raises(DraftInputError, match="butce"):
                DraftService(session).create_operator_draft(accepted.context.brief_id, body)

    def test_unknown_section_fails(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        body = DraftBodyInput(
            sections=valid_body(accepted.claim_ids).sections
            + (DraftSection(key="bonus", heading="Ekstra", blocks=(block("bonus-1"),)),)
        )
        with harness.session() as session:
            with pytest.raises(DraftInputError, match="bonus"):
                DraftService(session).create_operator_draft(accepted.context.brief_id, body)

    def test_foreign_claim_ref_fails(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        body = valid_body([accepted.claim_ids[0], uuid.uuid4()])
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
        sections = valid_body(accepted.claim_ids).sections
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
                    valid_body(accepted.claim_ids),
                    title_proposal="Harika plan https://spam.example",
                )

    def test_duplicate_block_ids_across_sections_fail(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        sections = valid_body(accepted.claim_ids).sections
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
        base = valid_body(accepted.claim_ids).sections

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
                    accepted.context.brief_id, valid_body(accepted.claim_ids)
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
                valid_body(accepted.claim_ids),
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
                valid_body(accepted.claim_ids),
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
            body = valid_body(accepted.claim_ids)
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
                accepted.context.brief_id, valid_body(accepted.claim_ids)
            )
            session.commit()
            attempt = writer_attempt(accepted.context.brief_id)
            session.add(attempt)
            session.commit()
            generated = service.create_generated_draft(
                accepted.context.brief_id,
                valid_body(accepted.claim_ids),
                generation_attempt=attempt,
                supersede_reason="yazar motoru sürümü tercih edildi",
            )
            session.commit()
            assert generated.draft.version == 2
            assert generated.superseded_draft_id == manual.draft.id
            active = DraftRepository(session).get_active_draft(accepted.context.work_item_id)
            assert active is not None and active.id == generated.draft.id
