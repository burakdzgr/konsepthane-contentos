"""AuthService: named humans, argon2id credentials, opaque sessions.

Rules (PHASE5_GOVERNANCE_ARCHITECTURE.md §1/§4):
- passwords exist only as argon2id hashes; session tokens exist once (in
  the issue result) and are stored only as SHA-256 hashes;
- login failures and session failures are deliberately
  indistinguishable (no user enumeration, no state leakage);
- every management action writes an append-only user_events row with a
  required reason;
- sessions have a fixed TTL and a one-shot revocation — no sliding
  expiry, re-login instead.

The service flushes; the caller owns COMMIT.
"""

import hashlib
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.auth.enums import UserEventAction, UserRole
from contentos.auth.errors import (
    AuthInputError,
    InvalidCredentialsError,
    InvalidSessionError,
    UserConflictError,
    UserNotFoundError,
)
from contentos.auth.models import AuthSession, User, UserEvent

DEFAULT_SESSION_TTL_HOURS = 12
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 256
MAX_REASON_LENGTH = 1000

_USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
_hasher = PasswordHasher()


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """The ONLY carrier of the raw token; it is never persisted."""

    token: str
    session: AuthSession
    user: User


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _validate_password(password: str) -> str:
    if not isinstance(password, str) or not (
        MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH
    ):
        raise AuthInputError(
            f"password must be {MIN_PASSWORD_LENGTH}..{MAX_PASSWORD_LENGTH} characters"
        )
    return password


def _validate_reason(reason: str) -> str:
    cleaned = reason.strip() if isinstance(reason, str) else ""
    if not cleaned or len(cleaned) > MAX_REASON_LENGTH:
        raise AuthInputError(f"reason must be 1..{MAX_REASON_LENGTH} characters")
    return cleaned


def _validate_roles(roles: list[UserRole]) -> list[str]:
    if not roles:
        raise AuthInputError("a user must hold at least one role")
    cleaned: list[str] = []
    for role in roles:
        if not isinstance(role, UserRole):
            raise AuthInputError("roles must be UserRole values")
        if role.value not in cleaned:
            cleaned.append(role.value)
    return cleaned


class AuthService:
    def __init__(self, session: Session) -> None:
        self._session = session

    # --- user management (audited) ------------------------------------------

    def provision_user(
        self,
        username: str,
        *,
        display_name: str,
        password: str,
        roles: list[UserRole],
        reason: str,
    ) -> User:
        cleaned_username = username.strip().lower() if isinstance(username, str) else ""
        if not _USERNAME_PATTERN.fullmatch(cleaned_username):
            raise AuthInputError(
                "username must be a lowercase slug (a-z, 0-9, '.', '_', '-') of 2..64 characters"
            )
        cleaned_display = display_name.strip() if isinstance(display_name, str) else ""
        if not cleaned_display or len(cleaned_display) > 200:
            raise AuthInputError("display_name must be 1..200 characters")
        existing = self._session.execute(
            select(User).where(User.username == cleaned_username)
        ).scalar_one_or_none()
        if existing is not None:
            raise UserConflictError(f"user {cleaned_username!r} is already provisioned")
        user = User(
            username=cleaned_username,
            display_name=cleaned_display,
            password_hash=_hasher.hash(_validate_password(password)),
            roles=_validate_roles(roles),
            is_active=True,
        )
        self._session.add(user)
        self._session.flush()
        self._append_event(user, UserEventAction.PROVISIONED, reason, user.roles)
        return user

    def rotate_password(self, username: str, *, password: str, reason: str) -> User:
        user = self._require_user(username)
        user.password_hash = _hasher.hash(_validate_password(password))
        user.credentials_rotated_at = datetime.now(UTC)
        self._append_event(user, UserEventAction.PASSWORD_ROTATED, reason, [])
        self._session.flush()
        return user

    def set_roles(self, username: str, *, roles: list[UserRole], reason: str) -> User:
        user = self._require_user(username)
        user.roles = _validate_roles(roles)
        self._append_event(user, UserEventAction.ROLES_CHANGED, reason, user.roles)
        self._session.flush()
        return user

    def set_active(self, username: str, *, active: bool, reason: str) -> User:
        user = self._require_user(username)
        user.is_active = active
        self._append_event(
            user,
            UserEventAction.REACTIVATED if active else UserEventAction.DEACTIVATED,
            reason,
            [],
        )
        self._session.flush()
        return user

    # --- sessions ------------------------------------------------------------

    def issue_session(
        self,
        username: str,
        password: str,
        *,
        ttl_hours: int = DEFAULT_SESSION_TTL_HOURS,
    ) -> IssuedSession:
        """Login. Failures are indistinguishable by design."""
        cleaned_username = username.strip().lower() if isinstance(username, str) else ""
        user = self._session.execute(
            select(User).where(User.username == cleaned_username)
        ).scalar_one_or_none()
        if user is None or not user.is_active:
            raise InvalidCredentialsError("invalid credentials")
        try:
            _hasher.verify(user.password_hash, password)
        except VerifyMismatchError:
            raise InvalidCredentialsError("invalid credentials") from None
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        session_row = AuthSession(
            user_id=user.id,
            token_hash=_token_hash(token),
            expires_at=now + timedelta(hours=ttl_hours),
        )
        self._session.add(session_row)
        self._session.flush()
        return IssuedSession(token=token, session=session_row, user=user)

    def verify_session(self, token: str) -> User:
        """Resolve a presented token to its ACTIVE user, or fail closed."""
        if not isinstance(token, str) or not token:
            raise InvalidSessionError("invalid session")
        row = self._session.execute(
            select(AuthSession).where(AuthSession.token_hash == _token_hash(token))
        ).scalar_one_or_none()
        if row is None or row.revoked_at is not None:
            raise InvalidSessionError("invalid session")
        # SQLite returns timezone-naive datetimes; PostgreSQL timestamptz is
        # aware. Normalize defensively so expiry always compares in UTC.
        expires_at = (
            row.expires_at
            if row.expires_at.tzinfo is not None
            else row.expires_at.replace(tzinfo=UTC)
        )
        if expires_at <= datetime.now(UTC):
            raise InvalidSessionError("invalid session")
        user = self._session.get(User, row.user_id)
        if user is None or not user.is_active:
            raise InvalidSessionError("invalid session")
        return user

    def prune_sessions(self, *, retention_days: int = 30) -> int:
        """Delete DEAD sessions (revoked, or expired) whose end lies more
        than ``retention_days`` in the past. Live sessions are untouchable
        (the DB trigger enforces that independently); the retention window
        keeps recent operational history inspectable. Returns the count.
        The caller commits."""
        if not isinstance(retention_days, int) or retention_days < 0:
            raise AuthInputError("retention_days must be a non-negative integer")
        now = datetime.now(UTC)
        cutoff = now - timedelta(days=retention_days)
        rows = list(self._session.execute(select(AuthSession)).scalars())
        pruned = 0
        for row in rows:
            expires_at = (
                row.expires_at
                if row.expires_at.tzinfo is not None
                else row.expires_at.replace(tzinfo=UTC)
            )
            revoked_at = (
                row.revoked_at
                if row.revoked_at is None or row.revoked_at.tzinfo is not None
                else row.revoked_at.replace(tzinfo=UTC)
            )
            ended_at = revoked_at if revoked_at is not None else None
            if ended_at is None and expires_at <= now:
                ended_at = expires_at
            if ended_at is not None and ended_at < cutoff:
                self._session.delete(row)
                pruned += 1
        self._session.flush()
        return pruned

    def revoke_session(self, token: str) -> None:
        """Logout: one-shot revocation; unknown tokens fail closed."""
        row = self._session.execute(
            select(AuthSession).where(AuthSession.token_hash == _token_hash(token))
        ).scalar_one_or_none()
        if row is None:
            raise InvalidSessionError("invalid session")
        if row.revoked_at is None:
            row.revoked_at = datetime.now(UTC)
            self._session.flush()

    # --- internals -----------------------------------------------------------

    def _require_user(self, username: str) -> User:
        cleaned = username.strip().lower() if isinstance(username, str) else ""
        user = self._session.execute(
            select(User).where(User.username == cleaned)
        ).scalar_one_or_none()
        if user is None:
            raise UserNotFoundError(f"no user with username {cleaned!r}")
        return user

    def _append_event(
        self, user: User, action: UserEventAction, reason: str, detail: list[str]
    ) -> None:
        self._session.add(
            UserEvent(
                user_id=user.id,
                action=action,
                reason=_validate_reason(reason),
                detail=list(detail),
            )
        )


def user_has_role(user: User, role: UserRole) -> bool:
    return role.value in (user.roles or [])


def resolve_user_by_id(session: Session, user_id: uuid.UUID) -> User | None:
    return session.get(User, user_id)
