"""Engineering measurement persistence is private, append-only, and restore-covered."""

from pathlib import Path

ROOT = Path(__file__).parents[1]
MIGRATION = (ROOT / "migrations/0021_engineering_measurements.sql").read_text()
COMPOSE = (ROOT / "compose.production.yaml").read_text()
BACKUP = (ROOT / "scripts/backup-postgres.sh").read_text()
RESTORE = (ROOT / "scripts/restore-postgres-gate.sh").read_text()
RUNNER = (ROOT / "scripts/migrate-engineering-measurements.sh").read_text()


def test_measurement_migration_is_closed_append_only_and_restore_covered() -> None:
    for table in (
        "research_engineering_measurement_state",
        "research_engineering_metric_definitions",
        "research_engineering_measurements",
        "research_filing_latency_receipts",
    ):
        assert f"CREATE TABLE {table}" in MIGRATION
        assert table in BACKUP and table in RESTORE
    assert "validate_engineering_measurement" in MIGRATION
    assert "validate_filing_latency_receipt" in MIGRATION
    assert "BEFORE UPDATE OR DELETE ON research_engineering_measurements" in MIGRATION
    assert "BEFORE UPDATE OR DELETE ON research_filing_latency_receipts" in MIGRATION
    assert "fields outside the closed contract" in MIGRATION
    assert "0021_engineering_measurements.sql" in COMPOSE
    assert "0021_engineering_measurements" in RUNNER
    assert "0020_validated_sec_links" in RUNNER


def test_measurements_are_private_and_application_cannot_mutate_history() -> None:
    assert (
        "GRANT SELECT, INSERT ON research_engineering_measurements, "
        "research_filing_latency_receipts TO kalki_app" in MIGRATION
    )
    assert "UPDATE ON research_engineering_measurements" not in MIGRATION
    assert "UPDATE ON research_filing_latency_receipts" not in MIGRATION
    assert "GRANT DELETE" not in MIGRATION
    assert "CREATE VIEW" not in MIGRATION
    assert "public" not in " ".join(
        line for line in MIGRATION.splitlines() if line.lstrip().startswith("CREATE VIEW")
    )


def test_metric_catalog_is_seeded_without_observations_or_historical_backfill() -> None:
    assert MIGRATION.count("'1.0.0'") >= 20
    assert "INSERT INTO research_engineering_metric_definitions" in MIGRATION
    assert "INSERT INTO research_engineering_measurements" not in MIGRATION
    assert "INSERT INTO research_filing_latency_receipts" not in MIGRATION
    assert "UPDATE research_candidates" not in MIGRATION
    assert "UPDATE research_briefs" not in MIGRATION
