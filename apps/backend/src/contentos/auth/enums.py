"""Auth vocabularies. Values are persistence contracts; never rename."""

from enum import StrEnum


class UserRole(StrEnum):
    """The frozen role vocabulary (PHASE5_GOVERNANCE_ARCHITECTURE.md §1):
    operators drive the pipeline; reviewers may additionally decide at
    AWAITING_HUMAN_REVIEW. A user can hold both."""

    OPERATOR = "operator"
    REVIEWER = "reviewer"


class UserEventAction(StrEnum):
    """Audited user-management actions (append-only)."""

    PROVISIONED = "provisioned"
    PASSWORD_ROTATED = "password_rotated"
    ROLES_CHANGED = "roles_changed"
    DEACTIVATED = "deactivated"
    REACTIVATED = "reactivated"
