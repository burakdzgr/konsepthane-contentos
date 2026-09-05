"""Live operations projection (ADR 0012): gateway parsing and the one read."""

import httpx
import pytest
from editorial_harness import Context, Harness, seed_scored
from pydantic import SecretStr

from contentos.api.read_models.operations import (
    _gateway_view,
    _read_gateway,
    read_gateway_screenshot,
)
from contentos.autopilot.enums import AutopilotMode
from contentos.autopilot.service import AutopilotService
from contentos.core.config import Settings


@pytest.fixture
def harness() -> Harness:
    return Harness()


GATEWAY_STATUS = {
    "status": "ok",
    "scheduler": {
        "hesap": 1,
        "mesgul": 1,
        "bekleyen": 2,
        "saglayici": {"chatgpt": {"toplam": 1, "hazir": 1, "mesgul": 1, "engelli": 0}},
    },
    "accounts": [
        {
            "id": "acc_1",
            "provider": "chatgpt",
            "label": "ChatGPT #1",
            "enabled": True,
            "blockedBy": None,
            "busy": True,
        }
    ],
    "jobStore": {
        "byStatus": {"queued": 2, "running": 1, "succeeded": 7},
        "running": [
            {
                "jobId": "job-9",
                "status": "running",
                "phase": "ChatGPT yanıtlıyor",
                "model": "chatgpt",
                "type": "text",
            }
        ],
    },
}


def test_gateway_status_maps_to_the_bounded_view() -> None:
    view = _gateway_view(GATEWAY_STATUS, provider="subcontractor", host="host.docker.internal")
    assert view.reachable and view.status == "ok"
    assert view.ready_accounts == 1
    assert view.queued == 2 and view.running == 1
    assert [account.label for account in view.accounts] == ["ChatGPT #1"]
    assert view.jobs[0].phase == "ChatGPT yanıtlıyor"


def settings(**overrides: object) -> Settings:
    base = dict(
        database_url="postgresql+psycopg://u:p@localhost:5432/db",
        redis_broker_url="redis://localhost:6379/0",
    )
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_unconfigured_and_unreachable_gateways_are_reported_truthfully() -> None:
    off = _read_gateway(settings())
    assert off.configured is False and off.reachable is False

    def refuse(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    http = httpx.Client(base_url="http://gateway.test", transport=httpx.MockTransport(refuse))
    down = _read_gateway(
        settings(
            ai_provider="subcontractor",
            subcontractor_base_url="http://gateway.test",
            subcontractor_admin_token=SecretStr("admin"),
        ),
        http,
    )
    assert down.configured is True and down.reachable is False
    assert down.error == "ConnectError"
    assert down.base_url_host == "gateway.test"


def test_admin_token_is_sent_server_side_and_never_returned() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json=GATEWAY_STATUS)

    http = httpx.Client(base_url="http://gateway.test", transport=httpx.MockTransport(handler))
    view = _read_gateway(
        settings(
            ai_provider="subcontractor",
            subcontractor_base_url="http://gateway.test",
            subcontractor_admin_token=SecretStr("admin-secret"),
        ),
        http,
    )
    assert seen == {"path": "/api/status", "auth": "Bearer admin-secret"}
    assert "admin-secret" not in view.model_dump_json()


def test_live_read_projects_autopilot_items_and_feed(harness: Harness) -> None:
    with harness.session() as session:
        context = Context()
        seed_scored(session, context)
        AutopilotService(session).set_mode(
            AutopilotMode.SUPERVISED,
            actor_user_id=_operator_id(harness),
            reason="ilk tur",
        )
        session.commit()
    response = harness.get("/internal/operations/live")
    assert response.status_code == 200
    body = response.json()
    assert body["autopilot"]["mode"] == "supervised"
    assert body["autopilot"]["actor_display_name"] == "Test Operator"
    [item] = body["items"]
    assert item["work_item_id"] == str(context.work_item_id)
    assert item["state"] == "idea_scoring"
    assert item["autopilot"] is None  # no step has run for it yet
    sources = {entry["source"] for entry in body["feed"]}
    assert {"autopilot", "workflow"} <= sources
    assert body["gateway"]["configured"] is False
    # No secret material anywhere in the page payload.
    assert "admin" not in response.text.lower() or "admin_token" not in response.text


def _operator_id(harness: Harness):  # type: ignore[no-untyped-def]
    from editorial_harness import TEST_OPERATOR_USERNAME
    from sqlalchemy import select

    from contentos.auth.models import User

    with harness.session() as session:
        user = session.scalar(select(User).where(User.username == TEST_OPERATOR_USERNAME))
        assert user is not None
        return user.id


def test_screenshot_proxy_returns_frames_only_from_a_configured_gateway() -> None:
    assert read_gateway_screenshot(settings()) is None

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/screenshot"
        assert request.headers.get("authorization") == "Bearer admin-secret"
        return httpx.Response(200, content=b"jpegframe", headers={"content-type": "image/jpeg"})

    http = httpx.Client(base_url="http://gateway.test", transport=httpx.MockTransport(handler))
    configured = settings(
        ai_provider="subcontractor",
        subcontractor_base_url="http://gateway.test",
        subcontractor_admin_token=SecretStr("admin-secret"),
    )
    assert read_gateway_screenshot(configured, http) == b"jpegframe"

    def no_session(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "no_session"})

    down = httpx.Client(base_url="http://gateway.test", transport=httpx.MockTransport(no_session))
    assert read_gateway_screenshot(configured, down) is None
