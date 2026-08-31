"""Stable normalization persistence enums."""

from enum import StrEnum


class NormalizationStatus(StrEnum):
    """Whether extraction produced a usable normalized document."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


class NormalizationFailureCode(StrEnum):
    """Broad durable categories independent of any parser library."""

    UNSUPPORTED_CONTENT = "unsupported_content"
    DECODE_ERROR = "decode_error"
    PARSE_ERROR = "parse_error"
    EMPTY_CONTENT = "empty_content"
    EXTRACTOR_ERROR = "extractor_error"
    POLICY_REJECTED = "policy_rejected"
