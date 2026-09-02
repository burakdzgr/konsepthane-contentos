"""Authentication endpoints: login, logout, whoami.

Login is the ONLY unauthenticated `/internal/*` route besides health.
The raw session token appears exactly once — in the login response —
and is otherwise carried as a Bearer header. Nothing here ever returns
password material or token hashes.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from contentos.api.security import _bearer_token, require_user
from contentos.auth.errors import InvalidCredentialsError, InvalidSessionError
from contentos.auth.models import User
from contentos.auth.service import AuthService
from contentos.db.session import get_db_session

router = APIRouter(prefix="/internal/auth")


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserView(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    username: str
    display_name: str
    roles: list[str]


class LoginResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["authenticated"]
    token: str
    expires_at: str
    user: UserView


class LogoutResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["logged_out"]


def _user_view(user: User) -> UserView:
    return UserView(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        roles=list(user.roles or []),
    )


@router.post("/login", response_model=LoginResponse)
def login(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    body: LoginRequest,
) -> LoginResponse:
    settings = request.app.state.settings
    try:
        issued = AuthService(session).issue_session(
            body.username,
            body.password,
            ttl_hours=settings.auth_session_ttl_hours,
        )
    except InvalidCredentialsError:
        raise HTTPException(status_code=401, detail="invalid credentials") from None
    session.commit()
    return LoginResponse(
        status="authenticated",
        token=issued.token,
        expires_at=issued.session.expires_at.isoformat(),
        user=_user_view(issued.user),
    )


@router.post("/logout", response_model=LogoutResponse)
def logout(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    user: Annotated[User, Depends(require_user)],
) -> LogoutResponse:
    try:
        AuthService(session).revoke_session(_bearer_token(request))
    except InvalidSessionError:  # pragma: no cover - require_user already verified
        raise HTTPException(status_code=401, detail="invalid or expired session") from None
    session.commit()
    return LogoutResponse(status="logged_out")


@router.get("/me", response_model=UserView)
def whoami(user: Annotated[User, Depends(require_user)]) -> UserView:
    return _user_view(user)
