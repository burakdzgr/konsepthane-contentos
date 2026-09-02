"""Read-only projections for Phase-4 QA reports.

DURABLE rows only: gate results exactly as persisted (unsatisfied and
UNKNOWN are never softened), the versioned gate policy, audited waivers
(always visible), package pins, and the supersession audit. QA v1 has no
AI attempts by design.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.api.read_models.editorial import _FrozenModel
from contentos.qa.enums import QaActorOrigin, QaOutcome, QaReportStatus, WaivableGateKey
from contentos.qa.models import QaGateWaiver, QaReport, QaReportStatusEvent
from contentos.workflow.models import EditorialWorkItem

MAX_QA_REPORTS_PER_WORK_ITEM = 50


class QaReportSummaryView(_FrozenModel):
    id: uuid.UUID
    work_item_id: uuid.UUID
    content_draft_id: uuid.UUID
    editorial_review_id: uuid.UUID
    content_brief_id: uuid.UUID
    version: int
    outcome: QaOutcome
    status: QaReportStatus
    # gate key -> its persisted result string ("pass", "fail",
    # "unsatisfied", "waived_by_human", "not_applicable", "none",
    # "pending"); unknown shapes surface as "UNKNOWN", never as a pass.
    gate_summary: dict[str, str]
    engine_name: str
    engine_version: str
    superseded_by_report_id: uuid.UUID | None
    content_hash: str
    created_at: datetime


class QaReportListPage(_FrozenModel):
    work_item_id: uuid.UUID
    reports: list[QaReportSummaryView]
    waivers: list["QaWaiverView"]
    total: int
    truncated: bool


class QaWaiverView(_FrozenModel):
    id: uuid.UUID
    gate_key: WaivableGateKey
    reason: str
    request_id: str | None
    created_at: datetime


class QaReportStatusEventView(_FrozenModel):
    id: int
    from_status: QaReportStatus
    to_status: QaReportStatus
    actor_origin: QaActorOrigin
    reason: str
    request_id: str | None
    replacement_report_id: uuid.UUID | None
    occurred_at: datetime


class QaReportDetail(_FrozenModel):
    report: QaReportSummaryView
    gate_results: dict[str, Any]
    gate_policy_snapshot: dict[str, Any]
    waivers: list[QaWaiverView]
    status_events: list[QaReportStatusEventView]


def _gate_summary(gate_results: dict[str, Any]) -> dict[str, str]:
    summary: dict[str, str] = {}
    for gate_key, detail in (gate_results or {}).items():
        result = detail.get("result") if isinstance(detail, dict) else None
        summary[str(gate_key)] = result if isinstance(result, str) else "UNKNOWN"
    return summary


def _summary_view(report: QaReport) -> QaReportSummaryView:
    return QaReportSummaryView(
        id=report.id,
        work_item_id=report.work_item_id,
        content_draft_id=report.content_draft_id,
        editorial_review_id=report.editorial_review_id,
        content_brief_id=report.content_brief_id,
        version=report.version,
        outcome=report.outcome,
        status=report.status,
        gate_summary=_gate_summary(report.gate_results),
        engine_name=report.engine_name,
        engine_version=report.engine_version,
        superseded_by_report_id=report.superseded_by_report_id,
        content_hash=report.content_hash,
        created_at=report.created_at,
    )


def _waiver_views(session: Session, work_item_id: uuid.UUID) -> list[QaWaiverView]:
    rows = session.execute(
        select(QaGateWaiver)
        .where(QaGateWaiver.work_item_id == work_item_id)
        .order_by(QaGateWaiver.created_at, QaGateWaiver.id)
    ).scalars()
    return [
        QaWaiverView(
            id=waiver.id,
            gate_key=waiver.gate_key,
            reason=waiver.reason,
            request_id=waiver.request_id,
            created_at=waiver.created_at,
        )
        for waiver in rows
    ]


def list_work_item_qa_reports(session: Session, work_item_id: uuid.UUID) -> QaReportListPage | None:
    """Every QA report version of one work item (newest first) plus the
    work item's audited waivers — always visible."""
    if session.get(EditorialWorkItem, work_item_id) is None:
        return None
    rows = list(
        session.execute(
            select(QaReport)
            .where(QaReport.work_item_id == work_item_id)
            .order_by(QaReport.version.desc())
        ).scalars()
    )
    return QaReportListPage(
        work_item_id=work_item_id,
        reports=[_summary_view(report) for report in rows[:MAX_QA_REPORTS_PER_WORK_ITEM]],
        waivers=_waiver_views(session, work_item_id),
        total=len(rows),
        truncated=len(rows) > MAX_QA_REPORTS_PER_WORK_ITEM,
    )


def get_qa_report_detail(session: Session, report_id: uuid.UUID) -> QaReportDetail | None:
    """One QA report in full: gate results as persisted, the versioned gate
    policy, the work item's waivers, and the supersession audit."""
    report = session.get(QaReport, report_id)
    if report is None:
        return None
    status_events = [
        QaReportStatusEventView(
            id=event.id,
            from_status=event.from_status,
            to_status=event.to_status,
            actor_origin=event.actor_origin,
            reason=event.reason,
            request_id=event.request_id,
            replacement_report_id=event.replacement_report_id,
            occurred_at=event.occurred_at,
        )
        for event in session.execute(
            select(QaReportStatusEvent)
            .where(QaReportStatusEvent.report_id == report.id)
            .order_by(QaReportStatusEvent.id)
        ).scalars()
    ]
    return QaReportDetail(
        report=_summary_view(report),
        gate_results=report.gate_results,
        gate_policy_snapshot=report.gate_policy_snapshot,
        waivers=_waiver_views(session, report.work_item_id),
        status_events=status_events,
    )
