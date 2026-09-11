"""Event novelty persistence is append-only, private, and restore-covered."""

from pathlib import Path

ROOT = Path(__file__).parents[1]
MIGRATION = (ROOT / "migrations/0018_event_novelty_lineage.sql").read_text()
COMPOSE = (ROOT / "compose.production.yaml").read_text()
BACKUP = (ROOT / "scripts/backup-postgres.sh").read_text()
RESTORE = (ROOT / "scripts/restore-postgres-gate.sh").read_text()
RUNNER = (ROOT / "scripts/migrate-event-novelty-lineage.sh").read_text()


def test_event_novelty_migration_is_closed_append_only_and_restore_covered() -> None:
    for table in (
        "research_event_novelty_state",
        "research_event_disclosures",
        "research_event_lineage",
    ):
        assert f"CREATE TABLE {table}" in MIGRATION
        assert table in BACKUP and table in RESTORE
    assert "validate_event_disclosure" in MIGRATION
    assert "validate_event_lineage" in MIGRATION
    assert "BEFORE UPDATE OR DELETE ON research_event_disclosures" in MIGRATION
    assert "BEFORE UPDATE OR DELETE ON research_event_lineage" in MIGRATION
    assert "0018_event_novelty_lineage.sql" in COMPOSE
    assert "0018_event_novelty_lineage" in RUNNER
    assert "0017_financing_intelligence" in RUNNER


def test_event_novelty_application_role_has_no_mutation_or_public_path() -> None:
    assert (
        "GRANT SELECT, INSERT ON research_event_disclosures, research_event_lineage TO kalki_app"
        in MIGRATION
    )
    assert "UPDATE ON research_event_disclosures" not in MIGRATION
    assert "UPDATE ON research_event_lineage" not in MIGRATION
    assert "GRANT DELETE" not in MIGRATION
    assert "CREATE VIEW" not in MIGRATION
