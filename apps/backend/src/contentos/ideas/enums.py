"""Idea vocabulary. Values are persistence contracts; never rename."""

from enum import StrEnum


class ContentType(StrEnum):
    """The accepted controlled initial content-type vocabulary (design §13.1).

    An idea-level editorial choice: never inferred from a single source
    article, never free text. Extension is a migration-time vocabulary
    addition.
    """

    GUIDE = "guide"
    IDEA_LIST = "idea_list"
    CHECKLIST = "checklist"
    PLANNING_GUIDE = "planning_guide"
    COMPARISON = "comparison"
    FAQ = "faq"
    HOW_TO = "how_to"
    INSPIRATION = "inspiration"


class IdeaOrigin(StrEnum):
    """Who authored this idea version.

    MODEL_ASSISTED is persistence vocabulary only for now: the runtime
    IdeaService still creates operator-authored ideas exclusively, and the
    database requires a real generation-attempt reference for any
    model-assisted row (and forbids one on operator rows), so fake model
    provenance stays impossible. The first model-assisted generation path
    arrives with the idea-generation-engine task.
    """

    OPERATOR = "operator"
    MODEL_ASSISTED = "model_assisted"


class OriginalityStatus(StrEnum):
    """Aggregate deterministic originality result for one idea version.

    NOT_CHECKABLE is a first-class state: "could not evaluate" is never
    silently promoted to a pass.
    """

    PASSED = "passed"
    FAILED = "failed"
    NOT_CHECKABLE = "not_checkable"


class IdeaSelectionAction(StrEnum):
    """Selection is an operator editorial decision — NEVER publication
    approval (ADR 0004 untouched)."""

    SELECTED = "selected"
    DESELECTED = "deselected"


class IdeaSelectionActor(StrEnum):
    """Who performed a selection action (operator only in Phase 3)."""

    OPERATOR = "operator"
