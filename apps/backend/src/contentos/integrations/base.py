"""Provider contract: status value, typed errors, and the provider protocol.

A `ProviderStatus` never contains secrets, URLs with keys, or vendor
response bodies: `detail` is an operator-facing Turkish sentence and
`last_error_class` is a bounded machine class such as `semrush_http_401`.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from contentos.integrations.enums import ProviderName, ProviderState

MAX_ERROR_CLASS_LENGTH = 64
_ERROR_CLASS_UNSAFE = re.compile(r"[^a-z0-9_]+")


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    """The last observed health of one provider (secret-free by construction)."""

    name: ProviderName
    state: ProviderState
    detail: str
    checked_at: datetime
    last_success_at: datetime | None
    last_error_class: str | None


def sanitize_error_class(prefix: str, token: str) -> str:
    """`<prefix>_<token>` lower-cased, `[a-z0-9_]` only, bounded in length.

    Vendor error text never becomes a class verbatim: callers pass a short
    token (an HTTP status, a vendor error code, `timeout`), and anything
    else collapses to underscores.
    """
    raw = f"{prefix}_{token}".lower()
    cleaned = _ERROR_CLASS_UNSAFE.sub("_", raw).strip("_")
    cleaned = re.sub(r"_+", "_", cleaned)
    return cleaned[:MAX_ERROR_CLASS_LENGTH] or prefix[:MAX_ERROR_CLASS_LENGTH]


class ProviderError(Exception):
    """A provider call failed in a typed, bounded, secret-free way.

    `kind` is the honest state the failure implies; `error_class` is the
    bounded machine class persisted on the status row; `retry_after_seconds`
    carries a vendor `Retry-After` when one was given.
    """

    def __init__(
        self,
        message: str,
        *,
        kind: ProviderState,
        error_class: str,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.error_class = error_class[:MAX_ERROR_CLASS_LENGTH]
        self.retry_after_seconds = retry_after_seconds


class ProviderNotConfiguredError(ProviderError):
    """The provider has no credentials; nothing was attempted."""

    def __init__(self, name: ProviderName, message: str | None = None) -> None:
        super().__init__(
            message or f"{name.value} is not configured",
            kind=ProviderState.NOT_CONFIGURED,
            error_class=sanitize_error_class(name.value, "not_configured"),
        )


class IntegrationProvider(Protocol):
    """What every provider adapter exposes to the registry and the API."""

    name: ProviderName
    display_name: str

    def configured(self) -> bool:
        """Are the credentials the adapter needs present in Settings?"""
        ...

    def test_connection(self) -> ProviderStatus:
        """ONE cheap real call when configured; an honest status otherwise.

        Never raises: every failure becomes a typed status.
        """
        ...
