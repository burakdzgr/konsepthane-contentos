from enum import StrEnum


class InspirationBand(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class SearchOpportunityBand(StrEnum):
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    UNKNOWN = "unknown"


class OpportunityRecommendation(StrEnum):
    PRODUCE = "produce"
    CONTINUE_RESEARCH = "continue_research"
    ELIMINATE = "eliminate"
    HUMAN_REVIEW = "human_review"


class TrendState(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"


class SignalExtractionMethod(StrEnum):
    DETERMINISTIC = "deterministic"
    MODEL_ASSISTED = "model_assisted"
    OPERATOR = "operator"


class IntelligenceBand(StrEnum):
    """One operator-facing strength vocabulary for every intelligence section.

    Family bands (strong/moderate/weak), factor values (1..5) and provider
    potentials all fold into this scale for display; UNKNOWN stays a value.
    """

    VERY_HIGH = "very_high"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"
