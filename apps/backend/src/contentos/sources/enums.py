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


class SourceRole(StrEnum):
    """Editorial PURPOSE of a source (why we read it), orthogonal to SourceKind.

    ``SourceKind`` stays technical (how content is acquired); the role says
    what the editorial pipeline expects from the source. A source is never
    locked into one role: ``capabilities`` widen it.
    """

    INSPIRATION = "inspiration"
    TURKISH_EDITORIAL = "turkish_editorial"
    COMMUNITY_INTENT = "community_intent"
    COMPETITOR = "competitor"
    TAXONOMY = "taxonomy"
    TREND = "trend"
    SEARCH = "search"


class SourceCapability(StrEnum):
    """Signal families a source MAY yield. Persisted as a JSON list of values."""

    INSPIRATION = "inspiration"
    COMMUNITY_NEED = "community_need"
    MARKET = "market"
    COMPETITION = "competition"
    TAXONOMY = "taxonomy"
    SEARCH = "search"
    TREND = "trend"
    VISUAL_TREND = "visual_trend"


_DEFAULT_CAPABILITIES: dict[SourceRole, tuple[SourceCapability, ...]] = {
    SourceRole.INSPIRATION: (SourceCapability.INSPIRATION,),
    SourceRole.TURKISH_EDITORIAL: (
        SourceCapability.INSPIRATION,
        SourceCapability.MARKET,
        SourceCapability.COMPETITION,
        SourceCapability.TAXONOMY,
    ),
    SourceRole.COMMUNITY_INTENT: (SourceCapability.COMMUNITY_NEED,),
    SourceRole.COMPETITOR: (SourceCapability.COMPETITION, SourceCapability.MARKET),
    SourceRole.TAXONOMY: (SourceCapability.TAXONOMY, SourceCapability.MARKET),
    SourceRole.TREND: (SourceCapability.TREND, SourceCapability.VISUAL_TREND),
    SourceRole.SEARCH: (SourceCapability.SEARCH,),
}


def default_capabilities_for(role: SourceRole) -> tuple[SourceCapability, ...]:
    """The capability set a role implies when the operator states none."""
    return _DEFAULT_CAPABILITIES[role]
