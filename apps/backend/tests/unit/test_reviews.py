"""Editor review persistence foundation tests (SQLite, real services)."""

import uuid

import pytest
from editorial_harness import Harness
from sqlalchemy import func, select
from test_drafts import AcceptedContext, accepted_context, valid_body

import contentos.reviews.models  # noqa: F401  (register tables before create_all)
from contentos.drafts.models import ContentDraft
from contentos.drafts.service import DraftService
from contentos.reviews.enums import (
    FindingDimension,
    FindingOrigin,
    FindingSeverity,
    ReviewActorOrigin,
    ReviewStatus,
    ReviewVerdict,
)
from contentos.reviews.errors import (
    ReviewInputError,
    ReviewPreconditionError,
)
from contentos.reviews.models import EditorialReview
from contentos.reviews.policies import DEFAULT_EDITOR_VERDICT_POLICY
from contentos.reviews.repository import ReviewRepository
from contentos.reviews.service import ReviewService
from contentos.reviews.values import ReviewFindingInput
from contentos.workflow.enums import WorkflowActorOrigin, WorkflowState
from contentos.workflow.service import WorkflowService


@pytest.fixture()
def harness() -> Harness:
    return Harness()


def editing_context(harness: Harness) -> tuple[AcceptedContext, uuid.UUID, uuid.UUID]:
    """Accepted brief -> durable operator draft -> SYSTEM DRAFTING->EDITING
    with the draft pinned (the exact artifact-gate the runtime performs).
    Returns (accepted, draft_id, claim_id_used_by_the_draft)."""
    accepted = accepted_context(harness)
    with harness.session() as session:
        creation = DraftService(session).create_operator_draft(
            accepted.context.brief_id,
            valid_body(accepted.claim_ids, accepted.handling_ids),
        )
        session.commit()
        draft = creation.draft
        WorkflowService(session).transition(
            draft.work_item_id,
            WorkflowState.EDITING,
            actor_origin=WorkflowActorOrigin.SYSTEM,
            reason="operator draft is durable and valid",
            artifact_refs={
                "content_draft_id": str(draft.id),
                "draft_version": draft.version,
                "content_hash": draft.content_hash,
            },
        )
        session.commit()
        return accepted, draft.id, accepted.claim_ids[0]


def finding(
    key: str = "claim-overstated",
    *,
    severity: FindingSeverity = FindingSeverity.MAJOR,
    block_id: str | None = "giris-2",
    claim_id: uuid.UUID | None = None,
) -> ReviewFindingInput:
    return ReviewFindingInput(
        finding_key=key,
        dimension=FindingDimension.CLAIM_FAITHFULNESS,
        severity=severity,
        origin=FindingOrigin.MODEL_SIGNAL,
        description="Metin, bağlanan iddiadan daha kesin bir dil kullanıyor.",
        recommendation="İfadeyi kaynağın belirttiği çerçeveye çek.",
        block_id=block_id,
        brief_claim_id=claim_id,
    )


class TestVerdictPolicy:
    def test_verdict_is_computed_never_supplied(self) -> None:
        policy = DEFAULT_EDITOR_VERDICT_POLICY
        assert policy.compute([]) is ReviewVerdict.PASS
        assert policy.compute([FindingSeverity.MINOR]) is ReviewVerdict.PASS
        assert policy.compute([FindingSeverity.MINOR, FindingSeverity.MAJOR]) is (
            ReviewVerdict.REVISE
        )
        assert policy.compute([FindingSeverity.BLOCKING]) is ReviewVerdict.REVISE
        snapshot = policy.snapshot()
        assert snapshot["version"] == "editor-verdict/1"
        assert snapshot["revise_severities"] == ["blocking", "major"]


class TestReviewCreation:
    def test_pass_review_with_no_findings(self, harness: Harness) -> None:
        accepted, draft_id, _ = editing_context(harness)
        with harness.session() as session:
            creation = ReviewService(session).create_review(accepted.context.work_item_id, [])
            session.commit()

            review = creation.review
            assert creation.created is True
            assert review.verdict is ReviewVerdict.PASS
            assert review.status is ReviewStatus.ACTIVE
            assert review.version == 1
            assert review.content_draft_id == draft_id
            assert review.engine_name == "editor"
            assert review.generation_attempt_id is None
            checks = review.integrity_gate_result["checks"]
            assert all(checks.values())
            assert review.integrity_gate_result["writer_envelope_recomputed"] is True
            assert review.integrity_gate_result["writer_envelope"] == {
                "structure_contract": "ok",
                "claim_ref_integrity": "ok",
                "handling_coverage": "ok",
            }
            assert review.review_scope["content_draft_id"] == str(draft_id)
            assert review.review_scope["finding_count"] == 0
            assert review.verdict_policy_snapshot["version"] == "editor-verdict/1"

    def test_blocking_finding_computes_revise_with_anchors(self, harness: Harness) -> None:
        accepted, draft_id, claim_id = editing_context(harness)
        with harness.session() as session:
            creation = ReviewService(session).create_review(
                accepted.context.work_item_id,
                [
                    finding(severity=FindingSeverity.BLOCKING, claim_id=claim_id),
                    finding(
                        "ton-notu",
                        severity=FindingSeverity.MINOR,
                        block_id="plan-1",
                    ),
                ],
            )
            session.commit()

            assert creation.review.verdict is ReviewVerdict.REVISE
            rows = ReviewRepository(session).list_findings(creation.review.id)
            assert [row.finding_key for row in rows] == ["claim-overstated", "ton-notu"]
            anchored = rows[0]
            assert anchored.block_id == "giris-2"
            assert anchored.brief_claim_id == claim_id
            assert anchored.origin is FindingOrigin.MODEL_SIGNAL
            assert rows[1].severity is FindingSeverity.MINOR

    def test_minor_only_findings_still_pass(self, harness: Harness) -> None:
        accepted, _, _ = editing_context(harness)
        with harness.session() as session:
            creation = ReviewService(session).create_review(
                accepted.context.work_item_id,
                [finding(severity=FindingSeverity.MINOR)],
            )
            session.commit()
            assert creation.review.verdict is ReviewVerdict.PASS

    def test_identical_re_review_is_idempotent(self, harness: Harness) -> None:
        accepted, _, _ = editing_context(harness)
        with harness.session() as session:
            service = ReviewService(session)
            first = service.create_review(accepted.context.work_item_id, [])
            session.commit()
            second = service.create_review(accepted.context.work_item_id, [])
            session.commit()
            assert second.created is False
            assert second.review.id == first.review.id
            assert session.scalar(select(func.count()).select_from(EditorialReview)) == 1

    def test_supersession_requires_reason_and_audits(self, harness: Harness) -> None:
        accepted, _, claim_id = editing_context(harness)
        with harness.session() as session:
            service = ReviewService(session)
            first = service.create_review(accepted.context.work_item_id, [])
            session.commit()

            with pytest.raises(ReviewInputError, match="explicit reason"):
                service.create_review(
                    accepted.context.work_item_id,
                    [finding(claim_id=claim_id)],
                )
            session.rollback()

            second = service.create_review(
                accepted.context.work_item_id,
                [finding(claim_id=claim_id)],
                supersede_reason="yeni bulgularla yeniden değerlendirildi",
                request_id="review-req-1",
            )
            session.commit()

            assert second.review.version == 2
            assert second.superseded_review_id == first.review.id
            old = ReviewRepository(session).get_review(first.review.id)
            assert old is not None
            assert old.status is ReviewStatus.SUPERSEDED
            assert old.superseded_by_review_id == second.review.id
            events = ReviewRepository(session).list_status_events(first.review.id)
            assert len(events) == 1
            assert events[0].from_status is ReviewStatus.ACTIVE
            assert events[0].to_status is ReviewStatus.SUPERSEDED
            assert events[0].actor_origin is ReviewActorOrigin.OPERATOR
            assert events[0].reason == "yeni bulgularla yeniden değerlendirildi"
            assert events[0].replacement_review_id == second.review.id
            assert events[0].request_id == "review-req-1"


class TestFindingValidation:
    def test_unknown_block_anchor_rejected(self, harness: Harness) -> None:
        accepted, _, _ = editing_context(harness)
        with harness.session() as session:
            with pytest.raises(ReviewInputError, match="unknown block"):
                ReviewService(session).create_review(
                    accepted.context.work_item_id,
                    [finding(block_id="hayalet-blok")],
                )

    def test_claim_outside_draft_usage_rejected(self, harness: Harness) -> None:
        accepted, _, _ = editing_context(harness)
        with harness.session() as session:
            # The inference claim exists on the brief but the draft never
            # bound it, so a finding cannot reference it.
            with pytest.raises(ReviewInputError, match="does not use"):
                ReviewService(session).create_review(
                    accepted.context.work_item_id,
                    [finding(claim_id=accepted.inference_claim_id)],
                )

    def test_duplicate_finding_key_rejected(self, harness: Harness) -> None:
        accepted, _, _ = editing_context(harness)
        with harness.session() as session:
            with pytest.raises(ReviewInputError, match="repeated"):
                ReviewService(session).create_review(
                    accepted.context.work_item_id,
                    [finding(), finding()],
                )

    def test_unsafe_finding_text_rejected(self, harness: Harness) -> None:
        accepted, _, _ = editing_context(harness)
        bad = ReviewFindingInput(
            finding_key="link-sizintisi",
            dimension=FindingDimension.CLARITY_STYLE,
            severity=FindingSeverity.MINOR,
            origin=FindingOrigin.MODEL_SIGNAL,
            description="Kaynak için https://ornek.com adresine bakın.",
        )
        with harness.session() as session:
            with pytest.raises(Exception, match="forbidden|https"):
                ReviewService(session).create_review(accepted.context.work_item_id, [bad])


class TestWriterEnvelopeDriftGuard:
    """Task 11: deterministic recomputation of the Writer envelope."""

    def _mutate_body(self, harness: Harness, draft_id: uuid.UUID, mutate) -> None:
        # SQLite harness has no immutability trigger, so tests can simulate
        # drifted durable state directly.
        with harness.session() as session:
            draft = session.get(ContentDraft, draft_id)
            assert draft is not None
            body = {
                "sections": [
                    {**section, "blocks": [dict(block) for block in section["blocks"]]}
                    for section in draft.body["sections"]
                ]
            }
            mutate(body)
            draft.body = body
            session.commit()

    def test_missing_coverage_block_is_blocking_deterministic_drift(self, harness: Harness) -> None:
        accepted, draft_id, _ = editing_context(harness)
        self._mutate_body(
            harness,
            draft_id,
            lambda body: body["sections"][0]["blocks"].__delitem__(-1),  # kapsam-notlari
        )
        with harness.session() as session:
            creation = ReviewService(session).create_review(accepted.context.work_item_id, [])
            session.commit()
            review = creation.review
            assert review.verdict is ReviewVerdict.REVISE
            envelope = review.integrity_gate_result["writer_envelope"]
            assert envelope["handling_coverage"] == "drift"
            assert envelope["structure_contract"] == "ok"
            rows = ReviewRepository(session).list_findings(review.id)
            drift = [row for row in rows if row.finding_key.startswith("drift-")]
            assert [row.finding_key for row in drift] == ["drift-handling-coverage"]
            assert drift[0].origin is FindingOrigin.DETERMINISTIC
            assert drift[0].severity is FindingSeverity.BLOCKING

    def test_claim_ref_mismatch_is_claim_integrity_drift(self, harness: Harness) -> None:
        accepted, draft_id, _ = editing_context(harness)

        def swap_ref(body: dict) -> None:
            body["sections"][0]["blocks"][1]["claim_refs"] = [str(uuid.uuid4())]

        self._mutate_body(harness, draft_id, swap_ref)
        with harness.session() as session:
            creation = ReviewService(session).create_review(accepted.context.work_item_id, [])
            session.commit()
            envelope = creation.review.integrity_gate_result["writer_envelope"]
            assert envelope["claim_ref_integrity"] == "drift"
            assert creation.review.verdict is ReviewVerdict.REVISE

    def test_section_outside_contract_is_structure_drift(self, harness: Harness) -> None:
        accepted, draft_id, _ = editing_context(harness)

        def rename_section(body: dict) -> None:
            body["sections"][1]["key"] = "sozlesme-disi"

        self._mutate_body(harness, draft_id, rename_section)
        with harness.session() as session:
            creation = ReviewService(session).create_review(accepted.context.work_item_id, [])
            session.commit()
            envelope = creation.review.integrity_gate_result["writer_envelope"]
            assert envelope["structure_contract"] == "drift"
            assert creation.review.verdict is ReviewVerdict.REVISE

    def test_drift_prefix_is_reserved_for_the_service(self, harness: Harness) -> None:
        accepted, _, _ = editing_context(harness)
        forged = ReviewFindingInput(
            finding_key="drift-sahte",
            dimension=FindingDimension.CLARITY_STYLE,
            severity=FindingSeverity.MINOR,
            origin=FindingOrigin.MODEL_SIGNAL,
            description="Deterministik sonuç taklidi denemesi.",
        )
        with harness.session() as session:
            with pytest.raises(ReviewInputError, match="reserved"):
                ReviewService(session).create_review(accepted.context.work_item_id, [forged])


class TestPreconditions:
    def test_requires_editing_state(self, harness: Harness) -> None:
        accepted = accepted_context(harness)  # work item stays DRAFTING
        with harness.session() as session:
            with pytest.raises(ReviewPreconditionError, match="EDITING"):
                ReviewService(session).create_review(accepted.context.work_item_id, [])

    def test_requires_pinned_draft_in_entry_event(self, harness: Harness) -> None:
        accepted = accepted_context(harness)
        with harness.session() as session:
            creation = DraftService(session).create_operator_draft(
                accepted.context.brief_id,
                valid_body(accepted.claim_ids, accepted.handling_ids),
            )
            session.commit()
            # A structurally legal transition WITHOUT the draft pin: the
            # review service must refuse rather than guess.
            WorkflowService(session).transition(
                creation.draft.work_item_id,
                WorkflowState.EDITING,
                actor_origin=WorkflowActorOrigin.SYSTEM,
                reason="transition without artifact pin (test)",
            )
            session.commit()
            with pytest.raises(ReviewPreconditionError, match="does not pin"):
                ReviewService(session).create_review(accepted.context.work_item_id, [])

    def test_missing_work_item_is_typed(self, harness: Harness) -> None:
        with harness.session() as session:
            with pytest.raises(ReviewPreconditionError, match="no editorial work item"):
                ReviewService(session).create_review(uuid.uuid4(), [])


class TestRepositorySurface:
    def test_repository_exposes_no_mutation_or_delete_surface(self) -> None:
        exposed = {name for name in dir(ReviewRepository) if not name.startswith("_")}
        assert exposed == {
            "insert_review",
            "insert_finding",
            "append_status_event",
            "get_review",
            "get_by_generation_attempt",
            "get_active_review",
            "list_by_work_item",
            "next_version",
            "list_findings",
            "list_status_events",
        }

    def test_draft_rows_untouched_by_review_creation(self, harness: Harness) -> None:
        accepted, draft_id, _ = editing_context(harness)
        with harness.session() as session:
            before = session.get(ContentDraft, draft_id)
            assert before is not None
            content_hash = before.content_hash
            ReviewService(session).create_review(accepted.context.work_item_id, [])
            session.commit()
            after = session.get(ContentDraft, draft_id)
            assert after is not None
            assert after.content_hash == content_hash
            assert after.status.value == "active"
