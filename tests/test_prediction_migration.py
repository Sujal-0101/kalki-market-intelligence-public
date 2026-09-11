"""Static safety checks for the PostgreSQL prediction migration."""

from pathlib import Path

ROOT = Path(__file__).parents[1]
MIGRATION = (ROOT / "migrations/0001_prediction_outcomes.sql").read_text(encoding="utf-8")
WEB_MIGRATION = (ROOT / "migrations/0002_web_operations.sql").read_text(encoding="utf-8")
RADAR_MIGRATION = (ROOT / "migrations/0004_live_research_radar.sql").read_text(encoding="utf-8")
VERIFIER_MIGRATION = (ROOT / "migrations/0005_hierarchical_verifier.sql").read_text(
    encoding="utf-8"
)
COMPOSE = (ROOT / "compose.yaml").read_text(encoding="utf-8")


def test_migration_protects_every_append_only_table() -> None:
    assert "CREATE TABLE predictions" in MIGRATION
    assert "CREATE TABLE prediction_corrections" in MIGRATION
    assert "CREATE TABLE prediction_outcomes" in MIGRATION
    assert MIGRATION.count("BEFORE UPDATE OR DELETE") == 3
    assert MIGRATION.count("BEFORE TRUNCATE") == 3
    assert "reject_append_only_mutation" in MIGRATION


def test_migration_retains_inconvenient_security_statuses_and_time_checks() -> None:
    for status in ("delisted", "acquired", "bankrupt", "renamed", "data_unavailable"):
        assert f"'{status}'" in MIGRATION
    assert "published_at >= knowledge_cutoff_at" in MIGRATION
    assert "knowledge_cutoff_at >= evaluated_at" in MIGRATION
    assert "evaluation_due_on = as_of_date + horizon_days" in MIGRATION


def test_integration_database_is_ephemeral_and_not_exposed() -> None:
    assert "network_mode: none" in COMPOSE
    assert "tmpfs:" in COMPOSE
    assert "ports:" not in COMPOSE
    assert "postgres:18.0-alpine3.22" in COMPOSE


def test_web_operational_migration_separates_mutable_and_append_only_state() -> None:
    assert "CREATE TABLE web_admin_sessions" in WEB_MIGRATION
    assert "CREATE TABLE web_security_audit_events" in WEB_MIGRATION
    assert "CREATE TABLE web_login_attempts" in WEB_MIGRATION
    assert "CREATE TABLE web_request_events" in WEB_MIGRATION
    assert "web_security_audit_no_update_delete" in WEB_MIGRATION
    assert "web_admin_sessions_no_update_delete" not in WEB_MIGRATION
    assert "INSERT INTO schema_migrations (version) VALUES ('0002_web_operations')" in (
        WEB_MIGRATION
    )


def test_live_radar_migration_separates_jobs_from_immutable_publications() -> None:
    assert "CREATE TABLE research_candidates" in RADAR_MIGRATION
    assert "CREATE TABLE research_briefs" in RADAR_MIGRATION
    assert "CREATE TABLE research_worker_status" in RADAR_MIGRATION
    assert "CREATE TABLE research_notification_deliveries" in RADAR_MIGRATION
    assert "research_briefs_no_update_delete" in RADAR_MIGRATION
    assert "research_notification_deliveries_no_update_delete" in RADAR_MIGRATION
    assert "research_candidates_no_update_delete" not in RADAR_MIGRATION
    assert "0004_live_research_radar" in RADAR_MIGRATION


def test_verifier_migration_makes_semantic_lineage_append_only_and_required() -> None:
    assert "CREATE TABLE research_verifier_reviews" in VERIFIER_MIGRATION
    assert "CREATE TABLE research_verification_retries" in VERIFIER_MIGRATION
    assert "CREATE TABLE research_verification_dispositions" in VERIFIER_MIGRATION
    assert VERIFIER_MIGRATION.count("BEFORE UPDATE OR DELETE") == 3
    assert VERIFIER_MIGRATION.count("BEFORE TRUNCATE") == 3
    assert "research_briefs_require_verification" in VERIFIER_MIGRATION
    assert "d.disposition = 'approved'" in VERIFIER_MIGRATION
