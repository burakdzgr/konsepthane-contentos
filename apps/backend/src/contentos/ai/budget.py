"""Deterministic daily provider-spend guard (production-readiness).

Bounded retries limit one job; this bounds the DAY: before any provider
invocation, the caller checks the count of durable
`ai_generation_attempts` rows created since UTC midnight against the
configured budget. Exceeding it is an EXECUTION condition — a typed
refusal that changes no workflow state and never becomes an editorial
decision. `None` disables the guard explicitly.
"""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from contentos.ai.errors import AiBoundaryError
from contentos.ai.models import AiGenerationAttempt


class BudgetExceededError(AiBoundaryError):
    """The daily attempt budget is exhausted; no provider was invoked."""


def attempts_today(session: Session) -> int:
    """Durable attempts created since UTC midnight."""
    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    bind = session.get_bind()
    since = (
        day_start.replace(tzinfo=None)
        if bind is not None and bind.dialect.name == "sqlite"
        else day_start
    )
    return int(
        session.scalar(
            select(func.count())
            .select_from(AiGenerationAttempt)
            .where(AiGenerationAttempt.created_at >= since)
        )
        or 0
    )


def ensure_daily_attempt_budget(session: Session, budget: int | None) -> None:
    """Raise typed when today's durable attempt count has reached the
    budget. Called BEFORE the provider — nothing is persisted here."""
    if budget is None:
        return
    used = attempts_today(session)
    if used >= budget:
        raise BudgetExceededError(
            f"the daily AI attempt budget is exhausted ({used}/{budget} "
            "attempts since UTC midnight); no provider was invoked"
        )
