"""Per-provider daily request budget + the cost-controlled call wrapper.

`BudgetedClient.cached(...)` is the single path every provider read goes
through: cache lookup → daily budget check → the real call → cache store.
Identical concurrent requests in one process are deduplicated behind a
per-key lock so only one of them reaches the vendor.
"""

import threading
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Protocol, TypeVar

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from contentos.integrations.base import ProviderError, sanitize_error_class
from contentos.integrations.cache import JsonPayload, ResponseCache, cache_key
from contentos.integrations.enums import ProviderName, ProviderState
from contentos.integrations.http import Clock, utc_now
from contentos.integrations.models import ProviderRequestLog
from contentos.integrations.sessions import SessionScope

T = TypeVar("T")


class RequestBudget(Protocol):
    def consume(self, provider: str, *, day: date, limit: int) -> int:
        """Count one request; raise `ProviderError(rate_limited)` when the
        day's budget is already spent. Returns the count after consuming."""
        ...

    def requests_today(self, provider: str, *, day: date) -> int: ...


def budget_exhausted(provider: str, limit: int) -> ProviderError:
    return ProviderError(
        f"{provider}: daily budget of {limit} requests exhausted",
        kind=ProviderState.RATE_LIMITED,
        error_class=sanitize_error_class(provider, "daily_budget"),
    )


class MemoryRequestBudget:
    def __init__(self) -> None:
        self._counts: dict[tuple[str, date], int] = {}
        self._lock = threading.Lock()

    def consume(self, provider: str, *, day: date, limit: int) -> int:
        with self._lock:
            current = self._counts.get((provider, day), 0)
            if current >= limit:
                raise budget_exhausted(provider, limit)
            self._counts[(provider, day)] = current + 1
            return current + 1

    def requests_today(self, provider: str, *, day: date) -> int:
        return self._counts.get((provider, day), 0)


class DatabaseRequestBudget:
    """Durable per-day counters in `provider_request_log` (UNIQUE provider+day)."""

    def __init__(self, scope: SessionScope) -> None:
        self._scope = scope

    def consume(self, provider: str, *, day: date, limit: int) -> int:
        with self._scope() as session:
            # Atomic bounded increment: only succeeds while under the limit.
            result = session.execute(
                update(ProviderRequestLog)
                .where(
                    ProviderRequestLog.provider == provider,
                    ProviderRequestLog.day == day,
                    ProviderRequestLog.request_count < limit,
                )
                .values(request_count=ProviderRequestLog.request_count + 1)
            )
            if _rowcount(result) == 1:
                session.flush()
                return self._count(session, provider, day)
            existing = self._count(session, provider, day, missing=-1)
            if existing >= 0:
                raise budget_exhausted(provider, limit)
            try:
                with session.begin_nested():
                    session.add(ProviderRequestLog(provider=provider, day=day, request_count=1))
            except IntegrityError:
                # Lost the insert race: retry the bounded increment once.
                retry = session.execute(
                    update(ProviderRequestLog)
                    .where(
                        ProviderRequestLog.provider == provider,
                        ProviderRequestLog.day == day,
                        ProviderRequestLog.request_count < limit,
                    )
                    .values(request_count=ProviderRequestLog.request_count + 1)
                )
                if _rowcount(retry) != 1:
                    raise budget_exhausted(provider, limit) from None
            session.flush()
            return self._count(session, provider, day)

    def requests_today(self, provider: str, *, day: date) -> int:
        with self._scope() as session:
            return self._count(session, provider, day)

    @staticmethod
    def _count(session: Session, provider: str, day: date, missing: int = 0) -> int:
        value = session.execute(
            select(ProviderRequestLog.request_count).where(
                ProviderRequestLog.provider == provider,
                ProviderRequestLog.day == day,
            )
        ).scalar_one_or_none()
        return missing if value is None else int(value)


def _rowcount(result: object) -> int:
    value = getattr(result, "rowcount", 0)
    return int(value) if isinstance(value, int) else 0


class BudgetedClient:
    """Cache + budget + dedupe around a provider's vendor calls."""

    def __init__(
        self,
        provider: ProviderName,
        *,
        daily_budget: int,
        cache_ttl: timedelta,
        cache: ResponseCache,
        budget: RequestBudget,
        clock: Clock | None = None,
    ) -> None:
        self.provider = provider
        self.daily_budget = daily_budget
        self.cache_ttl = cache_ttl
        self._cache = cache
        self._budget = budget
        self._clock: Clock = clock if clock is not None else utc_now
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def now(self) -> datetime:
        return self._clock()

    def requests_today(self) -> int:
        return self._budget.requests_today(self.provider.value, day=self._clock().date())

    def cached(self, parts: tuple[object, ...], fetch: Callable[[], JsonPayload]) -> JsonPayload:
        """Return the cached payload for `parts` or fetch, count and store it."""
        key = cache_key(self.provider.value, *parts)
        with self._key_lock(key):
            now = self._clock()
            hit = self._cache.get(self.provider.value, key, now=now)
            if hit is not None:
                return hit
            payload = self.uncached(fetch)
            fetched_at = self._clock()
            self._cache.put(
                self.provider.value,
                key,
                payload,
                fetched_at=fetched_at,
                expires_at=fetched_at + self.cache_ttl,
            )
            return payload

    def uncached(self, fetch: Callable[[], T]) -> T:
        """Count one request against today's budget, then perform it."""
        self._budget.consume(self.provider.value, day=self._clock().date(), limit=self.daily_budget)
        return fetch()

    def _key_lock(self, key: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
                if len(self._locks) > 1024:
                    # Bounded: drop everything except the newest entry.
                    self._locks = {key: lock}
            return lock
