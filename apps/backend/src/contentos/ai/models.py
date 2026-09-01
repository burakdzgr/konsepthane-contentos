"""AI generation-attempt persistence (provenance/metadata ONLY).

One generic append-only table for every generation purpose (accepted
design §6.3): per-engine RESULT artifacts live in their own tables and
reference attempts — never the reverse, so this boundary stays reusable.

Deliberately absent, forever: raw_response, raw_output, completion_text,
provider_payload, prompt, messages, HTML, api keys. This table answers
"which provider/model, under which exact schema/template contract, from
which exact inputs, when, at what usage, did validation pass, which retry"
— it is not a provider-payload archive. AI output is never ResearchEvidence
and never a provenance root (ADR 0007).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from contentos.ai.enums import GenerationPurpose, GenerationStatus
from contentos.db.base import Base
from contentos.db.types import JSON_DICT, string_enum


class AiGenerationAttempt(Base):
    """One immutable completed attempt outcome (no PENDING/RUNNING states).

    `attempt_identity_hash` is the NULL-safe DB-backed exact identity of one
    provider invocation (canonical JSON SHA-256 over purpose, input hash,
    provider/model identity with an unavailable model_version explicitly as
    null, schema/template identity, retry number) — a nullable-column UNIQUE
    tuple could not give exact idempotency, so the hash column is UNIQUE
    instead.
    """

    __tablename__ = "ai_generation_attempts"
    __table_args__ = (
        UniqueConstraint("attempt_identity_hash", name="uq_ai_generation_attempts_identity"),
        CheckConstraint(
            "length(trim(provider)) > 0", name="ck_ai_generation_attempts_provider_nonempty"
        ),
        CheckConstraint(
            "length(trim(model_name)) > 0",
            name="ck_ai_generation_attempts_model_name_nonempty",
        ),
        CheckConstraint(
            "model_version IS NULL OR length(trim(model_version)) > 0",
            name="ck_ai_generation_attempts_model_version_nonempty",
        ),
        CheckConstraint(
            "length(trim(schema_name)) > 0",
            name="ck_ai_generation_attempts_schema_name_nonempty",
        ),
        CheckConstraint(
            "length(trim(schema_version)) > 0",
            name="ck_ai_generation_attempts_schema_version_nonempty",
        ),
        CheckConstraint(
            "length(trim(template_name)) > 0",
            name="ck_ai_generation_attempts_template_name_nonempty",
        ),
        CheckConstraint(
            "length(trim(template_version)) > 0",
            name="ck_ai_generation_attempts_template_version_nonempty",
        ),
        CheckConstraint(
            "length(input_hash) = 64 AND input_hash = lower(input_hash)",
            name="ck_ai_generation_attempts_input_hash_format",
        ),
        CheckConstraint(
            "length(attempt_identity_hash) = 64 AND "
            "attempt_identity_hash = lower(attempt_identity_hash)",
            name="ck_ai_generation_attempts_identity_hash_format",
        ),
        CheckConstraint("retry_number >= 0", name="ck_ai_generation_attempts_retry_range"),
        CheckConstraint(
            "(status = 'succeeded' AND error_class IS NULL) OR "
            "(status != 'succeeded' AND error_class IS NOT NULL "
            "AND length(trim(error_class)) > 0)",
            name="ck_ai_generation_attempts_error_consistency",
        ),
        Index("ix_ai_generation_attempts_purpose", "purpose", "created_at"),
        Index("ix_ai_generation_attempts_input_hash", "input_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    purpose: Mapped[GenerationPurpose] = mapped_column(
        string_enum(GenerationPurpose, "ck_ai_generation_attempts_purpose", 24),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    schema_name: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(50), nullable=False)
    template_name: Mapped[str] = mapped_column(String(100), nullable=False)
    template_version: Mapped[str] = mapped_column(String(50), nullable=False)
    input_refs: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_identity_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[GenerationStatus] = mapped_column(
        string_enum(GenerationStatus, "ck_ai_generation_attempts_status", 24),
        nullable=False,
    )
    error_class: Mapped[str | None] = mapped_column(String(100), nullable=True)
    retry_number: Mapped[int] = mapped_column(Integer(), nullable=False)
    usage: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
