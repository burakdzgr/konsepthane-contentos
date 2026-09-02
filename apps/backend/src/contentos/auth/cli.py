"""User management CLI (Phase 5 G1).

Usage (from apps/backend, against the configured CONTENTOS_DATABASE_URL):

    uv run python -m contentos.auth.cli create-user <username> \\
        --display-name "..." --roles operator,reviewer --reason "..."
    uv run python -m contentos.auth.cli set-password <username> --reason "..."
    uv run python -m contentos.auth.cli set-roles <username> --roles reviewer --reason "..."
    uv run python -m contentos.auth.cli set-active <username> --active false --reason "..."

Passwords are read from the CONTENTOS_NEW_PASSWORD environment variable
or prompted interactively — never taken as a command-line argument
(process lists leak). Every action writes an audited user_events row.
"""

import argparse
import getpass
import os
import sys

from sqlalchemy.orm import Session

from contentos.auth.enums import UserRole
from contentos.auth.errors import AuthError
from contentos.auth.service import AuthService
from contentos.core.config import Settings
from contentos.db.session import create_database_engine, create_session_factory


def _parse_roles(raw: str) -> list[UserRole]:
    return [UserRole(part.strip()) for part in raw.split(",") if part.strip()]


def _read_password() -> str:
    from_env = os.environ.get("CONTENTOS_NEW_PASSWORD")
    if from_env:
        return from_env
    return getpass.getpass("New password: ")


def run_command(session: Session, args: argparse.Namespace) -> str:
    """Command core, separated for testability (no engine, no prompts)."""
    service = AuthService(session)
    if args.command == "create-user":
        user = service.provision_user(
            args.username,
            display_name=args.display_name,
            password=args.password,
            roles=_parse_roles(args.roles),
            reason=args.reason,
        )
        return f"provisioned {user.username} roles={user.roles}"
    if args.command == "set-password":
        user = service.rotate_password(args.username, password=args.password, reason=args.reason)
        return f"rotated password for {user.username}"
    if args.command == "set-roles":
        user = service.set_roles(args.username, roles=_parse_roles(args.roles), reason=args.reason)
        return f"set roles for {user.username}: {user.roles}"
    if args.command == "set-active":
        user = service.set_active(
            args.username,
            active=args.active.lower() == "true",
            reason=args.reason,
        )
        return f"set {user.username} active={user.is_active}"
    raise AuthError(f"unknown command {args.command!r}")  # pragma: no cover


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="contentos-auth")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-user")
    create.add_argument("username")
    create.add_argument("--display-name", required=True)
    create.add_argument("--roles", required=True)
    create.add_argument("--reason", required=True)

    password = sub.add_parser("set-password")
    password.add_argument("username")
    password.add_argument("--reason", required=True)

    roles = sub.add_parser("set-roles")
    roles.add_argument("username")
    roles.add_argument("--roles", required=True)
    roles.add_argument("--reason", required=True)

    active = sub.add_parser("set-active")
    active.add_argument("username")
    active.add_argument("--active", required=True, choices=["true", "false"])
    active.add_argument("--reason", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command in ("create-user", "set-password"):
        args.password = _read_password()
    engine = create_database_engine(Settings())
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            message = run_command(session, args)
            session.commit()
    except AuthError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print(message)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
