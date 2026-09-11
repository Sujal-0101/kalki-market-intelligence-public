"""Phase 39 ownership persistence migration remains append-only and bounded."""

from pathlib import Path

ROOT = Path(__file__).parents[1]
MIGRATION = (ROOT / "migrations/0015_ownership_intelligence.sql").read_text()
IDENTITY_MIGRATION = (ROOT / "migrations/0016_ownership_index_identity.sql").read_text()
COMPOSE = (ROOT / "compose.production.yaml").read_text()
BACKUP = (ROOT / "scripts/backup-postgres.sh").read_text()
RESTORE = (ROOT / "scripts/restore-postgres-gate.sh").read_text()
RUNNER = (ROOT / "scripts/migrate-ownership-intelligence.sh").read_text()
IDENTITY_RUNNER = (ROOT / "scripts/migrate-ownership-index-identity.sh").read_text()
TEMPLATE = (ROOT / "src/kalki_market_intelligence/web/templates/admin_operations.html").read_text()


def test_ownership_migration_adds_closed_receipt_and_routing_ledgers() -> None:
    assert "CREATE TABLE research_ownership_jobs" in MIGRATION
    assert "CREATE TABLE research_ownership_receipts" in MIGRATION
    assert "CREATE TABLE research_ownership_routing_receipts" in MIGRATION
    assert "validate_ownership_receipt" in MIGRATION
    assert "validate_ownership_routing_receipt" in MIGRATION
    assert "0015_ownership_intelligence" in MIGRATION
    assert "0015_ownership_intelligence.sql" in COMPOSE
    assert "0016_ownership_index_identity.sql" in COMPOSE
    assert "index_ciks" in IDENTITY_MIGRATION
    assert "resolved_issuer_cik" in IDENTITY_MIGRATION


def test_ownership_ledgers_reject_update_delete_and_truncate() -> None:
    assert "BEFORE UPDATE OR DELETE ON research_ownership_receipts" in MIGRATION
    assert "BEFORE TRUNCATE ON research_ownership_receipts" in MIGRATION
    assert "BEFORE UPDATE OR DELETE ON research_ownership_routing_receipts" in MIGRATION
    assert "BEFORE TRUNCATE ON research_ownership_routing_receipts" in MIGRATION
    assert "protect_ownership_job_lifecycle" in MIGRATION
    assert "terminal ownership jobs are immutable" in MIGRATION
    assert "completed ownership job requires its immutable receipt pair" in MIGRATION


def test_application_role_has_no_mutation_privilege() -> None:
    assert (
        "GRANT SELECT, INSERT ON research_ownership_receipts,\n"
        "            research_ownership_routing_receipts, research_ownership_jobs TO kalki_app"
    ) in MIGRATION
    assert ") ON research_ownership_jobs TO kalki_app" in MIGRATION
    assert "UPDATE ON research_ownership_receipts" not in MIGRATION
    assert "UPDATE ON research_ownership_routing_receipts" not in MIGRATION
    assert "GRANT DELETE" not in MIGRATION


def test_ownership_history_is_in_backup_restore_and_guarded_runner() -> None:
    for table in (
        "research_ownership_jobs",
        "research_ownership_receipts",
        "research_ownership_routing_receipts",
        "research_ownership_state",
    ):
        assert table in BACKUP
        assert table in RESTORE
    assert "0015_ownership_intelligence" in RESTORE
    assert "0016_ownership_index_identity" in RESTORE
    assert "0014_prospective_outcomes" in RUNNER
    assert "0015_ownership_intelligence" in RUNNER
    assert "0015_ownership_intelligence" in IDENTITY_RUNNER
    assert "0016_ownership_index_identity" in IDENTITY_RUNNER
    assert "Insider and ownership processing" in TEMPLATE
