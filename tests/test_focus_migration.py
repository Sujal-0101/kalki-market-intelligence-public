"""Focus persistence is append-only, private, and restore-covered."""

from pathlib import Path

ROOT = Path(__file__).parents[1]
MIGRATION = (ROOT / "migrations/0019_focus_universe.sql").read_text()
COMPOSE = (ROOT / "compose.production.yaml").read_text()
BACKUP = (ROOT / "scripts/backup-postgres.sh").read_text()
RESTORE = (ROOT / "scripts/restore-postgres-gate.sh").read_text()
RUNNER = (ROOT / "scripts/migrate-focus-universe.sh").read_text()


def test_focus_migration_is_closed_append_only_and_restore_covered() -> None:
    for table in (
        "research_focus_universe_state",
        "research_focus_membership_events",
    ):
        assert f"CREATE TABLE {table}" in MIGRATION
        assert table in BACKUP and table in RESTORE
    assert "validate_focus_membership_event" in MIGRATION
    assert "BEFORE UPDATE OR DELETE ON research_focus_membership_events" in MIGRATION
    assert "research_focus_membership_events_supersedes_idx" in MIGRATION
    assert "0019_focus_universe.sql" in COMPOSE
    assert "0019_focus_universe" in RUNNER
    assert "0018_event_novelty_lineage" in RUNNER


def test_focus_application_role_has_no_mutation_or_public_projection() -> None:
    assert "GRANT SELECT, INSERT ON research_focus_membership_events TO kalki_app" in MIGRATION
    assert "UPDATE ON research_focus_membership_events" not in MIGRATION
    assert "GRANT DELETE" not in MIGRATION
    assert "CREATE VIEW" not in MIGRATION
    assert "INSERT INTO research_focus_membership_events" not in MIGRATION
