"""QA persistence access. No update/delete surface for immutable content
— the only mutation the repository layer participates in is the guarded
status-forward supersession performed by the service."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from contentos.qa.enums import QaReportStatus
from contentos.qa.models import QaGateWaiver, QaReport, QaReportStatusEvent


class QaRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # --- writes (insert/append only) ---------------------------------------

    def insert_report(self, report: QaReport) -> QaReport:
        self._session.add(report)
        self._session.flush()
        return report

    def append_waiver(self, waiver: QaGateWaiver) -> QaGateWaiver:
        self._session.add(waiver)
        self._session.flush()
        return waiver

    def append_status_event(self, event: QaReportStatusEvent) -> QaReportStatusEvent:
        self._session.add(event)
        self._session.flush()
        return event

    # --- reads --------------------------------------------------------------

    def get_report(self, report_id: uuid.UUID) -> QaReport | None:
        return self._session.get(QaReport, report_id)

    def get_active_report(self, work_item_id: uuid.UUID) -> QaReport | None:
        statement = select(QaReport).where(
            QaReport.work_item_id == work_item_id,
            QaReport.status == QaReportStatus.ACTIVE,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_by_work_item(self, work_item_id: uuid.UUID) -> list[QaReport]:
        statement = (
            select(QaReport).where(QaReport.work_item_id == work_item_id).order_by(QaReport.version)
        )
        return list(self._session.execute(statement).scalars())

    def next_version(self, work_item_id: uuid.UUID) -> int:
        current = self._session.scalar(
            select(func.max(QaReport.version)).where(QaReport.work_item_id == work_item_id)
        )
        return int(current or 0) + 1

    def list_waivers(self, work_item_id: uuid.UUID) -> list[QaGateWaiver]:
        statement = (
            select(QaGateWaiver)
            .where(QaGateWaiver.work_item_id == work_item_id)
            .order_by(QaGateWaiver.created_at, QaGateWaiver.id)
        )
        return list(self._session.execute(statement).scalars())

    def list_status_events(self, report_id: uuid.UUID) -> list[QaReportStatusEvent]:
        statement = (
            select(QaReportStatusEvent)
            .where(QaReportStatusEvent.report_id == report_id)
            .order_by(QaReportStatusEvent.id)
        )
        return list(self._session.execute(statement).scalars())
