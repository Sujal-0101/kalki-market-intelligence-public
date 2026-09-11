from pathlib import Path

ROOT = Path(__file__).parents[1]
MIGRATION = (ROOT / "migrations/0025_filing_change_lifecycle.sql").read_text()
COMPOSE = (ROOT / "compose.production.yaml").read_text()
RUNNER = (ROOT / "scripts/migrate-filing-change-lifecycle.sh").read_text()
RESTORE = (ROOT / "scripts/restore-postgres-gate.sh").read_text()


def test_lifecycle_tables_are_private_append_only_and_source_bound() -> None:
    assert "CREATE TABLE research_filing_change_snapshots" in MIGRATION
    assert "CREATE TABLE research_filing_change_selections" in MIGRATION
    assert MIGRATION.count("reject_append_only_mutation()") == 4
    assert "validate_filing_change_snapshot()" in MIGRATION
    assert "validate_filing_change_selection()" in MIGRATION
    assert "GRANT SELECT, INSERT" in MIGRATION
    assert "GRANT UPDATE" not in MIGRATION
    assert "GRANT DELETE" not in MIGRATION
    assert "UPDATE research_" not in MIGRATION


def test_lifecycle_migration_is_wired_into_fresh_upgrade_and_restore_paths() -> None:
    assert "0025_filing_change_lifecycle.sql" in COMPOSE
    assert "0025_filing_change_lifecycle.sql" in RUNNER
    assert "0025_filing_change_lifecycle" in RESTORE
