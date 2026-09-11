from pathlib import Path

ROOT = Path(__file__).parents[1]
MIGRATION = (ROOT / "migrations/0026_contradiction_receipts.sql").read_text()
APP = (ROOT / "src/kalki_market_intelligence/web/app.py").read_text()
REPOSITORY = (ROOT / "src/kalki_market_intelligence/web/repository.py").read_text()
TEMPLATE = (ROOT / "src/kalki_market_intelligence/web/templates/admin_operations.html").read_text()
COMPOSE = (ROOT / "compose.production.yaml").read_text()
RUNNER = (ROOT / "scripts/migrate-contradiction-receipts.sh").read_text()
GATE = (ROOT / "scripts/test-contradiction-postgres.sh").read_text()
BACKUP = (ROOT / "scripts/backup-postgres.sh").read_text()
RESTORE = (ROOT / "scripts/restore-postgres-gate.sh").read_text()


def test_contradiction_receipts_are_private_append_only_and_closed() -> None:
    assert "CREATE TABLE research_contradiction_receipts" in MIGRATION
    assert "validate_contradiction_receipt()" in MIGRATION
    assert "BEFORE UPDATE OR DELETE ON research_contradiction_receipts" in MIGRATION
    assert "BEFORE TRUNCATE ON research_contradiction_receipts" in MIGRATION
    assert "GRANT SELECT, INSERT ON research_contradiction_receipts" in MIGRATION
    assert "GRANT UPDATE" not in MIGRATION
    assert "GRANT DELETE" not in MIGRATION
    assert "UPDATE research_" not in MIGRATION
    assert "knowledge_cutoff_at >= claim_retrieved_at" in MIGRATION
    assert "fact->>'retrieved_at'" in MIGRATION


def test_contradiction_migration_is_in_fresh_upgrade_backup_and_restore_paths() -> None:
    assert "0026_contradiction_receipts.sql" in COMPOSE
    assert "0026_contradiction_receipts.sql" in RUNNER
    assert "0026_contradiction_receipts.sql" in GATE
    assert "research_contradiction_receipts" in BACKUP
    assert "research_contradiction_receipts" in RESTORE
    assert "research_filing_change_snapshots" in BACKUP
    assert "research_filing_change_snapshots" in RESTORE
    assert "0026_contradiction_receipts" in RESTORE


def test_contradiction_projection_is_private_and_aggregate_only() -> None:
    assert '"convergence": state.repository.get_convergence_operations()' in APP
    assert "Deterministic convergence receipts" in TEMPLATE
    assert "receipt content" in TEMPLATE
    assert "SELECT family AS name, count(*) AS count" in REPOSITORY
    assert "SELECT disposition AS name, count(*) AS count" in REPOSITORY
    assert "GROUP BY source ORDER BY source" in REPOSITORY
    for forbidden in (
        "canonical_cik",
        "comparison_scope_id",
        "evidence_ids",
        "receipt_sha256",
        "source_content_sha256",
    ):
        assert forbidden not in TEMPLATE
