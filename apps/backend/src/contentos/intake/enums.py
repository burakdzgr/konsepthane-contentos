"""Intake-run vocabularies. Values are persistence contracts."""

from enum import StrEnum


class IntakeRunStatus(StrEnum):
    """One run's lifecycle. RUNNING work is always resumable: every
    decision re-derives from durable pipeline state, never from memory."""

    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


class IntakeStage(StrEnum):
    """Which orchestration stage an event belongs to."""

    RUN = "run"
    DISCOVERY = "discovery"
    PREFILTER = "prefilter"
    FETCH = "fetch"
    PROMOTE = "promote"


class IntakeEventKind(StrEnum):
    """Frozen event codes; the admin renders display text from these."""

    RUN_STARTED = "run_started"
    RUN_PAUSED = "run_paused"
    RUN_RESUMED = "run_resumed"
    RUN_STOPPED = "run_stopped"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    DISCOVERY_STARTED = "discovery_started"
    DISCOVERY_COMPLETED = "discovery_completed"
    DISCOVERY_RETRYING = "discovery_retrying"
    PREFILTER_PROGRESS = "prefilter_progress"
    PREFILTER_COMPLETED = "prefilter_completed"
    FETCH_BATCH_DISPATCHED = "fetch_batch_dispatched"
    FETCH_ITEM_DISPATCHED = "fetch_item_dispatched"
    FETCH_PROGRESS = "fetch_progress"
    FETCH_BUDGET_EXHAUSTED = "fetch_budget_exhausted"
    FETCH_CAP_REACHED = "fetch_cap_reached"
    FETCH_COMPLETED = "fetch_completed"
    PROMOTION_DISPATCHED = "promotion_dispatched"
    PROMOTION_CAP_REACHED = "promotion_cap_reached"
    OPERATIONAL_PAUSE = "operational_pause"
    STEP_ERROR = "step_error"
