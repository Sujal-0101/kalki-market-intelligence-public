from pathlib import Path

ROOT = Path(__file__).parents[1]
MIGRATION = (ROOT / "migrations/0024_stale_analyst_attempt_recovery.sql").read_text()
COMPOSE = (ROOT / "compose.production.yaml").read_text()
RUNNER = (ROOT / "scripts/migrate-stale-analyst-attempt-recovery.sh").read_text()
RESTORE = (ROOT / "scripts/restore-postgres-gate.sh").read_text()


def test_migration_is_forward_only_and_preserves_attempt_history() -> None:
    assert "DROP CONSTRAINT research_analyst_attempts_latency_ms_check" in MIGRATION
    assert "CHECK (latency_ms IS NULL OR latency_ms >= 0)" in MIGRATION
    assert "UPDATE research_analyst_attempts" not in MIGRATION
    assert "DELETE" not in MIGRATION
    assert "0024_stale_analyst_attempt_recovery" in MIGRATION


def test_migration_is_wired_into_fresh_upgrade_and_restore_paths() -> None:
    assert "0024_stale_analyst_attempt_recovery.sql" in COMPOSE
    assert "0024_stale_analyst_attempt_recovery.sql" in RUNNER
    assert "0024_stale_analyst_attempt_recovery" in RESTORE
