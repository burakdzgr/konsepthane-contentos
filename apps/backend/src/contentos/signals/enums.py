"""Search-signal vocabulary. Values are persistence contracts; never rename."""

from enum import StrEnum


class SearchSignalType(StrEnum):
    """WHAT was observed — never which provider produced it."""

    SEARCH_VOLUME = "search_volume"
    TREND = "trend"
    SERP_OBSERVATION = "serp_observation"
    QUERY_SET = "query_set"
    MANUAL_INTENT_NOTE = "manual_intent_note"


# Provider is persisted as a bounded governed STRING vocabulary, not a
# database enum: future governed connectors (added deliberately, each with
# its own explicit admission path) must not require migration churn, and
# vendor SDK concepts never enter the domain. Today exactly one provider is
# operational: a human operator recorded the observation — which never means
# "verified by Google" or "came from Semrush".
MANUAL_OPERATOR_PROVIDER = "manual_operator"
