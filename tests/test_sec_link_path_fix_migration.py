"""The SEC complete-submission path repair remains narrow and forward-only."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (ROOT / "migrations/0023_sec_complete_submission_paths.sql").read_text()
COMPOSE = (ROOT / "compose.production.yaml").read_text()
RUNNER = (ROOT / "scripts/migrate-sec-complete-submission-paths.sh").read_text()
RESTORE = (ROOT / "scripts/restore-postgres-gate.sh").read_text()


def test_forward_fix_accepts_only_exact_flat_or_nested_sec_paths() -> None:
    assert "expected_flat_complete" in MIGRATION
    assert "expected_nested_complete" in MIGRATION
    assert "NEW.complete_submission_url NOT IN" in MIGRATION
    assert "candidate_url IS DISTINCT FROM NEW.complete_submission_url" in MIGRATION
    assert "CREATE OR REPLACE FUNCTION validate_sec_link_receipt()" in MIGRATION
    assert "UPDATE research_candidates" not in MIGRATION
    assert "UPDATE research_sec_link_receipts" not in MIGRATION
    assert "0023_sec_complete_submission_paths" in MIGRATION


def test_fresh_database_and_guarded_runner_include_the_fix() -> None:
    assert "0023_sec_complete_submission_paths.sql" in COMPOSE
    assert "0023_sec_complete_submission_paths.sql" in RUNNER
    assert "0022_accounting_compliance" in RUNNER
    assert "0023_sec_complete_submission_paths" in RESTORE
    assert "No candidate, link receipt, publication, or history was rewritten" in RUNNER
