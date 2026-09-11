"""Static safety checks for durable analyst-attempt persistence."""

from pathlib import Path

ROOT = Path(__file__).parents[1]
MIGRATION = (ROOT / "migrations/0010_analyst_attempt_receipts.sql").read_text()
COMPOSE = (ROOT / "compose.production.yaml").read_text()
BACKUP = (ROOT / "scripts/backup-postgres.sh").read_text()
RESTORE = (ROOT / "scripts/restore-postgres-gate.sh").read_text()
REPORT = (ROOT / "scripts/report-analyst-attempts.sh").read_text()


def test_attempt_migration_is_bounded_private_and_completion_only() -> None:
    assert "CREATE TABLE research_analyst_attempts" in MIGRATION
    assert "protect_analyst_attempt_completion" in MIGRATION
    assert "research_analyst_attempts_no_delete" in MIGRATION
    assert "research_analyst_attempts_no_truncate" in MIGRATION
    assert "UNIQUE (invocation_id, attempt_number)" in MIGRATION
    assert "response_sha256" in MIGRATION
    assert "prompt" not in " ".join(
        line.strip() for line in MIGRATION.splitlines() if line.strip().startswith("response_")
    )
    for category in (
        "malformed_json",
        "extra_prose",
        "missing_required_field",
        "invalid_type",
        "invalid_enum",
        "invalid_evidence_id",
        "unsupported_claim",
        "numeric_conflict",
        "provenance_failure",
        "timeout",
        "refusal",
        "provider_error",
        "other",
    ):
        assert category in MIGRATION


def test_fresh_init_and_recovery_manifests_include_attempt_receipts() -> None:
    assert "0006_tier0_decisions.sql" in COMPOSE
    assert "0010_analyst_attempt_receipts.sql" in COMPOSE
    assert "research_analyst_attempts" in BACKUP
    assert "research_analyst_attempts" in RESTORE
    assert "0009_human_research_results" in RESTORE
    assert "0010_analyst_attempt_receipts" in RESTORE


def test_attempt_report_is_aggregate_only_and_labels_small_samples() -> None:
    assert "latency_sample_label" in REPORT
    assert "small_n" in REPORT
    assert "pipeline_retry_successes" in REPORT
    assert "work_item_retry_successes" in REPORT
    assert "failure_categories" in REPORT
    assert "record" not in REPORT
    assert "hypothesis" not in REPORT
    assert "response content" not in REPORT.casefold()
