"""Discovery enums. Values are persistence contracts; never rename."""

from enum import StrEnum


class DiscoveryLifecycleState(StrEnum):
    """Admission lifecycle only; fetch progress projections, never editorial state."""

    DISCOVERED = "discovered"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FETCHED = "fetched"
    FETCH_FAILED = "fetch_failed"


class DiscoveryMethod(StrEnum):
    """How a candidate was found.

    Only MANUAL is implemented; the rest are persistence placeholders for the
    strategies planned by the Phase 2 design.
    """

    MANUAL = "manual"
    FEED = "feed"
    SITEMAP = "sitemap"
    PROVIDER = "provider"
    SEARCH = "search"


class DiscoveryRejectionReason(StrEnum):
    """Coded machine-readable rejection reasons from the Phase 2 design."""

    OUT_OF_SCOPE = "out_of_scope"
    DUPLICATE_URL = "duplicate_url"
    SOURCE_NOT_ACTIVE = "source_not_active"
    POLICY = "policy"
    INVALID_URL = "invalid_url"
    UNSUPPORTED_SCHEME = "unsupported_scheme"
