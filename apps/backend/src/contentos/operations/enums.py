"""Operational control vocabularies. Values are persistence contracts."""

from enum import StrEnum


class PauseScope(StrEnum):
    """WHAT a pause gates. ``ENGINE`` gates every dispatch; the other
    scopes gate exactly one family of explicitly triggered jobs. A pause
    is an INTAKE control: already-running atomic work always finishes —
    nothing here cancels a task or touches workflow state."""

    ENGINE = "engine"
    RESEARCH = "research"
    OPPORTUNITY = "opportunity"
    IDEAS = "ideas"
    EVIDENCE = "evidence"
    INTENT = "intent"
    BRIEF = "brief"
    WRITER = "writer"
    EDITOR = "editor"
    QA = "qa"
    MEDIA = "media"
    PUBLISHER = "publisher"


class PauseAction(StrEnum):
    """Audited pause-control actions (append-only)."""

    PAUSED = "paused"
    RESUMED = "resumed"
