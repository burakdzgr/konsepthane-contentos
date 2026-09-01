"""Narrow persistence access for the workflow aggregate. Callers own commit.

No update or delete surface exists: events are append-only and the work
item's denormalized projection is mutated only by WorkflowService.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.workflow.enums import WorkflowState
from contentos.workflow.models import EditorialWorkflowEvent, EditorialWorkItem


class WorkflowRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def insert_work_item(self, item: EditorialWorkItem) -> EditorialWorkItem:
        self._session.add(item)
        self._session.flush()
        return item

    def append_event(self, event: EditorialWorkflowEvent) -> EditorialWorkflowEvent:
        self._session.add(event)
        self._session.flush()
        return event

    def get_by_id(self, work_item_id: uuid.UUID) -> EditorialWorkItem | None:
        return self._session.get(EditorialWorkItem, work_item_id)

    def get_by_id_for_update(self, work_item_id: uuid.UUID) -> EditorialWorkItem | None:
        """Lock one work item for a transaction-scoped state transition."""
        statement = (
            select(EditorialWorkItem).where(EditorialWorkItem.id == work_item_id).with_for_update()
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_events(self, work_item_id: uuid.UUID) -> list[EditorialWorkflowEvent]:
        """Full history in append (audit) order."""
        statement = (
            select(EditorialWorkflowEvent)
            .where(EditorialWorkflowEvent.work_item_id == work_item_id)
            .order_by(EditorialWorkflowEvent.id)
        )
        return list(self._session.execute(statement).scalars())

    def get_latest_entry_event(
        self, work_item_id: uuid.UUID, to_state: WorkflowState
    ) -> EditorialWorkflowEvent | None:
        """The newest event that entered ``to_state`` (for resume derivation)."""
        statement = (
            select(EditorialWorkflowEvent)
            .where(
                EditorialWorkflowEvent.work_item_id == work_item_id,
                EditorialWorkflowEvent.to_state == to_state,
            )
            .order_by(EditorialWorkflowEvent.id.desc())
            .limit(1)
        )
        return self._session.execute(statement).scalar_one_or_none()
