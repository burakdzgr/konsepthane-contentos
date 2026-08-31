"""Tests for the Alembic migration infrastructure and pgvector migration."""

import io
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from contentos.core.config import Settings

BACKEND_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
MIGRATIONS_DIR = BACKEND_DIR / "migrations"


@pytest.fixture(autouse=True)
def quiet_root_logging() -> Iterator[None]:
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    root.handlers = [logging.NullHandler()]
    try:
        yield
    finally:
        root.handlers = saved_handlers


def alembic_config(output_buffer: io.StringIO | None = None) -> Config:
    if output_buffer is None:
        return Config(str(ALEMBIC_INI))
    return Config(str(ALEMBIC_INI), output_buffer=output_buffer, stdout=output_buffer)


def offline_sql(direction: str, revision: str) -> str:
    buffer = io.StringIO()
    config = alembic_config(output_buffer=buffer)
    if direction == "upgrade":
        command.upgrade(config, revision, sql=True)
    else:
        command.downgrade(config, revision, sql=True)
    return buffer.getvalue()


def test_alembic_config_points_at_migrations_directory() -> None:
    assert ALEMBIC_INI.is_file()

    script = ScriptDirectory.from_config(alembic_config())

    assert Path(script.dir).resolve() == MIGRATIONS_DIR.resolve()


def test_migration_chain_has_expected_metadata() -> None:
    script = ScriptDirectory.from_config(alembic_config())

    assert script.get_heads() == ["0002"]

    initial = script.get_revision("0001")
    assert initial.down_revision is None
    assert "pgvector" in (initial.doc or "").lower()

    sources = script.get_revision("0002")
    assert sources.down_revision == "0001"


def test_offline_upgrade_enables_pgvector_without_leaking_url() -> None:
    sql = offline_sql("upgrade", "head")

    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql
    assert "DROP EXTENSION" not in sql
    assert Settings().database_url.get_secret_value() not in sql
    assert "postgresql+psycopg://" not in sql


def test_offline_downgrade_never_drops_the_extension() -> None:
    sql = offline_sql("downgrade", "0001:base")

    assert "Running downgrade" in sql
    assert "DROP EXTENSION" not in sql


def test_env_targets_existing_declarative_base_metadata() -> None:
    env_source = (MIGRATIONS_DIR / "env.py").read_text(encoding="utf-8")

    assert "from contentos.db.base import Base" in env_source
    assert "target_metadata = Base.metadata" in env_source
    assert "DeclarativeBase" not in env_source


def test_alembic_ini_contains_no_credentials_or_urls() -> None:
    ini_text = ALEMBIC_INI.read_text(encoding="utf-8").lower()

    assert "sqlalchemy.url" not in ini_text
    assert "postgresql" not in ini_text
    assert "@" not in ini_text
    assert Settings().database_url.get_secret_value().lower() not in ini_text
