"""Phase 41 accounting persistence is append-only, bounded, and private."""

from pathlib import Path

ROOT = Path(__file__).parents[1]
MIGRATION = (ROOT / "migrations/0022_accounting_compliance.sql").read_text()
COMPOSE = (ROOT / "compose.production.yaml").read_text()
BACKUP = (ROOT / "scripts/backup-postgres.sh").read_text()
RESTORE = (ROOT / "scripts/restore-postgres-gate.sh").read_text()
RUNNER = (ROOT / "scripts/migrate-accounting-compliance.sh").read_text()
TEMPLATE = (ROOT / "src/kalki_market_intelligence/web/templates/admin_operations.html").read_text()


def test_accounting_migration_adds_closed_receipt_and_routing_ledgers() -> None:
    for table in (
        "research_accounting_jobs",
        "research_accounting_receipts",
        "research_accounting_routing_receipts",
        "research_accounting_state",
    ):
        assert f"CREATE TABLE {table}" in MIGRATION
        assert table in BACKUP and table in RESTORE
    assert "validate_accounting_receipt" in MIGRATION
    assert "validate_accounting_routing_receipt" in MIGRATION
    assert "0022_accounting_compliance.sql" in COMPOSE
    assert "0022_accounting_compliance" in RUNNER
    assert "0021_engineering_measurements" in RUNNER


def test_accounting_ledgers_and_terminal_jobs_are_immutable() -> None:
    assert "BEFORE UPDATE OR DELETE ON research_accounting_receipts" in MIGRATION
    assert "BEFORE TRUNCATE ON research_accounting_receipts" in MIGRATION
    assert "BEFORE UPDATE OR DELETE ON research_accounting_routing_receipts" in MIGRATION
    assert "terminal accounting jobs are immutable" in MIGRATION
    assert "completed accounting job requires its immutable receipt pair" in MIGRATION
    assert "no-events accounting job cannot have an intelligence receipt" in MIGRATION


def test_application_role_cannot_mutate_accounting_receipts() -> None:
    assert "UPDATE ON research_accounting_receipts" not in MIGRATION
    assert "UPDATE ON research_accounting_routing_receipts" not in MIGRATION
    assert "GRANT DELETE" not in MIGRATION


def test_accounting_worker_is_private_bounded_and_model_free() -> None:
    block = COMPOSE.split("  accounting-worker:", 1)[1].split("  prospective-outcomes:", 1)[0]
    assert "command: [kalki-accounting-worker]" in block
    assert 'KALKI_ACCOUNTING_WORKER_BATCH_SIZE: "2"' in block
    assert 'KALKI_ACCOUNTING_WORKER_MAXIMUM_BACKLOG: "250"' in block
    assert "- database" in block and "- research_egress" in block
    assert "analyst" not in block
    assert "public_connector" not in block
    assert "discord" not in block.casefold()
    assert "ports:" not in block
    assert "Accounting, auditor and compliance processing" in TEMPLATE
