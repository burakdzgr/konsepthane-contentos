"""The live operations projection (ADR 0012): ONE read for ONE page.

Everything the operator needs to watch the whole line — intake runs, every
work item on the editorial line with the autopilot's last word about it,
the newest AI attempts, and the AI gateway's own health — assembled from
durable rows plus one bounded, server-side call to the gateway's admin
status endpoint. The gateway admin token never reaches a browser.

Read-only: nothing here writes, enqueues, or touches a provider.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.ai.enums import GenerationPurpose, GenerationStatus
from contentos.ai.models import AiGenerationAttempt
from contentos.api.read_models.intake import IntakeRunView, load_runs
from contentos.auth.models import User
from contentos.autopilot.enums import AutopilotEventKind, AutopilotMode
from contentos.autopilot.runner import ACTIONABLE_STATES
from contentos.autopilot.service import AutopilotService
from contentos.core.config import Settings
from contentos.workflow.enums import WorkflowActorOrigin, WorkflowState
from contentos.workflow.models import EditorialWorkflowEvent, EditorialWorkItem

MAX_ITEMS = 100
MAX_FEED = 60
GATEWAY_TIMEOUT_SECONDS = 4.0

# States shown on the board, in line order (terminal states are omitted).
BOARD_STATES: tuple[WorkflowState, ...] = (
    *ACTIONABLE_STATES,
    WorkflowState.AWAITING_HUMAN_REVIEW,
    WorkflowState.BLOCKED,
    WorkflowState.PUBLISHING,
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class AutopilotView(_Frozen):
    mode: AutopilotMode
    actor_display_name: str | None
    reason: str | None
    updated_at: datetime | None


class AutopilotWordView(_Frozen):
    kind: AutopilotEventKind
    action: str | None
    reason: str | None
    at: datetime


class LineItemView(_Frozen):
    work_item_id: uuid.UUID
    title: str
    state: WorkflowState
    entered_at: datetime
    blocked_reason: str | None
    autopilot: AutopilotWordView | None


class FeedEntryView(_Frozen):
    at: datetime
    source: str  # "autopilot" | "workflow" | "ai"
    work_item_id: uuid.UUID | None
    title: str | None
    summary: str
    tone: str  # "ok" | "warn" | "bad" | "info"


class GatewayAccountView(_Frozen):
    id: str
    provider: str
    label: str
    enabled: bool
    blocked_by: str | None
    busy: bool


class GatewayJobView(_Frozen):
    job_id: str
    status: str
    phase: str | None
    model: str | None
    job_type: str | None
    started_at: str | None


class GatewayView(_Frozen):
    configured: bool
    reachable: bool
    status: str | None  # ok | degraded | ...
    provider: str
    base_url_host: str | None
    accounts: list[GatewayAccountView]
    queued: int | None
    running: int | None
    ready_accounts: int | None
    jobs: list[GatewayJobView]
    error: str | None


class LiveOperationsView(_Frozen):
    generated_at: datetime
    autopilot: AutopilotView
    intake_runs: list[IntakeRunView]
    items: list[LineItemView]
    feed: list[FeedEntryView]
    gateway: GatewayView


# --- gateway -----------------------------------------------------------------


def _read_gateway(settings: Settings, http: httpx.Client | None = None) -> GatewayView:
    provider = settings.ai_provider
    base = settings.subcontractor_base_url
    token = settings.subcontractor_admin_token
    if provider != "subcontractor" or base is None:
        return GatewayView(
            configured=False,
            reachable=False,
            status=None,
            provider=provider,
            base_url_host=None,
            accounts=[],
            queued=None,
            running=None,
            ready_accounts=None,
            jobs=[],
            error=None,
        )
    host = httpx.URL(base).host
    client = http or httpx.Client(base_url=base, timeout=GATEWAY_TIMEOUT_SECONDS)
    try:
        if token is None:
            # Without the admin token only the unauthenticated health summary exists.
            response = client.get("/health")
        else:
            response = client.get(
                "/api/status",
                params={"queues": "1"},
                headers={"Authorization": f"Bearer {token.get_secret_value()}"},
            )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as error:
        return GatewayView(
            configured=True,
            reachable=False,
            status=None,
            provider=provider,
            base_url_host=host,
            accounts=[],
            queued=None,
            running=None,
            ready_accounts=None,
            jobs=[],
            error=type(error).__name__,
        )
    finally:
        if http is None:
            client.close()
    return _gateway_view(payload, provider=provider, host=host)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _gateway_view(payload: dict[str, Any], *, provider: str, host: str | None) -> GatewayView:
    scheduler = _dict(payload.get("scheduler"))
    providers = _dict(scheduler.get("saglayici"))
    ready = sum(int(_dict(entry).get("hazir", 0)) for entry in providers.values())
    accounts = [
        GatewayAccountView(
            id=str(entry.get("id", "")),
            provider=str(entry.get("provider", "")),
            label=str(entry.get("label", "")),
            enabled=bool(entry.get("enabled", False)),
            blocked_by=entry.get("blockedBy") if isinstance(entry.get("blockedBy"), str) else None,
            busy=bool(entry.get("busy", False)),
        )
        for entry in _list(payload.get("accounts"))
        if isinstance(entry, dict)
    ]
    jobs_raw = _dict(payload.get("jobStore"))
    running_list = _list(jobs_raw.get("running"))
    jobs = [
        GatewayJobView(
            job_id=str(entry.get("jobId") or entry.get("job_id") or ""),
            status=str(entry.get("status", "running")),
            phase=entry.get("phase") if isinstance(entry.get("phase"), str) else None,
            model=entry.get("model") if isinstance(entry.get("model"), str) else None,
            job_type=entry.get("type") if isinstance(entry.get("type"), str) else None,
            started_at=entry.get("startedAt") if isinstance(entry.get("startedAt"), str) else None,
        )
        for entry in running_list
        if isinstance(entry, dict)
    ]
    by_status = _dict(jobs_raw.get("byStatus"))
    queued = by_status.get("queued")
    running = by_status.get("running")
    if running is None and isinstance(scheduler.get("mesgul"), int):
        running = scheduler["mesgul"]
    if queued is None and isinstance(scheduler.get("bekleyen"), int):
        queued = scheduler["bekleyen"]
    return GatewayView(
        configured=True,
        reachable=True,
        status=str(payload.get("status")) if payload.get("status") is not None else "ok",
        provider=provider,
        base_url_host=host,
        accounts=accounts,
        queued=int(queued) if isinstance(queued, int) else None,
        running=int(running) if isinstance(running, int) else None,
        ready_accounts=ready if providers else None,
        jobs=jobs,
        error=None,
    )


# --- feed --------------------------------------------------------------------

_AI_TONE = {
    GenerationStatus.SUCCEEDED: "ok",
    GenerationStatus.VALIDATION_FAILED: "bad",
    GenerationStatus.PROVIDER_ERROR: "warn",
    GenerationStatus.TIMEOUT: "warn",
    GenerationStatus.CANCELLED: "info",
}

_PURPOSE_TR = {
    GenerationPurpose.IDEA_CANDIDATES: "fikir adayları",
    GenerationPurpose.INTENT_SYNTHESIS: "niyet sentezi",
    GenerationPurpose.BRIEF_COMPOSITION: "brief oluşturma",
    GenerationPurpose.EVIDENCE_ORGANIZATION: "kanıt düzenleme",
    GenerationPurpose.WRITER_DRAFT: "yazar taslağı",
    GenerationPurpose.EDITOR_REVIEW: "editör değerlendirmesi",
}


def _feed(session: Session, titles: dict[uuid.UUID, str]) -> list[FeedEntryView]:
    entries: list[FeedEntryView] = []
    autopilot = AutopilotService(session)
    for event in autopilot.recent_events(MAX_FEED):
        reason = event.detail.get("reason") if isinstance(event.detail, dict) else None
        if event.kind is AutopilotEventKind.MODE_CHANGED:
            summary = f"Otopilot modu {event.detail.get('from')} → {event.detail.get('to')}"
            tone = "info"
        elif event.kind is AutopilotEventKind.ACTION:
            summary = f"Otopilot: {event.action} — {reason or ''}".rstrip(" —")
            tone = "ok"
        elif event.kind is AutopilotEventKind.WAITING:
            summary = f"Bekliyor: {reason or event.action}"
            tone = "warn"
        elif event.kind is AutopilotEventKind.ERROR:
            summary = f"Otopilot hatası: {event.action} ({event.detail.get('error_type')})"
            tone = "bad"
        else:
            summary = f"Otopilot: {event.action} atlandı"
            tone = "info"
        entries.append(
            FeedEntryView(
                at=event.created_at,
                source="autopilot",
                work_item_id=event.work_item_id,
                title=titles.get(event.work_item_id) if event.work_item_id else None,
                summary=summary,
                tone=tone,
            )
        )
    for transition in session.scalars(
        select(EditorialWorkflowEvent)
        .order_by(EditorialWorkflowEvent.occurred_at.desc(), EditorialWorkflowEvent.id.desc())
        .limit(MAX_FEED)
    ):
        actor = "sistem" if transition.actor_origin is WorkflowActorOrigin.SYSTEM else "operatör"
        if (
            isinstance(transition.artifact_refs, dict)
            and transition.artifact_refs.get("autopilot") == "true"
        ):
            actor = "otopilot"
        entries.append(
            FeedEntryView(
                at=transition.occurred_at,
                source="workflow",
                work_item_id=transition.work_item_id,
                title=titles.get(transition.work_item_id) if transition.work_item_id else None,
                summary=f"{transition.from_state.value if transition.from_state else 'başlangıç'} → {transition.to_state.value} ({actor})",
                tone="bad"
                if transition.to_state in (WorkflowState.BLOCKED, WorkflowState.REJECTED)
                else "info",
            )
        )
    for attempt in session.scalars(
        select(AiGenerationAttempt).order_by(AiGenerationAttempt.created_at.desc()).limit(MAX_FEED)
    ):
        entries.append(
            FeedEntryView(
                at=attempt.created_at,
                source="ai",
                work_item_id=None,
                title=None,
                summary=(
                    f"Yapay zeka: {_PURPOSE_TR.get(attempt.purpose, attempt.purpose.value)} — "
                    f"{attempt.status.value} ({attempt.provider}/{attempt.model_name})"
                    + (f", {attempt.error_class}" if attempt.error_class else "")
                ),
                tone=_AI_TONE.get(attempt.status, "info"),
            )
        )
    entries.sort(key=lambda entry: entry.at, reverse=True)
    return entries[:MAX_FEED]


# --- the page ----------------------------------------------------------------


def load_live_operations(
    session: Session, settings: Settings, *, gateway_http: httpx.Client | None = None
) -> LiveOperationsView:
    autopilot = AutopilotService(session)
    state = autopilot.state()
    actor = session.get(User, state.actor_user_id) if state.actor_user_id else None

    items_rows = list(
        session.scalars(
            select(EditorialWorkItem)
            .where(EditorialWorkItem.current_state.in_(BOARD_STATES))
            .order_by(EditorialWorkItem.current_state_entered_at.desc())
            .limit(MAX_ITEMS)
        )
    )
    latest_words = autopilot.latest_per_work_item([row.id for row in items_rows])
    titles = {row.id: row.title_working_label for row in items_rows}
    items = [
        LineItemView(
            work_item_id=row.id,
            title=row.title_working_label,
            state=row.current_state,
            entered_at=row.current_state_entered_at,
            blocked_reason=row.blocked_reason,
            autopilot=(
                AutopilotWordView(
                    kind=word.kind,
                    action=word.action,
                    reason=word.detail.get("reason") if isinstance(word.detail, dict) else None,
                    at=word.created_at,
                )
                if (word := latest_words.get(row.id)) is not None
                else None
            ),
        )
        for row in items_rows
    ]
    runs = [run for run in load_runs(session).runs if run.status.value in ("running", "paused")]
    return LiveOperationsView(
        generated_at=datetime.now(UTC),
        autopilot=AutopilotView(
            mode=state.mode,
            actor_display_name=actor.display_name if actor is not None else None,
            reason=state.reason,
            updated_at=state.updated_at,
        ),
        intake_runs=runs,
        items=items,
        feed=_feed(session, titles),
        gateway=_read_gateway(settings, gateway_http),
    )


def read_gateway_screenshot(settings: Settings, http: httpx.Client | None = None) -> bytes | None:
    """The gateway's `/api/screenshot` JPEG, or None when unavailable."""
    base = settings.subcontractor_base_url
    token = settings.subcontractor_admin_token
    if settings.ai_provider != "subcontractor" or base is None or token is None:
        return None
    client = http or httpx.Client(base_url=base, timeout=GATEWAY_TIMEOUT_SECONDS * 3)
    try:
        response = client.get(
            "/api/screenshot",
            headers={"Authorization": f"Bearer {token.get_secret_value()}"},
        )
    except httpx.HTTPError:
        return None
    finally:
        if http is None:
            client.close()
    if response.status_code != 200 or not response.content:
        return None
    if not response.headers.get("content-type", "").startswith("image/"):
        return None
    return response.content
