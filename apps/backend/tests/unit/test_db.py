"""Tests for the database engine and session foundation."""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request
from pydantic import ValidationError
from sqlalchemy import Engine
from sqlalchemy.orm import Session

import contentos.db.base as db_base_module
import contentos.db.session as db_session_module
from contentos.api.app import create_app
from contentos.core.config import Environment, LogLevel, Settings
from contentos.db.base import Base
from contentos.db.session import (
    create_database_engine,
    create_session_factory,
    get_db_session,
    session_scope,
)

SAFE_TEST_DB_URL = "postgresql+psycopg://contentos:db-secret-value@localhost:5432/contentos_test"


def db_test_settings(database_url: str = SAFE_TEST_DB_URL) -> Settings:
    return Settings(
        environment=Environment.TEST,
        service_name="ContentOS DB Test",
        application_version="1.0.0-test",
        log_level=LogLevel.INFO,
        api_docs_enabled=False,
        database_url=database_url,
        db_pool_size=3,
        db_pool_timeout_seconds=7,
        db_connect_timeout_seconds=4,
    )


def app_with_fake_session_factory() -> tuple[FastAPI, MagicMock]:
    app = create_app(settings=db_test_settings())
    session = MagicMock(spec=Session)
    app.state.db_session_factory = MagicMock(return_value=session)
    return app, session


def request_for(app: FastAPI) -> Request:
    scope = {
        "type": "http",
        "app": app,
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
    }
    return Request(scope)


def test_settings_accept_contentos_database_url() -> None:
    settings = db_test_settings()

    assert settings.database_url.get_secret_value() == SAFE_TEST_DB_URL
    assert settings.db_pool_size == 3
    assert settings.db_pool_timeout_seconds == 7
    assert settings.db_connect_timeout_seconds == 4


@pytest.mark.parametrize(
    "invalid_url",
    ["", "postgresql://user:pw@localhost/db", "mysql+pymysql://user:pw@localhost/db", "not-a-url"],
)
def test_settings_reject_non_psycopg_database_urls(invalid_url: str) -> None:
    with pytest.raises(ValidationError):
        db_test_settings(database_url=invalid_url)


def test_database_url_secret_is_not_exposed_by_settings() -> None:
    settings = db_test_settings()

    assert "db-secret-value" not in repr(settings)
    assert "db-secret-value" not in str(settings)


def test_no_engine_is_created_at_import_time() -> None:
    for module in (db_session_module, db_base_module):
        assert not any(isinstance(value, Engine) for value in vars(module).values())


def test_declarative_base_registers_exactly_the_known_tables() -> None:
    import contentos.discovery.models  # noqa: F401
    import contentos.duplicates.models  # noqa: F401
    import contentos.fetching.snapshots  # noqa: F401
    import contentos.normalization.models  # noqa: F401
    import contentos.opportunities.models  # noqa: F401
    import contentos.payloads.postgres  # noqa: F401
    import contentos.research.models  # noqa: F401
    import contentos.signals.models  # noqa: F401
    import contentos.sources.models  # noqa: F401
    import contentos.workflow.models  # noqa: F401

    assert set(Base.metadata.tables) == {
        "sources",
        "source_lifecycle_events",
        "discovery_items",
        "duplicate_decisions",
        "fetch_snapshots",
        "normalized_documents",
        "research_evidence",
        "raw_payload_blobs",
        "editorial_work_items",
        "editorial_workflow_events",
        "editorial_opportunities",
        "opportunity_research_inputs",
        "opportunity_scores",
        "opportunity_score_components",
        "search_signals",
    }


def test_engine_factory_applies_configured_pooling(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    fake_engine = MagicMock(spec=Engine)

    def fake_create_engine(url: str, **kwargs: object) -> Engine:
        captured["url"] = url
        captured.update(kwargs)
        return fake_engine

    monkeypatch.setattr(db_session_module, "create_engine", fake_create_engine)

    engine = create_database_engine(db_test_settings())

    assert engine is fake_engine
    assert captured["url"] == SAFE_TEST_DB_URL
    assert captured["pool_pre_ping"] is True
    assert captured["pool_size"] == 3
    assert captured["pool_timeout"] == 7
    assert captured["connect_args"] == {"connect_timeout": 4}


def test_engine_creation_does_not_connect_and_masks_password() -> None:
    engine = create_database_engine(db_test_settings())
    try:
        assert engine.url.drivername == "postgresql+psycopg"
        assert engine.url.database == "contentos_test"
        assert "db-secret-value" not in repr(engine)
        assert "db-secret-value" not in repr(engine.url)
    finally:
        engine.dispose()


def test_session_factory_creates_bound_sessions_without_expire_on_commit() -> None:
    engine = create_database_engine(db_test_settings())
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            assert isinstance(session, Session)
            assert session.get_bind() is engine
            assert session.expire_on_commit is False
    finally:
        engine.dispose()


def test_session_scope_yields_closes_and_never_commits() -> None:
    session = MagicMock(spec=Session)
    factory = MagicMock(return_value=session)

    with session_scope(factory) as scoped:
        assert scoped is session
        session.close.assert_not_called()

    session.close.assert_called_once()
    session.commit.assert_not_called()
    session.rollback.assert_not_called()


def test_session_scope_rolls_back_reraises_and_closes_on_failure() -> None:
    session = MagicMock(spec=Session)
    factory = MagicMock(return_value=session)

    with pytest.raises(RuntimeError, match="database operation failed"):
        with session_scope(factory):
            raise RuntimeError("database operation failed")

    session.rollback.assert_called_once()
    session.close.assert_called_once()
    session.commit.assert_not_called()


def test_create_app_prepares_replaceable_session_factory() -> None:
    app = create_app(settings=db_test_settings())

    assert callable(app.state.db_session_factory)

    replacement = MagicMock()
    app.state.db_session_factory = replacement
    assert app.state.db_session_factory is replacement


def test_fastapi_dependency_yields_one_session_and_closes_without_commit() -> None:
    app, session = app_with_fake_session_factory()

    dependency = get_db_session(request_for(app))
    yielded = next(dependency)

    assert yielded is session
    session.close.assert_not_called()

    with pytest.raises(StopIteration):
        next(dependency)

    session.close.assert_called_once()
    session.commit.assert_not_called()


def test_fastapi_dependency_rolls_back_when_request_handling_fails() -> None:
    app, session = app_with_fake_session_factory()

    dependency = get_db_session(request_for(app))
    next(dependency)

    with pytest.raises(RuntimeError, match="route failure"):
        dependency.throw(RuntimeError("route failure"))

    session.rollback.assert_called_once()
    session.close.assert_called_once()
    session.commit.assert_not_called()
