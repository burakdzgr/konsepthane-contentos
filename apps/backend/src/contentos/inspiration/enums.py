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
