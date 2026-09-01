"""Manual search-signal recording (the only Task 5 admission path).

The service validates and canonicalizes one operator observation, computes
its deterministic identity, and appends it idempotently. It flushes; the
caller commits. Recording a signal has zero workflow/opportunity/scoring
side effects — it only persists an observation.

There is deliberately no ``provider`` parameter: the sole operational
provider today is MANUAL_OPERATOR, and future governed connectors get their
own explicit admission paths instead of a spoofable free-form argument.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from contentos.signals.enums import MANUAL_OPERATOR_PROVIDER, SearchSignalType
from contentos.signals.errors import InvalidSignalInputError, SignalConflictError
from contentos.signals.models import SearchSignal
from contentos.signals.repository import SearchSignalRepository
from contentos.signals.values import validate_signal_value

OBSERVATION_IDENTITY_SCHEMA_VERSION = 1

MAX_SUBJECT_LENGTH = 300
MAX_LOCALE_LENGTH = 20


@dataclass(frozen=True, slots=True)
class RecordedSignal:
    """The durable observation; `created` is False on an exact idempotent retry."""

    signal: SearchSignal
    created: bool


class SearchSignalService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = SearchSignalRepository(session)

    def record_manual_signal(
        self,
        *,
        signal_type: SearchSignalType,
        subject: str,
        value: dict[str, Any],
        observed_at: datetime,
        locale: str = "tr-TR",
        market: str = "TR",
        as_of: datetime | None = None,
        confidence: float | None = None,
    ) -> RecordedSignal:
        if not isinstance(signal_type, SearchSignalType):
            raise InvalidSignalInputError("signal_type must be a SearchSignalType value")
        cleaned_subject = _normalize_subject(subject)
        cleaned_locale = _validate_locale(locale)
        cleaned_market = _validate_market(market)
        canonical_value = validate_signal_value(signal_type, value)
        _validate_timestamp("observed_at", observed_at)
        if as_of is not None:
            _validate_timestamp("as_of", as_of)
        validated_confidence = _validate_confidence(confidence)

        observation_hash = _observation_hash(
            signal_type=signal_type,
            subject=cleaned_subject,
            locale=cleaned_locale,
            market=cleaned_market,
            provider=MANUAL_OPERATOR_PROVIDER,
            value=canonical_value,
            confidence=validated_confidence,
            observed_at=observed_at,
            as_of=as_of,
        )
        existing = self._repository.get_by_observation_hash(observation_hash)
        if existing is not None:
            return RecordedSignal(signal=existing, created=False)

        try:
            with self._session.begin_nested():
                signal = self._repository.add(
                    SearchSignal(
                        signal_type=signal_type,
                        subject=cleaned_subject,
                        locale=cleaned_locale,
                        market=cleaned_market,
                        provider=MANUAL_OPERATOR_PROVIDER,
                        value=canonical_value,
                        confidence=validated_confidence,
                        observed_at=observed_at,
                        as_of=as_of,
                        observation_hash=observation_hash,
                    )
                )
        except IntegrityError:
            winner = self._repository.get_by_observation_hash(observation_hash)
            if winner is not None:
                return RecordedSignal(signal=winner, created=False)
            raise SignalConflictError(
                "signal recording conflicted with concurrently written state"
            ) from None
        return RecordedSignal(signal=signal, created=True)


def _normalize_subject(subject: str) -> str:
    """Conservative whitespace normalization only — no slugs, no NLP, no
    case folding (Turkish casing is deliberately left untouched)."""
    if not isinstance(subject, str):
        raise InvalidSignalInputError("subject must be a string")
    cleaned = " ".join(subject.split())
    if not cleaned:
        raise InvalidSignalInputError("subject must not be empty")
    if len(cleaned) > MAX_SUBJECT_LENGTH:
        raise InvalidSignalInputError(f"subject exceeds the {MAX_SUBJECT_LENGTH}-character limit")
    return cleaned


def _validate_locale(locale: str) -> str:
    if not isinstance(locale, str) or not locale.strip():
        raise InvalidSignalInputError("locale must not be empty")
    cleaned = locale.strip()
    if len(cleaned) > MAX_LOCALE_LENGTH:
        raise InvalidSignalInputError("locale exceeds the length limit")
    return cleaned


def _validate_market(market: str) -> str:
    if not isinstance(market, str):
        raise InvalidSignalInputError("market must be a string")
    cleaned = market.strip()
    if len(cleaned) != 2:
        raise InvalidSignalInputError("market must be a two-letter country code")
    return cleaned


def _validate_timestamp(name: str, value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise InvalidSignalInputError(f"{name} must be a timezone-aware datetime")


def _validate_confidence(confidence: float | None) -> float | None:
    if confidence is None:
        return None
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise InvalidSignalInputError("confidence must be a number between 0 and 1")
    value = float(confidence)
    if value != value or value < 0 or value > 1:  # NaN-safe range check
        raise InvalidSignalInputError("confidence must be a number between 0 and 1")
    return value


def _observation_hash(
    *,
    signal_type: SearchSignalType,
    subject: str,
    locale: str,
    market: str,
    provider: str,
    value: dict[str, Any],
    confidence: float | None,
    observed_at: datetime,
    as_of: datetime | None,
) -> str:
    """Deterministic exact-observation identity (persistence idempotency only).

    QUERY_SET order is preserved in the canonical value because operator
    ordering is semantically meaningful, so reordering queries is a new
    observation by design.
    """
    identity = {
        "schema": OBSERVATION_IDENTITY_SCHEMA_VERSION,
        "signal_type": signal_type.value,
        "subject": subject,
        "locale": locale,
        "market": market,
        "provider": provider,
        "value": value,
        "confidence": confidence,
        "observed_at": observed_at.isoformat(),
        "as_of": as_of.isoformat() if as_of is not None else None,
    }
    canonical = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
