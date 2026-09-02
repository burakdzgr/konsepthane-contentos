"""Draft persistence access. No update/delete surface for immutable
content — the only mutation the repository layer participates in is the
guarded status-forward supersession performed by the service."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from contentos.drafts.enums import DraftStatus
from contentos.drafts.models import ContentDraft, DraftClaimUsage, DraftStatusEvent


class DraftRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # --- writes (insert/append only) ---------------------------------------

    def insert_draft(self, draft: ContentDraft) -> ContentDraft:
        self._session.add(draft)
        self._session.flush()
        return draft

    def insert_claim_usage(self, usage: DraftClaimUsage) -> DraftClaimUsage:
        self._session.add(usage)
        self._session.flush()
        return usage

    def append_status_event(self, event: DraftStatusEvent) -> DraftStatusEvent:
        self._session.add(event)
        self._session.flush()
        return event

    # --- reads --------------------------------------------------------------

    def get_draft(self, draft_id: uuid.UUID) -> ContentDraft | None:
        return self._session.get(ContentDraft, draft_id)

    def get_by_generation_attempt(self, attempt_id: uuid.UUID) -> ContentDraft | None:
        statement = select(ContentDraft).where(ContentDraft.generation_attempt_id == attempt_id)
        return self._session.execute(statement).scalar_one_or_none()

    def get_by_manual_identity(
        self, work_item_id: uuid.UUID, manual_input_hash: str
    ) -> ContentDraft | None:
        statement = select(ContentDraft).where(
            ContentDraft.work_item_id == work_item_id,
            ContentDraft.manual_input_hash == manual_input_hash,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_active_draft(self, work_item_id: uuid.UUID) -> ContentDraft | None:
        statement = select(ContentDraft).where(
            ContentDraft.work_item_id == work_item_id,
            ContentDraft.status == DraftStatus.ACTIVE,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_by_work_item(self, work_item_id: uuid.UUID) -> list[ContentDraft]:
        statement = (
            select(ContentDraft)
            .where(ContentDraft.work_item_id == work_item_id)
            .order_by(ContentDraft.version)
        )
        return list(self._session.execute(statement).scalars())

    def next_version(self, work_item_id: uuid.UUID) -> int:
        current = self._session.scalar(
            select(func.max(ContentDraft.version)).where(ContentDraft.work_item_id == work_item_id)
        )
        return int(current or 0) + 1

    def list_claim_usages(self, draft_id: uuid.UUID) -> list[DraftClaimUsage]:
        statement = (
            select(DraftClaimUsage)
            .where(DraftClaimUsage.draft_id == draft_id)
            .order_by(DraftClaimUsage.created_at, DraftClaimUsage.id)
        )
        return list(self._session.execute(statement).scalars())

    def list_status_events(self, draft_id: uuid.UUID) -> list[DraftStatusEvent]:
        statement = (
            select(DraftStatusEvent)
            .where(DraftStatusEvent.draft_id == draft_id)
            .order_by(DraftStatusEvent.id)
        )
        return list(self._session.execute(statement).scalars())
