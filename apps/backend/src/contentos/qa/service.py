"""QaService: package resolution + idempotent report persistence.

Task 16 scope (PHASE4_QA_ARCHITECTURE.md §8): the deterministic
package-resolution gates (the work item is in QA_REVIEW; the validated
entry event pins the editorial review AND the draft; the pins resolve to
the ACTIVE pass review covering the ACTIVE draft over the accepted
brief) and the idempotent persistence of QaReport rows (identical
content_hash reuses the ACTIVE report; a changed re-run supersedes it
with an audited SYSTEM event). The gate ENGINE that computes the seven
qa-gates/1 results is Task 17 and calls this service.

The service flushes; the caller owns COMMIT.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from contentos.ai.hashing import sha256_hex
from contentos.briefs.enums import BriefStatus
from contentos.briefs.models import ContentBrief
from contentos.briefs.repository import BriefRepository
from contentos.core.context import is_valid_request_id
from contentos.drafts.models import ContentDraft
from contentos.drafts.repository import DraftRepository
from contentos.qa.enums import (
    QaActorOrigin,
    QaOutcome,
    QaReportStatus,
    WaivableGateKey,
)
from contentos.qa.errors import (
    QaConflictError,
    QaInputError,
    QaPackageError,
    QaPreconditionError,
)
from contentos.qa.models import QaGateWaiver, QaReport, QaReportStatusEvent
from contentos.qa.repository import QaRepository
from contentos.qa.values import (
    MAX_REASON_LENGTH,
    QA_ENGINE_NAME,
    QA_ENGINE_VERSION,
)
from contentos.reviews.enums import ReviewStatus, ReviewVerdict
from contentos.reviews.models import EditorialReview
from contentos.reviews.repository import ReviewRepository
from contentos.workflow.enums import WorkflowState
from contentos.workflow.repository import WorkflowRepository


@dataclass(frozen=True, slots=True)
class QaPackage:
    """The exact entry-pinned package a QA run evaluates."""

    work_item_id: uuid.UUID
    draft: ContentDraft
    review: EditorialReview
    brief: ContentBrief


@dataclass(frozen=True, slots=True)
class QaReportPersistence:
    """`created` is False when an idempotent identical run was reused."""

    report: QaReport
    created: bool
    superseded_report_id: uuid.UUID | None


class QaService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = QaRepository(session)
        self._drafts = DraftRepository(session)
        self._reviews = ReviewRepository(session)
        self._briefs = BriefRepository(session)
        self._workflow = WorkflowRepository(session)

    # --- package resolution (deterministic preconditions) -------------------

    def resolve_package(self, work_item_id: uuid.UUID) -> QaPackage:
        work_item = self._workflow.get_by_id(work_item_id)
        if work_item is None:
            raise QaPreconditionError(f"no editorial work item with id {work_item_id}")
        if work_item.current_state is not WorkflowState.QA_REVIEW:
            raise QaPreconditionError(
                f"a QA run requires QA_REVIEW (current: {work_item.current_state.value})"
            )
        entry = self._workflow.get_latest_entry_event(work_item_id, WorkflowState.QA_REVIEW)
        refs = (entry.artifact_refs or {}) if entry is not None else {}
        pinned_review_id = _parse_pin(refs.get("editorial_review_id"), "editorial_review_id")
        pinned_draft_id = _parse_pin(refs.get("content_draft_id"), "content_draft_id")

        review = self._reviews.get_active_review(work_item_id)
        draft = self._drafts.get_active_draft(work_item_id)
        if review is None or draft is None:
            raise QaPackageError(
                "the work item has no ACTIVE editorial review and ACTIVE draft to evaluate"
            )
        if review.id != pinned_review_id or draft.id != pinned_draft_id:
            raise QaPackageError(
                "the ACTIVE review/draft do not match the QA_REVIEW entry pins; "
                "refusing to evaluate ambiguous state"
            )
        if review.verdict is not ReviewVerdict.PASS:
            raise QaPackageError(
                f"the pinned review verdict is '{review.verdict.value}', not 'pass'"
            )
        if review.status is not ReviewStatus.ACTIVE or review.content_draft_id != draft.id:
            raise QaPackageError("the pinned review does not cover the ACTIVE draft")
        brief = self._briefs.get_brief(draft.content_brief_id)
        if brief is None or brief.status is not BriefStatus.ACCEPTED_FOR_DRAFTING:
            status = brief.status.value if brief is not None else "missing"
            raise QaPackageError(
                "the package's brief is no longer the accepted writing contract "
                f"(brief status: {status})"
            )
        return QaPackage(work_item_id=work_item_id, draft=draft, review=review, brief=brief)

    # --- report persistence --------------------------------------------------

    def persist_report(
        self,
        package: QaPackage,
        *,
        outcome: QaOutcome,
        gate_results: dict[str, Any],
        gate_policy_snapshot: dict[str, Any],
        request_id: str | None = None,
    ) -> QaReportPersistence:
        if not isinstance(outcome, QaOutcome):
            raise QaInputError("outcome must be a QaOutcome value")
        validated_request_id = _validate_request_id(request_id)
        content_hash = sha256_hex(
            {
                "work_item_id": str(package.work_item_id),
                "content_draft_id": str(package.draft.id),
                "draft_content_hash": package.draft.content_hash,
                "editorial_review_id": str(package.review.id),
                "review_content_hash": package.review.content_hash,
                "content_brief_id": str(package.brief.id),
                "outcome": outcome.value,
                "gate_results": gate_results,
                "gate_policy": gate_policy_snapshot,
                "engine": [QA_ENGINE_NAME, QA_ENGINE_VERSION],
            }
        )

        active = self._repository.get_active_report(package.work_item_id)
        if active is not None and active.content_hash == content_hash:
            # An identical deterministic re-run: idempotent reuse.
            return QaReportPersistence(report=active, created=False, superseded_report_id=None)

        try:
            with self._session.begin_nested():
                if active is not None:
                    active.status = QaReportStatus.SUPERSEDED
                    self._session.flush()
                report = self._repository.insert_report(
                    QaReport(
                        work_item_id=package.work_item_id,
                        content_draft_id=package.draft.id,
                        editorial_review_id=package.review.id,
                        content_brief_id=package.brief.id,
                        version=self._repository.next_version(package.work_item_id),
                        outcome=outcome,
                        gate_results=gate_results,
                        gate_policy_snapshot=gate_policy_snapshot,
                        engine_name=QA_ENGINE_NAME,
                        engine_version=QA_ENGINE_VERSION,
                        status=QaReportStatus.ACTIVE,
                        content_hash=content_hash,
                    )
                )
                if active is not None:
                    active.superseded_by_report_id = report.id
                    self._repository.append_status_event(
                        QaReportStatusEvent(
                            report_id=active.id,
                            from_status=QaReportStatus.ACTIVE,
                            to_status=QaReportStatus.SUPERSEDED,
                            # Re-runs are deterministic recomputation, not a
                            # human judgment — the system supersedes.
                            actor_origin=QaActorOrigin.SYSTEM,
                            reason=(
                                "deterministic re-run produced a different "
                                "result over the current durable state"
                            ),
                            request_id=validated_request_id,
                            replacement_report_id=report.id,
                            occurred_at=datetime.now(UTC),
                        )
                    )
        except IntegrityError:
            winner = self._repository.get_active_report(package.work_item_id)
            if winner is not None and winner.content_hash == content_hash:
                return QaReportPersistence(report=winner, created=False, superseded_report_id=None)
            raise QaConflictError(
                "QA report persistence conflicted with concurrently written state"
            ) from None

        return QaReportPersistence(
            report=report,
            created=True,
            superseded_report_id=active.id if active is not None else None,
        )

    # --- waivers --------------------------------------------------------------

    def add_waiver(
        self,
        work_item_id: uuid.UUID,
        gate_key: WaivableGateKey,
        *,
        reason: str,
        request_id: str | None = None,
    ) -> QaGateWaiver:
        """Audited human waiver of one waivable gate. It does not re-run
        gates by itself — the next run consumes it; needs stay visible."""
        if not isinstance(gate_key, WaivableGateKey):
            raise QaInputError("gate_key must be a waivable gate")
        work_item = self._workflow.get_by_id(work_item_id)
        if work_item is None:
            raise QaPreconditionError(f"no editorial work item with id {work_item_id}")
        if work_item.current_state is not WorkflowState.QA_REVIEW:
            raise QaPreconditionError(
                f"a QA waiver requires QA_REVIEW (current: {work_item.current_state.value})"
            )
        return self._repository.append_waiver(
            QaGateWaiver(
                work_item_id=work_item_id,
                gate_key=gate_key,
                reason=_required_reason(reason),
                request_id=_validate_request_id(request_id),
            )
        )


def _parse_pin(value: Any, name: str) -> uuid.UUID:
    if not isinstance(value, str):
        raise QaPreconditionError(f"the durable QA_REVIEW entry event does not pin {name}")
    try:
        return uuid.UUID(value)
    except ValueError:
        raise QaPreconditionError(
            f"the durable QA_REVIEW entry event pins an unparseable {name}"
        ) from None


def _validate_request_id(value: str | None) -> str | None:
    if value is None:
        return None
    if not is_valid_request_id(value):
        raise QaInputError("request_id is not a valid correlation identifier")
    return value


def _required_reason(value: str) -> str:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned or len(cleaned) > MAX_REASON_LENGTH:
        raise QaInputError(f"reason must be 1..{MAX_REASON_LENGTH} characters")
    return cleaned
