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

    assert script.get_heads() == ["0027"]

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
    assert script.get_revision("0016").down_revision == "0015"
    assert script.get_revision("0017").down_revision == "0016"
    assert script.get_revision("0027").down_revision == "0026"
    assert script.get_revision("0026").down_revision == "0025"
    assert script.get_revision("0025").down_revision == "0024"
    assert script.get_revision("0024").down_revision == "0023"
    assert script.get_revision("0023").down_revision == "0022"
    assert script.get_revision("0022").down_revision == "0021"
    assert script.get_revision("0021").down_revision == "0020"
    assert script.get_revision("0020").down_revision == "0019"
    assert script.get_revision("0019").down_revision == "0018"
    assert script.get_revision("0018").down_revision == "0017"


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


def test_search_intent_migration_contains_identity_and_append_only_protection() -> None:
    sql = offline_sql("upgrade", "0015:0016")

    assert "CREATE TABLE search_intent_analyses" in sql
    assert "uq_search_intent_analyses_version" in sql
    assert "uq_search_intent_analyses_identity" in sql
    assert "ck_search_intent_analyses_cannibalization" in sql
    assert "ck_search_intent_analyses_hash_format" in sql
    assert "ck_search_intent_analyses_basis_object" in sql
    assert "CREATE TRIGGER trg_search_intent_analyses_append_only" in sql
    assert "BEFORE UPDATE OR DELETE ON search_intent_analyses" in sql
    assert sql.count("ON DELETE RESTRICT") == 3


def test_content_brief_migration_contains_identity_and_protection() -> None:
    sql = offline_sql("upgrade", "0016:0017")

    assert "CREATE TABLE content_briefs" in sql
    assert "CREATE TABLE brief_claims" in sql
    assert "CREATE TABLE brief_claim_evidence" in sql
    assert "CREATE TABLE brief_status_events" in sql
    assert "uq_content_briefs_version" in sql
    assert "uq_content_briefs_identity" in sql
    assert "uq_content_briefs_active" in sql
    assert "uq_brief_claims_key" in sql
    assert "uq_brief_claim_evidence_link" in sql
    assert "ck_content_briefs_hash_format" in sql
    assert "CREATE TRIGGER trg_content_briefs_guarded" in sql
    assert "CREATE TRIGGER trg_brief_claims_append_only" in sql
    assert "CREATE TRIGGER trg_brief_claim_evidence_append_only" in sql
    assert "CREATE TRIGGER trg_brief_status_events_append_only" in sql
    assert sql.count("ON DELETE RESTRICT") == 10
    # A brief is a contract, never the article.
    for forbidden in ("article_body", "markdown_body", "html_body", "draft_text"):
        assert forbidden not in sql


def test_content_draft_migration_contains_identity_and_protection() -> None:
    sql = offline_sql("upgrade", "0017:0018")

    assert "CREATE TABLE content_drafts" in sql
    assert "CREATE TABLE draft_claim_usages" in sql
    assert "CREATE TABLE draft_status_events" in sql
    assert "uq_content_drafts_version" in sql
    assert "uq_content_drafts_attempt" in sql
    assert "uq_content_drafts_active" in sql
    assert "uq_content_drafts_manual_identity" in sql
    assert "uq_draft_claim_usages_anchor" in sql
    assert "ck_content_drafts_operator_attempt" in sql
    assert "ck_content_drafts_manual_hash_origin" in sql
    assert "ck_content_drafts_hash_format" in sql
    assert "CREATE TRIGGER trg_content_drafts_guarded" in sql
    assert "CREATE TRIGGER trg_draft_claim_usages_append_only" in sql
    assert "CREATE TRIGGER trg_draft_status_events_append_only" in sql
    # The attempt purpose vocabulary gains the Writer purpose.
    assert "writer_draft" in sql
    assert sql.count("ON DELETE RESTRICT") == 8
    # A draft is structured content, never article HTML.
    for forbidden in ("html_body", "article_html", "raw_output", "prompt"):
        assert forbidden not in sql


def test_editorial_review_migration_contains_identity_and_protection() -> None:
    sql = offline_sql("upgrade", "0018:0019")

    assert "CREATE TABLE editorial_reviews" in sql
    assert "CREATE TABLE editorial_review_findings" in sql
    assert "CREATE TABLE editorial_review_status_events" in sql
    assert "uq_editorial_reviews_version" in sql
    assert "uq_editorial_reviews_attempt" in sql
    assert "uq_editorial_reviews_active" in sql
    assert "uq_editorial_review_findings_key" in sql
    assert "ck_editorial_reviews_verdict" in sql
    assert "ck_editorial_reviews_hash_format" in sql
    assert "CREATE TRIGGER trg_editorial_reviews_guarded" in sql
    assert "CREATE TRIGGER trg_editorial_review_findings_append_only" in sql
    assert "CREATE TRIGGER trg_editorial_review_status_events_append_only" in sql
    # The attempt purpose vocabulary gains the Editor purpose.
    assert "editor_review" in sql
    assert sql.count("ON DELETE RESTRICT") == 9
    # A review is findings + a computed verdict, never content or raw output.
    for forbidden in ("html_body", "article_html", "raw_output", "prompt", "'reject'"):
        assert forbidden not in sql


def test_qa_report_migration_contains_identity_and_protection() -> None:
    sql = offline_sql("upgrade", "0019:0020")

    assert "CREATE TABLE qa_reports" in sql
    assert "CREATE TABLE qa_gate_waivers" in sql
    assert "CREATE TABLE qa_report_status_events" in sql
    assert "uq_qa_reports_version" in sql
    assert "uq_qa_reports_active" in sql
    assert "ck_qa_reports_outcome" in sql
    assert "ck_qa_reports_hash_format" in sql
    assert "ck_qa_gate_waivers_key" in sql
    assert "ck_qa_gate_waivers_reason_nonempty" in sql
    assert "CREATE TRIGGER trg_qa_reports_guarded" in sql
    assert "CREATE TRIGGER trg_qa_gate_waivers_append_only" in sql
    assert "CREATE TRIGGER trg_qa_report_status_events_append_only" in sql
    assert sql.count("ON DELETE RESTRICT") == 8
    # QA v1 is deterministic and never an approval or a model surface.
    for forbidden in ("'approved'", "'rejected'", "generation_attempt", "prompt", "raw_output"):
        assert forbidden not in sql


def test_auth_migration_contains_identity_and_protection() -> None:
    sql = offline_sql("upgrade", "0020:0021")

    assert "CREATE TABLE users" in sql
    assert "CREATE TABLE user_events" in sql
    assert "CREATE TABLE auth_sessions" in sql
    assert "uq_users_username" in sql
    assert "uq_auth_sessions_token_hash" in sql
    assert "ck_auth_sessions_token_hash_format" in sql
    assert "ck_users_roles_array" in sql
    assert "CREATE TRIGGER trg_users_guarded" in sql
    assert "CREATE TRIGGER trg_user_events_append_only" in sql
    assert "CREATE TRIGGER trg_auth_sessions_guarded" in sql
    # Only hashes are ever stored; no raw secret columns exist.
    for forbidden in ("password VARCHAR", "raw_token", "plain_password", "secret_key"):
        assert forbidden not in sql


def test_human_decision_migration_contains_identity_and_protection() -> None:
    sql = offline_sql("upgrade", "0021:0022")

    assert "CREATE TABLE human_decisions" in sql
    assert "ck_human_decisions_decision" in sql
    assert "ck_human_decisions_hash_format" in sql
    assert "ck_human_decisions_revocation_reference" in sql
    assert "CREATE TRIGGER trg_human_decisions_append_only" in sql
    # The named actor lands additively on workflow events.
    assert "ADD COLUMN actor_user_id" in sql
    assert "ix_editorial_workflow_events_actor_user" in sql
    # A decision is a human event: no machine identity, no status field.
    for forbidden in ("worker_id", "'system'", "status VARCHAR", "superseded"):
        assert forbidden not in sql


def test_media_migration_contains_identity_and_protection() -> None:
    sql = offline_sql("upgrade", "0022:0023")

    assert "CREATE TABLE media_assets" in sql
    assert "uq_media_assets_content" in sql
    assert "ck_media_assets_origin_attempt" in sql
    assert "ck_media_assets_alt_text_nonempty" in sql
    assert "ck_media_assets_license_nonempty" in sql
    assert "CREATE TRIGGER trg_media_assets_append_only" in sql
    assert "CREATE TABLE media_need_satisfactions" in sql
    assert "uq_media_satisfactions_active" in sql
    assert "CREATE TRIGGER trg_media_need_satisfactions_guarded" in sql
    assert "CREATE TABLE media_satisfaction_events" in sql
    assert "CREATE TRIGGER trg_media_satisfaction_events_append_only" in sql
    # Human-only in this phase: no machine actor vocabulary anywhere.
    assert "worker_id" not in sql and "'system'" not in sql


def test_media_image_purpose_migration_widens_and_guards() -> None:
    sql = offline_sql("upgrade", "0023:0024")
    assert "ck_ai_generation_attempts_purpose" in sql
    assert "'media_image'" in sql

    source = (MIGRATIONS_DIR / "versions" / "0024_add_media_image_purpose.py").read_text(
        encoding="utf-8"
    )
    # The downgrade refuses to destroy or invalidate audit history.
    assert "cannot downgrade 0024" in source
    assert "purpose = 'media_image'" in source


def test_publication_migration_contains_identity_and_protection() -> None:
    sql = offline_sql("upgrade", "0024:0025")

    assert "CREATE TABLE publication_packages" in sql
    assert "uq_publication_packages_version" in sql
    assert "uq_publication_packages_content" in sql
    assert "ck_publication_packages_package_hash_format" in sql
    assert "CREATE TRIGGER trg_publication_packages_append_only" in sql
    assert "CREATE TABLE publication_attempts" in sql
    assert "uq_publication_attempts_number" in sql
    assert "ck_publication_attempts_status" in sql
    assert "ck_publication_attempts_remote_ref" in sql
    assert "CREATE TRIGGER trg_publication_attempts_append_only" in sql
    # Execution facts only: no editorial vocabulary in the attempt statuses.
    assert "'rejected'" not in sql and "'approved'" not in sql


def test_session_pruning_migration_keeps_live_sessions_undeletable() -> None:
    sql = offline_sql("upgrade", "0025:0026")
    assert "live auth_sessions rows cannot be deleted" in sql
    assert "auth_sessions permits only the one-shot revocation" in sql

    down = offline_sql("downgrade", "0026:0025")
    assert "auth_sessions rows cannot be deleted" in down


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
