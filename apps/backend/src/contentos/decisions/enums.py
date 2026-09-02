"""Decision vocabularies. Values are persistence contracts; never rename."""

from enum import StrEnum


class DecisionKind(StrEnum):
    """One human decision event. There is no 'pending' — a decision row
    EXISTS or it does not — and no machine may author any of these."""

    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    REJECTED = "rejected"
    APPROVAL_REVOKED = "approval_revoked"
