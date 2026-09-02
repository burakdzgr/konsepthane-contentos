"""Review persistence access. No update/delete surface for immutable
content — the only mutation the repository layer participates in is the
guarded status-forward supersession performed by the service."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from contentos.reviews.enums import ReviewStatus
from contentos.reviews.models import (
    EditorialReview,
    EditorialReviewFinding,
    EditorialReviewStatusEvent,
)


class ReviewRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # --- writes (insert/append only) ---------------------------------------

    def insert_review(self, review: EditorialReview) -> EditorialReview:
        self._session.add(review)
        self._session.flush()
        return review

    def insert_finding(self, finding: EditorialReviewFinding) -> EditorialReviewFinding:
        self._session.add(finding)
        self._session.flush()
        return finding

    def append_status_event(self, event: EditorialReviewStatusEvent) -> EditorialReviewStatusEvent:
        self._session.add(event)
        self._session.flush()
        return event

    # --- reads --------------------------------------------------------------

    def get_review(self, review_id: uuid.UUID) -> EditorialReview | None:
        return self._session.get(EditorialReview, review_id)

    def get_by_generation_attempt(self, attempt_id: uuid.UUID) -> EditorialReview | None:
        statement = select(EditorialReview).where(
            EditorialReview.generation_attempt_id == attempt_id
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_active_review(self, work_item_id: uuid.UUID) -> EditorialReview | None:
        statement = select(EditorialReview).where(
            EditorialReview.work_item_id == work_item_id,
            EditorialReview.status == ReviewStatus.ACTIVE,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_by_work_item(self, work_item_id: uuid.UUID) -> list[EditorialReview]:
        statement = (
            select(EditorialReview)
            .where(EditorialReview.work_item_id == work_item_id)
            .order_by(EditorialReview.version)
        )
        return list(self._session.execute(statement).scalars())

    def next_version(self, work_item_id: uuid.UUID) -> int:
        current = self._session.scalar(
            select(func.max(EditorialReview.version)).where(
                EditorialReview.work_item_id == work_item_id
            )
        )
        return int(current or 0) + 1

    def list_findings(self, review_id: uuid.UUID) -> list[EditorialReviewFinding]:
        statement = (
            select(EditorialReviewFinding)
            .where(EditorialReviewFinding.review_id == review_id)
            .order_by(EditorialReviewFinding.finding_key)
        )
        return list(self._session.execute(statement).scalars())

    def list_status_events(self, review_id: uuid.UUID) -> list[EditorialReviewStatusEvent]:
        statement = (
            select(EditorialReviewStatusEvent)
            .where(EditorialReviewStatusEvent.review_id == review_id)
            .order_by(EditorialReviewStatusEvent.id)
        )
        return list(self._session.execute(statement).scalars())
