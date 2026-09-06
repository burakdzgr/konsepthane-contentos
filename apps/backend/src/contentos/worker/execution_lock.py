"""Per-entity execution locks for provider-calling worker tasks.

The same editorial task can be queued twice for one entity: the previous
stage chains it after commit, and the autopilot enqueues it on its own
sweep. Both executions then call the subcontractor gateway at once, one
gets the gateway's concurrency 429, and the two write attempt rows with
colliding retry numbers — the losing execution discards a real result.

A lock is one Redis key per (task, entity) held for the execution and
bounded by a TTL that outlives the provider timeout, so a crashed worker
never pins an entity forever. The duplicate does not wait: it reports
`duplicate_in_flight` and exits, because the running execution (or the
autopilot's next sweep) already owns the outcome. Eager/test settings use
an in-memory lock with the same semantics.
"""

import secrets
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

from redis import Redis

# Compare-and-delete: only the holder's token may release the key.
_RELEASE_SCRIPT = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) "
    "else return 0 end"
)


class ExecutionLock(Protocol):
    def acquire(self, key: str, ttl_seconds: int) -> str | None:
        """Return a release token when the lock was taken, else None."""
        ...

    def release(self, key: str, token: str) -> None: ...


class InMemoryExecutionLock:
    """Process-local lock with TTL expiry; eager Celery and tests."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._entries: dict[str, tuple[str, float]] = {}
        self._clock = clock
        self._guard = threading.Lock()

    def acquire(self, key: str, ttl_seconds: int) -> str | None:
        now = self._clock()
        with self._guard:
            held = self._entries.get(key)
            if held is not None and held[1] > now:
                return None
            token = secrets.token_hex(8)
            self._entries[key] = (token, now + ttl_seconds)
            return token

    def release(self, key: str, token: str) -> None:
        with self._guard:
            held = self._entries.get(key)
            if held is not None and held[0] == token:
                del self._entries[key]


class RedisExecutionLock:
    """SET NX EX lock shared by every worker process."""

    def __init__(self, client_factory: Callable[[], Redis]) -> None:
        self._client_factory = client_factory
        self._client: Redis | None = None

    def _connection(self) -> Any:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    def acquire(self, key: str, ttl_seconds: int) -> str | None:
        token = secrets.token_hex(8)
        taken = self._connection().set(key, token, nx=True, ex=max(1, int(ttl_seconds)))
        return token if taken else None

    def release(self, key: str, token: str) -> None:
        self._connection().eval(_RELEASE_SCRIPT, 1, key, token)


def execution_lock_key(task_name: str, *parts: str) -> str:
    return "contentos:execution:" + task_name + ":" + ":".join(parts)
