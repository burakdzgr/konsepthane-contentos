"""Shared persistence column helpers for ContentOS models."""

from enum import StrEnum

from sqlalchemy import JSON, Enum
from sqlalchemy.dialects.postgresql import JSONB

# JSONB on PostgreSQL; plain JSON elsewhere so unit tests can run on SQLite.
JSON_DICT = JSON().with_variant(JSONB(), "postgresql")
JSON_LIST = JSON().with_variant(JSONB(), "postgresql")


def string_enum(enum_cls: type[StrEnum], constraint_name: str, length: int) -> Enum:
    """VARCHAR-backed enum persisting member VALUES with a named CHECK constraint."""
    return Enum(
        enum_cls,
        name=constraint_name,
        native_enum=False,
        create_constraint=True,
        length=length,
        values_callable=lambda cls: [member.value for member in cls],
        validate_strings=True,
    )
