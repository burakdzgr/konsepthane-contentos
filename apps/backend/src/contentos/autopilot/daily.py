"""Daily preparation reservations. Caller commits; no editorial state is invented.

The singleton lock serializes admissions across concurrent sweeps. Unfinished
reservations carry over and consume capacity before new work. A preparation
counts only once, on its first real human-review transition (Istanbul day).
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from contentos.autopilot.enums import AutopilotEventKind
from contentos.autopilot.models import (
    AutopilotEvent,
    AutopilotSetting,
    AutopilotSource,
    DailyPreparation,
)
from contentos.autopilot.service import AutopilotService
from contentos.core.config import Settings
from contentos.discovery.models import DiscoveryItem
from contentos.fetching.snapshots import FetchSnapshot
from contentos.intake.enums import IntakeRunStatus
from contentos.intake.models import IntakeRun
from contentos.intake.service import AUTOMATED_PAIRS, IntakePolicy, IntakeRunService
from contentos.normalization.models import NormalizedDocument
from contentos.opportunities.models import EditorialOpportunity
from contentos.opportunities.repository import OpportunityRepository
from contentos.opportunities.service import commissioning_admits
from contentos.sources.enums import SourceLifecycleState
from contentos.sources.models import Source
from contentos.workflow.enums import WorkflowState
from contentos.workflow.models import EditorialWorkflowEvent, EditorialWorkItem

ISTANBUL = ZoneInfo("Europe/Istanbul")
FINISHED = {WorkflowState.REJECTED, WorkflowState.ARCHIVED}
PUBLICATION = {WorkflowState.APPROVED, WorkflowState.SCHEDULED}


def local_day(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(ISTANBUL).date()


class DailyPreparationService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def configure(self, target: int, source_ids: list[uuid.UUID]) -> None:
        if not 1 <= target <= 50 or not source_ids or len(source_ids) > 50:
            raise ValueError("Günlük hedef 1–50 olmalı ve en az bir kaynak seçilmeli.")
        selected = set(source_ids)
        sources = list(self.session.scalars(select(Source).where(Source.id.in_(selected))))
        if len(sources) != len(selected) or any(
            source.lifecycle_state is not SourceLifecycleState.ACTIVE for source in sources
        ):
            raise ValueError("Yalnızca kayıtlı ve aktif kaynakları seçebilirsiniz.")
        setting = self.session.get(AutopilotSetting, 1, with_for_update=True)
        if setting is None:
            raise ValueError("Önce botun sorumlu operatörü kaydedilmeli.")
        setting.daily_target = target
        existing = set(self.session.scalars(select(AutopilotSource.source_id)))
        self.session.execute(
            delete(AutopilotSource).where(AutopilotSource.source_id.not_in(selected))
        )
        self.session.add_all(AutopilotSource(source_id=value) for value in selected - existing)
        self.session.flush()

    def start_daily_research(self, settings: Settings) -> list[uuid.UUID]:
        setting = self.session.get(AutopilotSetting, 1, with_for_update=True)
        if setting is None or setting.daily_target is None:
            return []
        day = local_day()
        runs: list[uuid.UUID] = []
        service = IntakeRunService(self.session)
        for selection in self.session.scalars(select(AutopilotSource)):
            source = self.session.get(Source, selection.source_id)
            if source is None or source.lifecycle_state != SourceLifecycleState.ACTIVE:
                continue
            if (source.kind, source.discovery_strategy) not in AUTOMATED_PAIRS:
                continue
            live = service.live_run_for_source(source.id)
            if live is not None:
                # Recover a lost dispatch/timer, without resuming operator-paused runs.
                updated = (
                    live.updated_at
                    if live.updated_at.tzinfo
                    else live.updated_at.replace(tzinfo=UTC)
                )
                if (
                    live.status == IntakeRunStatus.RUNNING
                    and updated < datetime.now(UTC) - timedelta(minutes=5)
                    and self._research_dispatch_due(live.id)
                ):
                    self._record_research_dispatch(live.id, setting)
                    runs.append(live.id)
                continue
            if selection.last_researched_on == day:
                continue
            run = service.start_run(
                source.id,
                policy=IntakePolicy.from_settings(settings),
                actor_user_id=setting.actor_user_id,
            )
            selection.last_researched_on = day
            self._record_research_dispatch(run.id, setting)
            runs.append(run.id)
        self.session.flush()
        return runs

    def _research_dispatch_due(self, run_id: uuid.UUID) -> bool:
        return (
            self.session.scalar(
                select(AutopilotEvent.id)
                .where(
                    AutopilotEvent.action == "daily_research_dispatch",
                    AutopilotEvent.detail["run_id"].as_string() == str(run_id),
                    AutopilotEvent.created_at >= datetime.now(UTC) - timedelta(minutes=5),
                )
                .limit(1)
            )
            is None
        )

    def _record_research_dispatch(self, run_id: uuid.UUID, setting: AutopilotSetting) -> None:
        AutopilotService(self.session).record(
            AutopilotEventKind.ACTION,
            work_item_id=None,
            action="daily_research_dispatch",
            mode=setting.mode,
            detail={"run_id": str(run_id), "reason": "Günlük kaynak taraması"},
        )

    def reconcile(self) -> None:
        rows = self.session.scalars(
            select(DailyPreparation).where(DailyPreparation.completed_on.is_(None))
        )
        for row in rows:
            event = self.session.scalar(
                select(EditorialWorkflowEvent)
                .where(
                    EditorialWorkflowEvent.work_item_id == row.work_item_id,
                    EditorialWorkflowEvent.to_state == WorkflowState.AWAITING_HUMAN_REVIEW,
                )
                .order_by(EditorialWorkflowEvent.id)
                .limit(1)
            )
            if event is not None:
                stamp = event.occurred_at
                row.completed_on = local_day(stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC))
        self.session.flush()

    def reserve(
        self, candidate_ids: list[uuid.UUID], *, today: date | None = None
    ) -> list[uuid.UUID]:
        setting = self.session.get(AutopilotSetting, 1, with_for_update=True)
        if setting is None or setting.daily_target is None:
            return candidate_ids  # compatibility: daily planning is explicitly opt-in
        self.reconcile()
        day = today or local_day()
        rows = list(
            self.session.execute(
                select(DailyPreparation, EditorialWorkItem).join(
                    EditorialWorkItem, EditorialWorkItem.id == DailyPreparation.work_item_id
                )
            )
        )
        completed = sum(row.completed_on == day for row, _ in rows)
        active = {
            row.work_item_id
            for row, item in rows
            if row.completed_on is None and item.current_state not in FINISHED
        }
        known = {row.work_item_id for row, _ in rows}
        capacity = max(0, setting.daily_target - completed - len(active))
        allowed_sources = select(AutopilotSource.source_id)
        eligible_ids = set(
            self.session.scalars(
                select(EditorialOpportunity.work_item_id)
                .join(
                    NormalizedDocument,
                    NormalizedDocument.id == EditorialOpportunity.promotion_root_document_id,
                )
                .join(FetchSnapshot, FetchSnapshot.id == NormalizedDocument.fetch_snapshot_id)
                .join(DiscoveryItem, DiscoveryItem.id == FetchSnapshot.discovery_item_id)
                .join(Source, Source.id == DiscoveryItem.source_id)
                .where(
                    Source.id.in_(allowed_sources),
                    Source.lifecycle_state == SourceLifecycleState.ACTIVE,
                    EditorialOpportunity.work_item_id.in_(candidate_ids),
                )
            )
        )
        for candidate in candidate_ids:
            if capacity <= 0:
                break
            if candidate in known or candidate not in eligible_ids:
                continue
            item = self.session.get(EditorialWorkItem, candidate)
            if item is None or item.current_state in PUBLICATION:
                continue
            if item.current_state == WorkflowState.IDEA_SCORING:
                repo = OpportunityRepository(self.session)
                opportunity = repo.get_by_work_item_id(candidate)
                score = repo.get_effective_score(opportunity.id) if opportunity else None
                if opportunity is None or not commissioning_admits(
                    disposition=opportunity.disposition,
                    work_item_state=item.current_state,
                    score_eligibility=score.eligibility if score else None,
                ):
                    continue
            self.session.add(DailyPreparation(work_item_id=candidate, reserved_on=day))
            active.add(candidate)
            capacity -= 1
        self.session.flush()
        # Already human-approved publication is independent of preparation quota.
        publication = set(
            self.session.scalars(
                select(EditorialWorkItem.id).where(
                    EditorialWorkItem.id.in_(candidate_ids),
                    EditorialWorkItem.current_state.in_(PUBLICATION),
                )
            )
        )
        return [value for value in candidate_ids if value in active or value in publication]

    def permits(self, item: EditorialWorkItem) -> bool:
        setting = self.session.get(AutopilotSetting, 1)
        return (
            setting is None
            or setting.daily_target is None
            or item.current_state in PUBLICATION
            or self.session.get(DailyPreparation, item.id) is not None
        )

    def view(self) -> dict[str, Any]:
        setting = self.session.get(AutopilotSetting, 1)
        selected = set(self.session.scalars(select(AutopilotSource.source_id)))
        rows = list(
            self.session.execute(
                select(DailyPreparation, EditorialWorkItem)
                .join(EditorialWorkItem, EditorialWorkItem.id == DailyPreparation.work_item_id)
                .order_by(DailyPreparation.reserved_on.desc(), EditorialWorkItem.created_at.desc())
            )
        )
        day = local_day()
        completed = sum(row.completed_on == day for row, _ in rows)
        pending = [
            (row, item)
            for row, item in rows
            if row.completed_on is None and item.current_state not in FINISHED
        ]
        latest = AutopilotService(self.session).latest_per_work_item([item.id for _, item in rows])
        return {
            "target": setting.daily_target if setting else None,
            "mode": setting.mode.value if setting else "off",
            "day": day.isoformat(),
            "timezone": "Europe/Istanbul",
            "completed": completed,
            "in_progress": len(pending),
            "research": [
                {
                    "source": source.name,
                    "status": run.status.value,
                    "fetched": run.fetched,
                    "opportunities": run.opportunities_created,
                }
                for run, source in self.session.execute(
                    select(IntakeRun, Source)
                    .join(Source, Source.id == IntakeRun.source_id)
                    .where(Source.id.in_(selected))
                    .order_by(IntakeRun.created_at.desc())
                    .limit(3)
                )
            ],
            "sources": [
                {
                    "id": str(source.id),
                    "name": source.name,
                    "selected": source.id in selected,
                    "active": source.lifecycle_state == SourceLifecycleState.ACTIVE,
                }
                for source in self.session.scalars(select(Source).order_by(Source.name))
            ],
            "items": [
                {
                    "id": str(item.id),
                    "title": item.title_working_label,
                    "state": item.current_state.value,
                    "completed": row.completed_on is not None,
                    "reserved_on": row.reserved_on.isoformat(),
                    "reason": item.blocked_reason
                    or (
                        str(latest[item.id].detail.get("reason", "")) or None
                        if item.id in latest
                        else None
                    ),
                }
                for row, item in rows
                if row.completed_on == day or (row, item) in pending
            ][:100],
        }
