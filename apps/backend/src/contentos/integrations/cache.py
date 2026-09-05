"""Provider response cache with TTL (cost control only — never "truth").

Keys are sha256 digests of the canonical request identity; the API key is
never part of the identity, so a key rotation reuses the cache and the key
never appears in the database.
"""

import hashlib
import json
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import select

from contentos.integrations.models import ProviderCacheEntry
from contentos.integrations.sessions import SessionScope

JsonPayload = dict[str, Any]


def cache_key(*parts: object) -> str:
    canonical = json.dumps(
        [
            str(part) if not isinstance(part, (int, float, bool, list, dict)) else part
            for part in parts
        ],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ResponseCache(Protocol):
    def get(self, provider: str, key: str, *, now: datetime) -> JsonPayload | None: ...

    def put(
        self,
        provider: str,
        key: str,
        payload: JsonPayload,
        *,
        fetched_at: datetime,
        expires_at: datetime,
    ) -> None: ...


class MemoryResponseCache:
    """Process-local cache for tests and session-less construction."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], tuple[JsonPayload, datetime]] = {}

    def get(self, provider: str, key: str, *, now: datetime) -> JsonPayload | None:
        entry = self._entries.get((provider, key))
        if entry is None:
            return None
        payload, expires_at = entry
        if expires_at <= now:
            self._entries.pop((provider, key), None)
            return None
        return payload

    def put(
        self,
        provider: str,
        key: str,
        payload: JsonPayload,
        *,
        fetched_at: datetime,
        expires_at: datetime,
    ) -> None:
        self._entries[(provider, key)] = (payload, expires_at)


class DatabaseResponseCache:
    """Durable cache in `provider_cache` (shared by API and worker processes)."""

    def __init__(self, scope: SessionScope) -> None:
        self._scope = scope

    def get(self, provider: str, key: str, *, now: datetime) -> JsonPayload | None:
        with self._scope() as session:
            entry = session.execute(
                select(ProviderCacheEntry).where(
                    ProviderCacheEntry.provider == provider,
                    ProviderCacheEntry.cache_key == key,
                )
            ).scalar_one_or_none()
            if entry is None:
                return None
            expires_at = entry.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=now.tzinfo)
            if expires_at <= now:
                return None
            return dict(entry.payload)

    def put(
        self,
        provider: str,
        key: str,
        payload: JsonPayload,
        *,
        fetched_at: datetime,
        expires_at: datetime,
    ) -> None:
        with self._scope() as session:
            entry = session.execute(
                select(ProviderCacheEntry).where(
                    ProviderCacheEntry.provider == provider,
                    ProviderCacheEntry.cache_key == key,
                )
            ).scalar_one_or_none()
            if entry is None:
                session.add(
                    ProviderCacheEntry(
                        provider=provider,
                        cache_key=key,
                        payload=payload,
                        fetched_at=fetched_at,
                        expires_at=expires_at,
                    )
                )
            else:
                entry.payload = payload
                entry.fetched_at = fetched_at
                entry.expires_at = expires_at
            session.flush()
