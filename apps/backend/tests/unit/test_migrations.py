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

    assert script.get_heads() == ["0015"]

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
    assert script.get_revision("0010").down_revision == "0009"
    assert script.get_revision("0011").down_revision == "0010"
    assert script.get_revision("0012").down_revision == "0011"
    assert script.get_revision("0013").down_revision == "0012"
    assert script.get_revision("0014").down_revision == "0013"
    assert script.get_revision("0015").down_revision == "0014"


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


def test_opportunity_migration_contains_identity_and_append_only_protection() -> None:
    sql = offline_sql("upgrade", "0009:0010")

    assert "CREATE TABLE editorial_opportunities" in sql
    assert "CREATE TABLE opportunity_research_inputs" in sql
    assert "uq_editorial_opportunities_work_item" in sql
    assert "uq_editorial_opportunities_promotion_root" in sql
    assert "uq_opportunity_research_inputs_document" in sql
    assert "ck_editorial_opportunities_disposition_consistency" in sql
    assert "CREATE TRIGGER trg_opportunity_research_inputs_append_only" in sql
    assert "BEFORE UPDATE OR DELETE ON opportunity_research_inputs" in sql
    assert sql.count("ON DELETE RESTRICT") == 5


def test_opportunity_score_migration_contains_identity_and_append_only_protection() -> None:
    sql = offline_sql("upgrade", "0010:0011")

    assert "CREATE TABLE opportunity_scores" in sql
    assert "CREATE TABLE opportunity_score_components" in sql
    assert "uq_opportunity_scores_identity" in sql
    assert "uq_opportunity_score_components_component" in sql
    assert "ck_opportunity_score_components_value_presence" in sql
    assert "CREATE TRIGGER trg_opportunity_scores_append_only" in sql
    assert "CREATE TRIGGER trg_opportunity_score_components_append_only" in sql
    assert sql.count("ON DELETE RESTRICT") == 2


def test_search_signal_migration_contains_identity_and_append_only_protection() -> None:
    sql = offline_sql("upgrade", "0011:0012")

    assert "CREATE TABLE search_signals" in sql
    assert "uq_search_signals_observation_hash" in sql
    assert "ck_search_signals_hash_format" in sql
    assert "ck_search_signals_value_object" in sql
    assert "CREATE TRIGGER trg_search_signals_append_only" in sql
    assert "BEFORE UPDATE OR DELETE ON search_signals" in sql


def test_evidence_pack_migration_contains_provenance_and_protection() -> None:
    sql = offline_sql("upgrade", "0012:0013")

    assert "CREATE TABLE evidence_packs" in sql
    assert "CREATE TABLE evidence_pack_items" in sql
    assert "CREATE TABLE evidence_contradictions" in sql
    assert "uq_evidence_packs_identity" in sql
    assert "assembly_input_hash" in sql
    assert "ck_evidence_packs_assembly_snapshot_object" in sql
    assert "uq_evidence_pack_items_evidence" in sql
    assert "ck_evidence_contradictions_resolution_consistency" in sql
    assert "CREATE TRIGGER trg_evidence_packs_append_only" in sql
    assert "CREATE TRIGGER trg_evidence_pack_items_append_only" in sql
    assert "CREATE TRIGGER trg_evidence_contradictions_guarded" in sql
    assert sql.count("ON DELETE RESTRICT") == 4


def test_idea_migration_contains_identity_and_append_only_protection() -> None:
    sql = offline_sql("upgrade", "0013:0014")

    assert "CREATE TABLE ideas" in sql
    assert "CREATE TABLE idea_selection_events" in sql
    assert "uq_ideas_logical_version" in sql
    assert "ck_ideas_version_positive" in sql
    assert "ck_ideas_angle_nonempty" in sql
    assert "ck_ideas_planning_dimensions_object" in sql
    assert "fk_evidence_packs_idea" in sql
    assert "CREATE TRIGGER trg_ideas_append_only" in sql
    assert "CREATE TRIGGER trg_idea_selection_events_append_only" in sql
    assert sql.count("ON DELETE RESTRICT") == 4


def test_ai_attempt_migration_contains_identity_and_staged_provenance() -> None:
    sql = offline_sql("upgrade", "0014:0015")

    assert "CREATE TABLE ai_generation_attempts" in sql
    assert "uq_ai_generation_attempts_identity" in sql
    assert "ck_ai_generation_attempts_error_consistency" in sql
    assert "ck_ai_generation_attempts_identity_hash_format" in sql
    assert "CREATE TRIGGER trg_ai_generation_attempts_append_only" in sql
    assert "fk_ideas_generation_attempt" in sql
    assert "ck_ideas_origin_attempt_consistency" in sql
    assert "origin IN ('operator', 'model_assisted')" in sql
    assert "fk_evidence_packs_organization_attempt" in sql
    assert sql.count("ON DELETE RESTRICT") == 2
    # Provenance/metadata only: never a payload archive.
    for forbidden in ("raw_response", "raw_output", "prompt", "completion_text"):
        assert forbidden not in sql


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
