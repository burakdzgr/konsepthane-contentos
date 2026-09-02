"""Publication persistence models (immutable packages + attempt facts).

`publication_packages` rows are IMMUTABLE: one row is the exact hashed
projection of the approved artifacts at assembly time, pinned to the
approval decision, draft, brief, and QA report. Identical content
converges by the per-work-item UNIQUE `package_hash`; changed content
gets a new version. Packages are addressed by id — there is no "current
package" state to mutate.

`publication_attempts` are append-only EXECUTION facts with a bounded
non-editorial vocabulary; a successful attempt (and only a successful
one) carries the remote publication reference.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

# Registered so every FK target resolves wherever these models are used
# (acyclic: none of these import contentos.publishing).
from contentos.auth import models as _auth_models  # noqa: F401
from contentos.briefs import models as _brief_models  # noqa: F401
from contentos.db.base import Base
from contentos.db.types import JSON_DICT
from contentos.decisions import models as _decision_models  # noqa: F401
from contentos.drafts import models as _draft_models  # noqa: F401
from contentos.qa import models as _qa_models  # noqa: F401


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PublicationPackage(Base):
    __tablename__ = "publication_packages"
    __table_args__ = (
        UniqueConstraint("work_item_id", "version", name="uq_publication_packages_version"),
        UniqueConstraint("work_item_id", "package_hash", name="uq_publication_packages_content"),
        CheckConstraint("version > 0", name="ck_publication_packages_version_positive"),
        CheckConstraint(
            "length(content_hash) = 64 AND content_hash = lower(content_hash)",
            name="ck_publication_packages_content_hash_format",
        ),
        CheckConstraint(
            "length(package_hash) = 64 AND package_hash = lower(package_hash)",
            name="ck_publication_packages_package_hash_format",
        ),
        CheckConstraint(
            "length(trim(payload_schema_version)) > 0",
            name="ck_publication_packages_schema_version_nonempty",
        ),
        CheckConstraint(
            "request_id IS NULL OR length(trim(request_id)) > 0",
            name="ck_publication_packages_request_id_nonempty",
        ),
        Index("ix_publication_packages_work_item", "work_item_id", "version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    work_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("editorial_work_items.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer(), nullable=False)
    human_decision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("human_decisions.id", ondelete="RESTRICT"), nullable=False
    )
    content_draft_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("content_drafts.id", ondelete="RESTRICT"), nullable=False
    )
    content_brief_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("content_briefs.id", ondelete="RESTRICT"), nullable=False
    )
    qa_report_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("qa_reports.id", ondelete="RESTRICT"), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(length=64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False)
    payload_schema_version: Mapped[str] = mapped_column(String(length=50), nullable=False)
    package_hash: Mapped[str] = mapped_column(String(length=64), nullable=False)
    media_manifest: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    assembled_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    request_id: Mapped[str | None] = mapped_column(String(length=128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )


class PublicationAttempt(Base):
    """One publication dispatch execution fact (append-only)."""

    __tablename__ = "publication_attempts"
    __table_args__ = (
        UniqueConstraint(
            "publication_package_id", "attempt_number", name="uq_publication_attempts_number"
        ),
        CheckConstraint("attempt_number > 0", name="ck_publication_attempts_number_positive"),
        CheckConstraint(
            "status IN ('succeeded', 'transport_error', 'rejected_by_api', 'timeout')",
            name="ck_publication_attempts_status",
        ),
        # The remote reference exists exactly when the dispatch succeeded.
        CheckConstraint(
            "(status = 'succeeded') = (remote_publication_ref IS NOT NULL)",
            name="ck_publication_attempts_remote_ref",
        ),
        CheckConstraint(
            "length(trim(idempotency_key)) > 0",
            name="ck_publication_attempts_idempotency_nonempty",
        ),
        CheckConstraint(
            "length(trim(transport_name)) > 0",
            name="ck_publication_attempts_transport_nonempty",
        ),
        CheckConstraint(
            "request_id IS NULL OR length(trim(request_id)) > 0",
            name="ck_publication_attempts_request_id_nonempty",
        ),
        Index("ix_publication_attempts_package", "publication_package_id", "attempt_number"),
        Index("ix_publication_attempts_idempotency", "idempotency_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    publication_package_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("publication_packages.id", ondelete="RESTRICT"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer(), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(length=128), nullable=False)
    status: Mapped[str] = mapped_column(String(length=32), nullable=False)
    error_class: Mapped[str | None] = mapped_column(String(length=100), nullable=True)
    remote_publication_ref: Mapped[str | None] = mapped_column(Text(), nullable=True)
    transport_name: Mapped[str] = mapped_column(String(length=100), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(length=128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
