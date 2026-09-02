"""Session authentication for the internal API (Phase 5 G1).

Every `/internal/*` router (health excluded) requires a Bearer session
token issued by the login endpoint. Failures are typed and minimal: 401
for a missing/invalid session, 403 for an insufficient role — never a
detail that distinguishes unknown/expired/revoked. The resolved user is
exposed to route handlers via `request.state.current_user` so audited
commands can record the named actor.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security.utils import get_authorization_scheme_param
from sqlalchemy.orm import Session

from contentos.auth.enums import UserRole
from contentos.auth.errors import InvalidSessionError
from contentos.auth.models import User
from contentos.auth.service import AuthService, user_has_role
from contentos.db.session import get_db_session


def _bearer_token(request: Request) -> str:
    scheme, token = get_authorization_scheme_param(request.headers.get("Authorization") or "")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=401,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


def require_user(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
) -> User:
    token = _bearer_token(request)
    try:
        user = AuthService(session).verify_session(token)
    except InvalidSessionError:
        raise HTTPException(
            status_code=401,
            detail="invalid or expired session",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    request.state.current_user = user
    return user


def require_operator(user: Annotated[User, Depends(require_user)]) -> User:
    if not user_has_role(user, UserRole.OPERATOR):
        raise HTTPException(status_code=403, detail="the operator role is required")
    return user


def require_reviewer(user: Annotated[User, Depends(require_user)]) -> User:
    if not user_has_role(user, UserRole.REVIEWER):
        raise HTTPException(status_code=403, detail="the reviewer role is required")
    return user
