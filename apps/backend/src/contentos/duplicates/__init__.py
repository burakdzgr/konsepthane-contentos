"""Deterministic duplicate decisions over local normalized documents."""

from contentos.duplicates.engine import (
    DUPLICATE_ENGINE_NAME,
    DUPLICATE_ENGINE_VERSION,
    DuplicateEngineV1,
)
from contentos.duplicates.enums import DuplicateDecisionOutcome
from contentos.duplicates.service import DuplicateDecisionService

__all__ = [
    "DUPLICATE_ENGINE_NAME",
    "DUPLICATE_ENGINE_VERSION",
    "DuplicateDecisionOutcome",
    "DuplicateDecisionService",
    "DuplicateEngineV1",
]
