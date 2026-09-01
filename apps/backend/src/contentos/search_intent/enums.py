"""Search-intent vocabulary. Values are persistence contracts; never rename."""

from enum import StrEnum


class CannibalizationStatus(StrEnum):
    """Durable recorded truth-state — never a prompt hint (design §8.1).

    Until a Konsepthane published-inventory read contract exists,
    KNOWN_CONFLICT is accepted FUTURE vocabulary only: the current service
    refuses to record it because no supported inventory basis exists, and
    NO_KNOWN_CONFLICT / POTENTIAL_CONFLICT are always scoped explicitly to
    ContentOS-internal data in `cannibalization_basis`.
    """

    NOT_CHECKED = "not_checked"
    NO_KNOWN_CONFLICT = "no_known_conflict"
    POTENTIAL_CONFLICT = "potential_conflict"
    KNOWN_CONFLICT = "known_conflict"
