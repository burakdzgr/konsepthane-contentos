"""Google service-account access tokens (JWT bearer flow, RS256).

`CONTENTOS_GOOGLE_SERVICE_ACCOUNT_JSON` may hold the key file's JSON
content or a path to it. The assertion is signed locally with google-auth's
signer; the token exchange goes through the provider's own HTTP client so
tests can fake it. Tokens are cached until shortly before expiry.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from google.auth import crypt, jwt
from pydantic import SecretStr

from contentos.integrations.base import ProviderError, sanitize_error_class
from contentos.integrations.enums import ProviderState
from contentos.integrations.http import Clock, ProviderHttp

TOKEN_LIFETIME = timedelta(hours=1)
REFRESH_MARGIN = timedelta(seconds=60)
DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"
GRANT_TYPE = "urn:ietf:params:oauth:grant-type:jwt-bearer"


@dataclass(frozen=True, slots=True)
class ServiceAccountInfo:
    client_email: str
    token_uri: str
    project_id: str | None
    # The full key-file mapping stays private to the signer construction.
    _raw: dict[str, Any]

    def raw(self) -> dict[str, Any]:
        return dict(self._raw)


def invalid_service_account(reason: str) -> ProviderError:
    return ProviderError(
        f"google service account key unusable ({reason})",
        kind=ProviderState.ERROR,
        error_class=sanitize_error_class("google", "service_account_invalid"),
    )


def load_service_account(secret: SecretStr | None) -> ServiceAccountInfo:
    """Parse the key JSON (content or file path). Never logs or echoes it."""
    if secret is None:
        raise invalid_service_account("missing")
    value = secret.get_secret_value().strip()
    if not value:
        raise invalid_service_account("missing")
    text = value
    if not value.startswith("{"):
        path = Path(value)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            raise invalid_service_account("file_unreadable") from None
    try:
        payload = json.loads(text)
    except ValueError:
        raise invalid_service_account("not_json") from None
    if not isinstance(payload, dict):
        raise invalid_service_account("not_object")
    email = payload.get("client_email")
    key = payload.get("private_key")
    if not isinstance(email, str) or not email or not isinstance(key, str) or not key:
        raise invalid_service_account("fields_missing")
    token_uri = payload.get("token_uri")
    project = payload.get("project_id")
    return ServiceAccountInfo(
        client_email=email,
        token_uri=token_uri if isinstance(token_uri, str) and token_uri else DEFAULT_TOKEN_URI,
        project_id=project if isinstance(project, str) else None,
        _raw=payload,
    )


class ServiceAccountTokenSource:
    """Mints and caches one scoped access token for a service account."""

    def __init__(
        self,
        info: ServiceAccountInfo,
        scopes: tuple[str, ...],
        *,
        http: ProviderHttp,
        clock: Clock,
    ) -> None:
        self._info = info
        self._scopes = scopes
        self._http = http
        self._clock = clock
        self._token: str | None = None
        self._expires_at: datetime | None = None

    def access_token(self) -> str:
        now = self._clock()
        if (
            self._token is not None
            and self._expires_at is not None
            and now + REFRESH_MARGIN < self._expires_at
        ):
            return self._token
        assertion = self._assertion(now)
        try:
            response = self._http.request(
                "POST",
                self._info.token_uri,
                data={"grant_type": GRANT_TYPE, "assertion": assertion},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except ProviderError as error:
            # A refused exchange (bad key, clock skew, disabled account) is an
            # access problem, whatever the vendor status code was.
            if error.kind in (ProviderState.ERROR, ProviderState.ACCESS_REQUIRED):
                raise ProviderError(
                    "google token exchange refused",
                    kind=ProviderState.ACCESS_REQUIRED,
                    error_class=sanitize_error_class("google_token", error.error_class),
                ) from None
            raise
        body = self._http.json(response)
        token = body.get("access_token") if isinstance(body, dict) else None
        expires_in = body.get("expires_in") if isinstance(body, dict) else None
        if not isinstance(token, str) or not token:
            raise ProviderError(
                "google token exchange returned no token",
                kind=ProviderState.ERROR,
                error_class=sanitize_error_class("google_token", "malformed"),
            )
        lifetime = (
            timedelta(seconds=int(expires_in))
            if isinstance(expires_in, (int, float)) and expires_in > 0
            else TOKEN_LIFETIME
        )
        self._token = token
        self._expires_at = self._clock() + lifetime
        return token

    def _assertion(self, now: datetime) -> str:
        try:
            signer = crypt.RSASigner.from_service_account_info(self._info.raw())  # type: ignore[no-untyped-call]
        except (ValueError, TypeError, KeyError):
            raise invalid_service_account("private_key") from None
        issued = int(now.timestamp())
        payload = {
            "iss": self._info.client_email,
            "scope": " ".join(self._scopes),
            "aud": self._info.token_uri,
            "iat": issued,
            "exp": issued + int(TOKEN_LIFETIME.total_seconds()),
        }
        encoded = jwt.encode(signer, payload)  # type: ignore[no-untyped-call]
        return encoded.decode("utf-8") if isinstance(encoded, bytes) else str(encoded)
