"""Performance-loop vocabulary. Values are persistence contracts; never rename."""

from enum import StrEnum


class PerformanceProvider(StrEnum):
    """Which external provider an observation came from."""

    GOOGLE_SEARCH_CONSOLE = "google_search_console"
    GOOGLE_ANALYTICS = "google_analytics"
    SEMRUSH = "semrush"
    GOOGLE_TRENDS = "google_trends"
    PINTEREST_TRENDS = "pinterest_trends"


class AssessmentStatus(StrEnum):
    """Honest classification of one published content over one window."""

    INSUFFICIENT_DATA = "insufficient_data"
    RISING = "rising"
    STABLE = "stable"
    DECLINING = "declining"
    VOLATILE = "volatile"
    UNKNOWN = "unknown"


class RefreshStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    DISMISSED = "dismissed"
    SUPERSEDED = "superseded"


class SuggestionKind(StrEnum):
    CLUSTER_FOCUS = "cluster_focus"
    KEYWORD_ADD = "keyword_add"
    AUDIENCE_FOCUS = "audience_focus"
    THEME_FOCUS = "theme_focus"


class SuggestionStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    IGNORED = "ignored"


class HistoricalOutcome(StrEnum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class HistoricalBand(StrEnum):
    """Strength of the historical signal; UNKNOWN is a value, never zero."""

    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    UNKNOWN = "unknown"


ASSESSMENT_WINDOWS: tuple[int, ...] = (7, 28, 90)
