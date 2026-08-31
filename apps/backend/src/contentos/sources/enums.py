"""Source Registry enums. Values are persistence contracts; never rename."""

from enum import StrEnum


class SourceKind(StrEnum):
    """What kind of origin a source is.

    Provider kinds are registry placeholders per the Phase 2 design;
    registering one does not make an integration exist.
    """

    EDITORIAL_SITE = "editorial_site"
    COMPETITOR_SITE = "competitor_site"
    RSS_FEED = "rss_feed"
    SITEMAP = "sitemap"
    MANUAL = "manual"
    TREND_PROVIDER = "trend_provider"
    SEARCH_PROVIDER = "search_provider"


class SourceLifecycleState(StrEnum):
    """Audited source lifecycle. BLOCKED is a policy prohibition, not a pause."""

    ACTIVE = "active"
    PAUSED = "paused"
    DISABLED = "disabled"
    BLOCKED = "blocked"


class TrustTier(StrEnum):
    """Evidence-weighting classification; never grants republication rights."""

    OFFICIAL = "official"
    EXPERT = "expert"
    REPUTABLE = "reputable"
    GENERAL = "general"
    REFERENCE_ONLY = "reference_only"


class DiscoveryStrategy(StrEnum):
    """How candidates are found for a source.

    PROVIDER is declared for future provider kinds; it is not implemented.
    """

    FEED = "feed"
    SITEMAP = "sitemap"
    MANUAL = "manual"
    PROVIDER = "provider"


class RobotsPolicy(StrEnum):
    """Robots posture. OBEY is the only permitted Phase 2 value."""

    OBEY = "obey"


class LifecycleChangeOrigin(StrEnum):
    """Who initiated a lifecycle transition in a single-operator system."""

    OPERATOR = "operator"
    SYSTEM = "system"
