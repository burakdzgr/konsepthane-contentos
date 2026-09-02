"""Typed auth domain errors; transport-neutral. Messages never contain
credential or token material."""


class AuthError(Exception):
    """Base class for auth domain errors."""


class AuthInputError(AuthError):
    """A user-management or login input violates the bounded contract."""


class UserNotFoundError(AuthError):
    """No user exists for the given identity."""


class UserConflictError(AuthError):
    """The username is already provisioned."""


class InvalidCredentialsError(AuthError):
    """Login failed: unknown user, wrong password, or deactivated user.
    Deliberately indistinguishable to the caller."""


class InvalidSessionError(AuthError):
    """The presented session token is unknown, expired, revoked, or its
    user is deactivated. Deliberately indistinguishable to the caller."""


class InsufficientRoleError(AuthError):
    """The authenticated user lacks the required role."""
