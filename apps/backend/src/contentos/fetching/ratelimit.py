"""Per-host politeness: bounded concurrency plus a minimum request interval.

PROCESS-LOCAL ONLY: this protects politeness within one process. Distributed
enforcement across workers arrives with Celery orchestration in a later task.
"""

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager


class HostRateLimiter:
    """Concurrency-safe per-host serialization with injectable clock/sleeper."""

    def __init__(
        self,
        *,
        min_interval_seconds: float,
        max_concurrency: int = 1,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._min_interval = min_interval_seconds
        self._max_concurrency = max_concurrency
        self._clock = clock
        self._sleeper = sleeper
        self._guard = threading.Lock()
        self._semaphores: dict[str, threading.BoundedSemaphore] = {}
        self._last_request_at: dict[str, float] = {}

    def _semaphore_for(self, host: str) -> threading.BoundedSemaphore:
        with self._guard:
            if host not in self._semaphores:
                self._semaphores[host] = threading.BoundedSemaphore(self._max_concurrency)
            return self._semaphores[host]

    @contextmanager
    def acquire(self, host: str) -> Iterator[None]:
        """Hold a per-host slot, waiting out the minimum interval first."""
        semaphore = self._semaphore_for(host)
        semaphore.acquire()
        try:
            self._respect_interval(host)
            yield
        finally:
            semaphore.release()

    def _respect_interval(self, host: str) -> None:
        if self._min_interval > 0:
            with self._guard:
                last = self._last_request_at.get(host)
            if last is not None:
                wait = self._min_interval - (self._clock() - last)
                if wait > 0:
                    self._sleeper(wait)
        with self._guard:
            self._last_request_at[host] = self._clock()
