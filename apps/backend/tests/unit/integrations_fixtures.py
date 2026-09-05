"""Shared fakes for the integration provider tests (not collected)."""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from contentos.core.config import Environment, LogLevel, Settings

NOW = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)

FAKE_SEMRUSH_KEY = "semrush-secret-key-1234567890"
FAKE_PINTEREST_TOKEN = "pina_secret_token_ABCDEF"
FAKE_TRENDS_KEY = "trends-secret-key-XYZ"
FAKE_ACCESS_TOKEN = "ya29.fake-google-access-token"


def integration_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "environment": Environment.TEST,
        "service_name": "ContentOS Integrations Test",
        "application_version": "1.0.0-test",
        "log_level": LogLevel.INFO,
        "api_docs_enabled": False,
        "database_url": "postgresql+psycopg://contentos:int-secret@localhost:5432/contentos_int",
        "redis_broker_url": "redis://:int-secret@localhost:6379/0",
        "openai_api_key": "test-openai-key",
        "openai_model": "test-model",
        "openai_image_model": "test-image-model",
    }
    base.update(overrides)
    return Settings(**base)


class FixedClock:
    def __init__(self, start: datetime = NOW) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now = self.now + timedelta(**kwargs)


class Recorder:
    """A MockTransport handler that records requests and scripts responses."""

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self.sleeps: list[float] = []
        self._handler = handler

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


def text_response(status: int, body: str, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, text=body, headers=headers)


def json_response(status: int, body: Any, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, json=body, headers=headers)


def timeout_raiser(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("read timed out", request=request)


_PRIVATE_KEY_PEM: str | None = None


def service_account_json(**overrides: Any) -> str:
    """A syntactically valid service-account key with a throwaway RSA key."""
    global _PRIVATE_KEY_PEM
    if _PRIVATE_KEY_PEM is None:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        _PRIVATE_KEY_PEM = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode("ascii")
    payload = {
        "type": "service_account",
        "project_id": "konsepthane-test",
        "private_key_id": "abc123",
        "private_key": _PRIVATE_KEY_PEM,
        "client_email": "contentos@konsepthane-test.iam.gserviceaccount.com",
        "client_id": "1234567890",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    payload.update(overrides)
    return json.dumps(payload)


def token_response() -> httpx.Response:
    return json_response(200, {"access_token": FAKE_ACCESS_TOKEN, "expires_in": 3600})


def assert_no_secrets(text: str) -> None:
    for secret in (
        FAKE_SEMRUSH_KEY,
        FAKE_PINTEREST_TOKEN,
        FAKE_TRENDS_KEY,
        FAKE_ACCESS_TOKEN,
        "PRIVATE KEY",
    ):
        assert secret not in text
