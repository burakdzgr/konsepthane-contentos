"""Media vocabulary. Values are persistence contracts; never rename."""

from enum import StrEnum


class MediaOrigin(StrEnum):
    """WHERE an asset came from — a named human upload or an audited
    generation attempt. Nothing else exists."""

    HUMAN_UPLOAD = "human_upload"
    AI_GENERATED = "ai_generated"


class SatisfactionStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
