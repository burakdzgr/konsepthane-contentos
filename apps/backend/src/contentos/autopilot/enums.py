"""Autopilot vocabulary (ADR 0012). Values are persistence contracts."""

from enum import StrEnum


class AutopilotMode(StrEnum):
    """How far the pipeline may advance without a human click.

    OFF        — every editorial step stays an explicit operator command
                 (the pre-ADR-0012 behaviour).
    SUPERVISED — the machine PRODUCES every artifact automatically (ideas,
                 evidence pack, intent, brief, draft, editor review, QA) but
                 every ACCEPTANCE stays human: commissioning, idea choice,
                 brief acceptance, review acceptance, media satisfaction,
                 final approval, scheduling. The operator sees each output
                 and judges it before the next stage.
    AUTONOMOUS — acceptances are made by the autopilot on behalf of the
                 named operator who switched the mode on, with bounded
                 deterministic rules, EXCEPT the ADR 0004 gate: final
                 publication approval remains a named human decision.
                 After approval the autopilot assembles, schedules and
                 publishes.
    """

    OFF = "off"
    SUPERVISED = "supervised"
    AUTONOMOUS = "autonomous"


class AutopilotEventKind(StrEnum):
    """Append-only trail of what the autopilot did or why it waited."""

    MODE_CHANGED = "mode_changed"
    ACTION = "action"
    WAITING = "waiting"
    SKIPPED = "skipped"
    ERROR = "error"
