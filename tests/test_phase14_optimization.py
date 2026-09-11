"""Reversible database and bounded-query contracts for Phase 14."""

from pathlib import Path

ROOT = Path(__file__).parents[1]
UP = (ROOT / "migrations/0003_publication_list_index.sql").read_text(encoding="utf-8")
DOWN = (ROOT / "migrations/rollback/0003_publication_list_index.sql").read_text(encoding="utf-8")
COMPOSE = (ROOT / "compose.production.yaml").read_text(encoding="utf-8")
RUNNER = (ROOT / "scripts/migrate-postgres.sh").read_text(encoding="utf-8")


def test_publication_index_exactly_matches_bounded_list_order() -> None:
    assert "ON predictions (published_at DESC, prediction_id DESC)" in UP
    assert "0003_publication_list_index" in UP
    assert "0003_publication_list_index.sql" in COMPOSE


def test_index_has_an_explicit_transactional_rollback() -> None:
    assert UP.startswith("BEGIN;") and UP.rstrip().endswith("COMMIT;")
    assert DOWN.startswith("BEGIN;") and DOWN.rstrip().endswith("COMMIT;")
    assert "DROP INDEX predictions_publication_order_idx" in DOWN
    assert "DELETE FROM schema_migrations" in DOWN


def test_live_runner_is_idempotent_and_stops_on_database_errors() -> None:
    assert "set -eu" in RUNNER
    assert "ON_ERROR_STOP=1" in RUNNER
    assert "SELECT EXISTS" in RUNNER
    assert "up|down" in RUNNER
