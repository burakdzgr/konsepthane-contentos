"""Small, stable strategy vocabulary."""

from enum import StrEnum


class StrategyStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"
