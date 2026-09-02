"""Auth foundation tests: service, CLI core, API enforcement (Phase 5 G1)."""

import argparse
from datetime import UTC, datetime, timedelta

import pytest
from editorial_harness import (
    TEST_OPERATOR_PASSWORD,
    TEST_OPERATOR_USERNAME,
    Harness,
)
from sqlalchemy import select

import contentos.auth.models  # noqa: F401  (register tables before create_all)
from contentos.auth.cli import run_command
from contentos.auth.enums import UserEventAction, UserRole
from contentos.auth.errors import (
    AuthInputError,
    InvalidCredentialsError,
    InvalidSessionError,
    UserConflictError,
)
from contentos.auth.models import AuthSession, UserEvent
from contentos.auth.service import AuthService, user_has_role


@pytest.fixture()
def harness() -> Harness:
    return Harness()


class TestUserManagement:
    def test_provision_is_audited_and_unique(self, harness: Harness) -> None:
        with harness.session() as session:
            service = AuthService(session)
            user = service.provision_user(
                "Editor.One",
                display_name="Editör Bir",
                password="a-long-enough-password",
                roles=[UserRole.REVIEWER],
                reason="ilk hakem hesabı",
            )
            session.commit()
            assert user.username == "editor.one"  # normalized
            assert user.roles == ["reviewer"]
            assert user_has_role(user, UserRole.REVIEWER)
            assert not user_has_role(user, UserRole.OPERATOR)
            events = (
                session.execute(select(UserEvent).where(UserEvent.user_id == user.id))
                .scalars()
                .all()
            )
            assert [event.action for event in events] == [UserEventAction.PROVISIONED]
            assert "password" not in str(events[0].detail).lower()

            with pytest.raises(UserConflictError):
                service.provision_user(
                    "editor.one",
                    display_name="Kopya",
                    password="another-long-password",
                    roles=[UserRole.OPERATOR],
                    reason="kopya",
                )

    def test_password_rules_and_rotation(self, harness: Harness) -> None:
        with harness.session() as session:
            service = AuthService(session)
            with pytest.raises(AuthInputError, match="password"):
                service.provision_user(
                    "shortpw",
                    display_name="Kısa",
                    password="too-short",
                    roles=[UserRole.OPERATOR],
                    reason="kısa parola",
                )
            service.rotate_password(
                TEST_OPERATOR_USERNAME,
                password="a-brand-new-long-password",
                reason="dönemsel rotasyon",
            )
            session.commit()
            # Old password no longer works; the new one does.
            with pytest.raises(InvalidCredentialsError):
                service.issue_session(TEST_OPERATOR_USERNAME, TEST_OPERATOR_PASSWORD)
            issued = service.issue_session(TEST_OPERATOR_USERNAME, "a-brand-new-long-password")
            assert issued.user.credentials_rotated_at is not None

    def test_deactivation_blocks_login_and_sessions(self, harness: Harness) -> None:
        with harness.session() as session:
            service = AuthService(session)
            issued = service.issue_session(TEST_OPERATOR_USERNAME, TEST_OPERATOR_PASSWORD)
            session.commit()
            service.set_active(TEST_OPERATOR_USERNAME, active=False, reason="ayrıldı")
            session.commit()
            with pytest.raises(InvalidCredentialsError):
                service.issue_session(TEST_OPERATOR_USERNAME, TEST_OPERATOR_PASSWORD)
            # Existing sessions die with the user.
            with pytest.raises(InvalidSessionError):
                service.verify_session(issued.token)


class TestSessions:
    def test_token_is_never_stored_raw(self, harness: Harness) -> None:
        with harness.session() as session:
            issued = AuthService(session).issue_session(
                TEST_OPERATOR_USERNAME, TEST_OPERATOR_PASSWORD
            )
            session.commit()
            row = session.execute(select(AuthSession)).scalar_one()
            assert issued.token not in row.token_hash
            assert len(row.token_hash) == 64

    def test_verify_expiry_and_revocation_fail_closed(self, harness: Harness) -> None:
        with harness.session() as session:
            service = AuthService(session)
            issued = service.issue_session(TEST_OPERATOR_USERNAME, TEST_OPERATOR_PASSWORD)
            session.commit()
            assert service.verify_session(issued.token).username == TEST_OPERATOR_USERNAME

            # Expire it (test-only direct mutation; SQLite has no trigger).
            issued.session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            session.commit()
            with pytest.raises(InvalidSessionError):
                service.verify_session(issued.token)

            second = service.issue_session(TEST_OPERATOR_USERNAME, TEST_OPERATOR_PASSWORD)
            session.commit()
            service.revoke_session(second.token)
            session.commit()
            with pytest.raises(InvalidSessionError):
                service.verify_session(second.token)
            with pytest.raises(InvalidSessionError):
                service.verify_session("not-a-real-token")


class TestCli:
    def test_cli_core_commands(self, harness: Harness) -> None:
        with harness.session() as session:
            message = run_command(
                session,
                argparse.Namespace(
                    command="create-user",
                    username="cli.user",
                    display_name="CLI Kullanıcısı",
                    roles="operator,reviewer",
                    reason="cli testi",
                    password="a-long-cli-password",
                ),
            )
            assert "provisioned cli.user" in message
            message = run_command(
                session,
                argparse.Namespace(
                    command="set-roles",
                    username="cli.user",
                    roles="reviewer",
                    reason="rol daralt",
                ),
            )
            assert "['reviewer']" in message
            message = run_command(
                session,
                argparse.Namespace(
                    command="set-active",
                    username="cli.user",
                    active="false",
                    reason="devre dışı",
                ),
            )
            assert "active=False" in message


class TestApiEnforcement:
    def test_unauthenticated_internal_requests_are_401(self, harness: Harness) -> None:
        # Bypass the harness auto-login by sending a blank Authorization.
        response = harness.request(
            "GET", "/internal/editorial/work-items", headers={"Authorization": ""}
        )
        assert response.status_code == 401
        assert response.headers.get("WWW-Authenticate") == "Bearer"

    def test_garbage_token_is_401(self, harness: Harness) -> None:
        response = harness.request(
            "GET",
            "/internal/editorial/work-items",
            headers={"Authorization": "Bearer not-a-token"},
        )
        assert response.status_code == 401

    def test_health_stays_open(self, harness: Harness) -> None:
        assert (
            harness.request("GET", "/health/live", headers={"Authorization": ""}).status_code == 200
        )

    def test_login_logout_me_flow(self, harness: Harness) -> None:
        login = harness.post(
            "/internal/auth/login",
            {"username": TEST_OPERATOR_USERNAME, "password": TEST_OPERATOR_PASSWORD},
        )
        assert login.status_code == 200
        body = login.json()
        token = body["token"]
        assert body["user"]["username"] == TEST_OPERATOR_USERNAME
        assert "password" not in login.text.lower() or "password" not in body

        me = harness.request(
            "GET", "/internal/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert me.status_code == 200
        assert me.json()["roles"] == ["operator", "reviewer"]

        logout = harness.request(
            "POST", "/internal/auth/logout", headers={"Authorization": f"Bearer {token}"}
        )
        assert logout.status_code == 200
        stale = harness.request(
            "GET", "/internal/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert stale.status_code == 401

    def test_bad_credentials_are_401_without_detail(self, harness: Harness) -> None:
        response = harness.post(
            "/internal/auth/login",
            {"username": TEST_OPERATOR_USERNAME, "password": "wrong-password-value"},
        )
        assert response.status_code == 401
        unknown = harness.post(
            "/internal/auth/login",
            {"username": "ghost.user", "password": "wrong-password-value"},
        )
        assert unknown.status_code == 401
        # Indistinguishable failures: identical messages.
        assert response.json()["error"]["message"] == unknown.json()["error"]["message"]

    def test_reviewer_only_user_cannot_drive_the_pipeline(self, harness: Harness) -> None:
        with harness.session() as session:
            AuthService(session).provision_user(
                "pure.reviewer",
                display_name="Sadece Hakem",
                password="a-long-reviewer-password",
                roles=[UserRole.REVIEWER],
                reason="rol testi",
            )
            session.commit()
        login = harness.post(
            "/internal/auth/login",
            {"username": "pure.reviewer", "password": "a-long-reviewer-password"},
        )
        assert login.status_code == 200
        token = login.json()["token"]
        response = harness.request(
            "GET",
            "/internal/editorial/work-items",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    def test_authenticated_operator_reaches_the_pipeline(self, harness: Harness) -> None:
        response = harness.get("/internal/editorial/work-items")
        assert response.status_code == 200


class TestSessionPruning:
    """Production-readiness: dead-session pruning (live sessions untouchable)."""

    def test_prune_removes_only_old_dead_sessions(self, harness: Harness) -> None:
        from datetime import UTC, datetime, timedelta

        from contentos.auth.models import AuthSession

        with harness.session() as session:
            service = AuthService(session)
            live = service.issue_session(TEST_OPERATOR_USERNAME, TEST_OPERATOR_PASSWORD)
            old_expired = service.issue_session(TEST_OPERATOR_USERNAME, TEST_OPERATOR_PASSWORD)
            recent_expired = service.issue_session(TEST_OPERATOR_USERNAME, TEST_OPERATOR_PASSWORD)
            old_revoked = service.issue_session(TEST_OPERATOR_USERNAME, TEST_OPERATOR_PASSWORD)
            session.commit()
            now = datetime.now(UTC)
            # SQLite has no immutability trigger: simulate aged rows directly.
            old_expired.session.expires_at = now - timedelta(days=90)
            recent_expired.session.expires_at = now - timedelta(days=2)
            old_revoked.session.revoked_at = now - timedelta(days=90)
            session.commit()

            pruned = service.prune_sessions(retention_days=30)
            session.commit()
            assert pruned == 2  # the two OLD dead sessions only
            remaining = {row.token_hash for row in session.query(AuthSession).all()}
            assert live.session.token_hash in remaining  # live untouched
            assert recent_expired.session.token_hash in remaining  # inside retention
            assert old_expired.session.token_hash not in remaining
            assert old_revoked.session.token_hash not in remaining
            # The live session still authenticates after pruning.
            assert service.verify_session(live.token).username == TEST_OPERATOR_USERNAME

    def test_prune_validates_retention_and_is_idempotent(self, harness: Harness) -> None:
        with harness.session() as session:
            service = AuthService(session)
            with pytest.raises(AuthInputError, match="retention_days"):
                service.prune_sessions(retention_days=-1)
            assert service.prune_sessions(retention_days=0) == 0
            assert service.prune_sessions(retention_days=0) == 0

    def test_cli_prune_command_reports_the_count(self, harness: Harness) -> None:
        import argparse

        from contentos.auth.cli import run_command

        with harness.session() as session:
            message = run_command(
                session,
                argparse.Namespace(command="prune-sessions", retention_days=30),
            )
            session.commit()
            assert message == "pruned 0 dead session(s) older than 30 day(s)"
