"""Publishing workflow gates (Phase 7 P2): scheduling + expiry resolution.

Humans schedule; machines only execute. APPROVED → SCHEDULED requires
the CURRENT approval (the guard) AND an explicit durable publication
package whose content hash equals the approved hash — a package
assembled over different content can never ride an approval. Out of
APPROVAL_EXPIRED the target is DERIVED, never chosen: back to
AWAITING_HUMAN_REVIEW when the ACTIVE ready QA report still covers the
ACTIVE draft (with the exact re-entry pins so a re-approval works),
else back to QA_REVIEW (with the review/draft pins the QA engine
requires). The caller commits.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from contentos.decisions.service import ApprovalStatus, DecisionService
from contentos.drafts.repository import DraftRepository
from contentos.publishing.errors import PublicationPreconditionError
from contentos.publishing.models import PublicationPackage
from contentos.qa.enums import QaOutcome, QaReportStatus
from contentos.qa.repository import QaRepository
from contentos.reviews.enums import ReviewStatus
from contentos.reviews.repository import ReviewRepository
from contentos.workflow.enums import WorkflowActorOrigin, WorkflowState
from contentos.workflow.models import EditorialWorkItem
from contentos.workflow.repository import WorkflowRepository
from contentos.workflow.service import WorkflowService


@dataclass(frozen=True, slots=True)
class SchedulablePackage:
    package: PublicationPackage
    approval: ApprovalStatus


class PublishingService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._workflow = WorkflowRepository(session)
        self._decisions = DecisionService(session)
        self._drafts = DraftRepository(session)
        self._reviews = ReviewRepository(session)
        self._qa = QaRepository(session)

    # --- scheduling -----------------------------------------------------------

    def resolve_schedulable_package(
        self, work_item_id: uuid.UUID, publication_package_id: uuid.UUID
    ) -> SchedulablePackage:
        work_item = self._require_work_item(work_item_id)
        if work_item.current_state is not WorkflowState.APPROVED:
            raise PublicationPreconditionError(
                f"scheduling requires APPROVED (current: {work_item.current_state.value})"
            )
        # The guard: a stale approval raises typed — never ridden.
        approval = self._decisions.require_current_approval(work_item_id)
        package = self._session.get(PublicationPackage, publication_package_id)
        if package is None or package.work_item_id != work_item_id:
            raise PublicationPreconditionError(
                f"no publication package {publication_package_id} exists for this work item"
            )
        if package.content_hash != approval.approved_content_hash:
            raise PublicationPreconditionError(
                "the publication package was assembled over different content "
                "than the approval covers; re-assemble before scheduling"
            )
        return SchedulablePackage(package=package, approval=approval)

    def schedule_publication(
        self,
        work_item_id: uuid.UUID,
        publication_package_id: uuid.UUID,
        *,
        reason: str,
        actor_user_id: uuid.UUID | None,
        request_id: str | None = None,
    ) -> EditorialWorkItem:
        resolved = self.resolve_schedulable_package(work_item_id, publication_package_id)
        assert resolved.approval.decision_id is not None
        return WorkflowService(self._session).transition(
            work_item_id,
            WorkflowState.SCHEDULED,
            actor_origin=WorkflowActorOrigin.OPERATOR,
            reason=reason,
            artifact_refs={
                "publication_package_id": str(resolved.package.id),
                "package_hash": resolved.package.package_hash,
                "human_decision_id": str(resolved.approval.decision_id),
                "content_hash": resolved.package.content_hash,
            },
            request_id=request_id,
            actor_user_id=actor_user_id,
        )

    # --- expiry resolution ----------------------------------------------------

    def resolve_approval_expired(
        self,
        work_item_id: uuid.UUID,
        *,
        reason: str,
        actor_user_id: uuid.UUID | None,
        request_id: str | None = None,
    ) -> EditorialWorkItem:
        """Route out of APPROVAL_EXPIRED to the DERIVED target."""
        work_item = self._require_work_item(work_item_id)
        if work_item.current_state is not WorkflowState.APPROVAL_EXPIRED:
            raise PublicationPreconditionError(
                "expiry resolution requires APPROVAL_EXPIRED "
                f"(current: {work_item.current_state.value})"
            )
        draft = self._drafts.get_active_draft(work_item_id)
        review = self._reviews.get_active_review(work_item_id)
        if draft is None or review is None:
            raise PublicationPreconditionError(
                "the work item has no ACTIVE draft and editor review to route back to"
            )
        report = self._qa.get_active_report(work_item_id)
        report_covers_draft = (
            report is not None
            and report.status is QaReportStatus.ACTIVE
            and report.content_draft_id == draft.id
            and report.outcome is QaOutcome.READY_FOR_HUMAN_REVIEW
        )
        if report_covers_draft:
            assert report is not None
            target = WorkflowState.AWAITING_HUMAN_REVIEW
            refs = {
                "qa_report_id": str(report.id),
                "editorial_review_id": str(report.editorial_review_id),
                "content_draft_id": str(draft.id),
                "content_hash": draft.content_hash,
            }
        else:
            if review.status is not ReviewStatus.ACTIVE or review.content_draft_id != draft.id:
                raise PublicationPreconditionError(
                    "the ACTIVE review no longer covers the ACTIVE draft; "
                    "route rework through the editorial stages instead"
                )
            target = WorkflowState.QA_REVIEW
            refs = {
                "editorial_review_id": str(review.id),
                "content_draft_id": str(draft.id),
                "review_verdict": review.verdict.value,
                "content_hash": draft.content_hash,
            }
        return WorkflowService(self._session).transition(
            work_item_id,
            target,
            actor_origin=WorkflowActorOrigin.OPERATOR,
            reason=reason,
            artifact_refs=refs,
            request_id=request_id,
            actor_user_id=actor_user_id,
        )

    # --- internals ------------------------------------------------------------

    def _require_work_item(self, work_item_id: uuid.UUID) -> EditorialWorkItem:
        work_item = self._workflow.get_by_id(work_item_id)
        if work_item is None:
            raise PublicationPreconditionError(f"no editorial work item with id {work_item_id}")
        return work_item
