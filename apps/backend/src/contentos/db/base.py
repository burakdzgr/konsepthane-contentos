"""Declarative base for ContentOS-owned database models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base all future ContentOS models must inherit from."""
