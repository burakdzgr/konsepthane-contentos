"""Narrow append/read-only attempt persistence access. Callers own commit.

Attempts are execution HISTORY: there is deliberately no update, no delete,
and no "latest AI truth" accessor — engines consult their own artifact
tables for domain state.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.ai.enums import GenerationPurpose
from contentos.ai.models import AiGenerationAttempt


class AiGenerationAttemptRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, attempt: AiGenerationAttempt) -> AiGenerationAttempt:
        self._session.add(attempt)
        self._session.flush()
        return attempt

    def get_by_id(self, attempt_id: uuid.UUID) -> AiGenerationAttempt | None:
        return self._session.get(AiGenerationAttempt, attempt_id)

    def get_by_identity_hash(self, attempt_identity_hash: str) -> AiGenerationAttempt | None:
        statement = select(AiGenerationAttempt).where(
            AiGenerationAttempt.attempt_identity_hash == attempt_identity_hash
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_by_purpose(self, purpose: GenerationPurpose) -> list[AiGenerationAttempt]:
        statement = (
            select(AiGenerationAttempt)
            .where(AiGenerationAttempt.purpose == purpose)
            .order_by(AiGenerationAttempt.created_at, AiGenerationAttempt.id)
        )
        return list(self._session.execute(statement).scalars())

    def list_by_input_hash(self, input_hash: str) -> list[AiGenerationAttempt]:
        statement = (
            select(AiGenerationAttempt)
            .where(AiGenerationAttempt.input_hash == input_hash)
            .order_by(AiGenerationAttempt.created_at, AiGenerationAttempt.id)
        )
        return list(self._session.execute(statement).scalars())
