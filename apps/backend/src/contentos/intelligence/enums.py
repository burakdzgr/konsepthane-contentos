"""Intelligence signal enums. Values are persistence contracts; never rename."""

from enum import StrEnum


class SignalFamily(StrEnum):
    """Which kind of clue a signal is. Stored as a string with a CHECK."""

    INSPIRATION = "inspiration"
    COMMUNITY_NEED = "community_need"
    MARKET = "market"
    COMPETITION = "competition"
    TAXONOMY = "taxonomy"
    SEARCH = "search"
    TREND = "trend"
    VISUAL_TREND = "visual_trend"
    HISTORICAL_PERFORMANCE = "historical_performance"


class Band(StrEnum):
    """Honest strength band per family. UNKNOWN is a value, never zero."""

    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    UNKNOWN = "unknown"
