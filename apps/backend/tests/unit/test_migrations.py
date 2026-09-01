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

    assert script.get_heads() == ["0009"]

    initial = script.get_revision("0001")
    assert initial.down_revision is None
    assert "pgvector" in (initial.doc or "").lower()

    assert script.get_revision("0002").down_revision == "0001"
    assert script.get_revision("0003").down_revision == "0002"
    assert script.get_revision("0004").down_revision == "0003"
    assert script.get_revision("0005").down_revision == "0004"
    assert script.get_revision("0006").down_revision == "0005"
    assert script.get_revision("0007").down_revision == "0006"
    assert script.get_revision("0008").down_revision == "0007"
    assert script.get_revision("0009").down_revision == "0008"


def test_fetch_snapshot_migration_contains_append_only_protection() -> None:
    sql = offline_sql("upgrade", "0003:0004")

    assert "CREATE TABLE fetch_snapshots" in sql
    assert "CREATE TRIGGER trg_fetch_snapshots_append_only" in sql
    assert "BEFORE UPDATE OR DELETE ON fetch_snapshots" in sql
    assert "ON DELETE RESTRICT" in sql


def test_normalized_document_migration_contains_provenance_and_append_only_protection() -> None:
    sql = offline_sql("upgrade", "0004:0005")

    assert "CREATE TABLE normalized_documents" in sql
    assert "uq_normalized_documents_snapshot_extractor" in sql
    assert "CREATE TRIGGER trg_normalized_documents_append_only" in sql
    assert "BEFORE UPDATE OR DELETE ON normalized_documents" in sql
    assert "ON DELETE RESTRICT" in sql


def test_duplicate_decision_migration_contains_identity_and_append_only_protection() -> None:
    sql = offline_sql("upgrade", "0005:0006")

    assert "CREATE TABLE duplicate_decisions" in sql
    assert "uq_duplicate_decisions_document_engine" in sql
    assert "ck_duplicate_decisions_decision" in sql
    assert "CREATE TRIGGER trg_duplicate_decisions_append_only" in sql
    assert "BEFORE UPDATE OR DELETE ON duplicate_decisions" in sql
    assert "ON DELETE RESTRICT" in sql


def test_research_evidence_migration_contains_provenance_and_append_only_protection() -> None:
    sql = offline_sql("upgrade", "0006:0007")

    assert "CREATE TABLE research_evidence" in sql
    assert "uq_research_evidence_document_extractor_key" in sql
    assert "ck_research_evidence_excerpt_consistency" in sql
    assert "CREATE TRIGGER trg_research_evidence_append_only" in sql
    assert "BEFORE UPDATE OR DELETE ON research_evidence" in sql
    assert sql.count("ON DELETE RESTRICT") == 3


def test_raw_payload_blob_migration_contains_identity_and_append_only_protection() -> None:
    sql = offline_sql("upgrade", "0007:0008")

    assert "CREATE TABLE raw_payload_blobs" in sql
    assert "ck_raw_payload_blobs_sha256_format" in sql
    assert "ck_raw_payload_blobs_size_consistency" in sql
    assert "BYTEA" in sql
    assert "CREATE TRIGGER trg_raw_payload_blobs_append_only" in sql
    assert "BEFORE UPDATE OR DELETE ON raw_payload_blobs" in sql


def test_editorial_workflow_migration_contains_audit_and_append_only_protection() -> None:
    sql = offline_sql("upgrade", "0008:0009")

    assert "CREATE TABLE editorial_work_items" in sql
    assert "CREATE TABLE editorial_workflow_events" in sql
    assert "ck_editorial_work_items_current_state" in sql
    assert "ck_editorial_work_items_blocked_reason" in sql
    assert "ck_editorial_work_items_rejected_reason" in sql
    assert "ck_editorial_workflow_events_artifact_refs_object" in sql
    assert "CREATE TRIGGER trg_editorial_workflow_events_append_only" in sql
    assert "BEFORE UPDATE OR DELETE ON editorial_workflow_events" in sql
    assert "ON DELETE RESTRICT" in sql


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
