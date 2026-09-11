"""Phase 40 financing persistence is append-only, bounded, and private."""

from pathlib import Path

ROOT = Path(__file__).parents[1]
MIGRATION = (ROOT / "migrations/0017_financing_intelligence.sql").read_text()
COMPOSE = (ROOT / "compose.production.yaml").read_text()
BACKUP = (ROOT / "scripts/backup-postgres.sh").read_text()
RESTORE = (ROOT / "scripts/restore-postgres-gate.sh").read_text()
RUNNER = (ROOT / "scripts/migrate-financing-intelligence.sh").read_text()
TEMPLATE = (ROOT / "src/kalki_market_intelligence/web/templates/admin_operations.html").read_text()


def test_financing_migration_adds_closed_receipt_and_routing_ledgers() -> None:
    for table in (
        "research_financing_jobs",
        "research_financing_receipts",
        "research_financing_routing_receipts",
        "research_financing_state",
    ):
        assert f"CREATE TABLE {table}" in MIGRATION
        assert table in BACKUP and table in RESTORE
    assert "validate_financing_receipt" in MIGRATION
    assert "validate_financing_routing_receipt" in MIGRATION
    assert "0017_financing_intelligence.sql" in COMPOSE
    assert "0017_financing_intelligence" in RUNNER
    assert "0016_ownership_index_identity" in RUNNER


def test_financing_ledgers_and_terminal_jobs_are_immutable() -> None:
    assert "BEFORE UPDATE OR DELETE ON research_financing_receipts" in MIGRATION
    assert "BEFORE TRUNCATE ON research_financing_receipts" in MIGRATION
    assert "BEFORE UPDATE OR DELETE ON research_financing_routing_receipts" in MIGRATION
    assert "terminal financing jobs are immutable" in MIGRATION
    assert "completed financing job requires its immutable receipt pair" in MIGRATION
    assert "no-terms financing job cannot have an intelligence receipt" in MIGRATION


def test_application_role_cannot_mutate_financing_receipts() -> None:
    assert (
        "GRANT SELECT, INSERT ON research_financing_receipts,\n"
        "            research_financing_routing_receipts, research_financing_jobs TO kalki_app"
    ) in MIGRATION
    assert "UPDATE ON research_financing_receipts" not in MIGRATION
    assert "UPDATE ON research_financing_routing_receipts" not in MIGRATION
    assert "GRANT DELETE" not in MIGRATION


def test_financing_worker_is_private_bounded_and_model_free() -> None:
    block = COMPOSE.split("  financing-worker:", 1)[1].split("  prospective-outcomes:", 1)[0]
    assert "command: [kalki-financing-worker]" in block
    assert 'KALKI_FINANCING_WORKER_BATCH_SIZE: "2"' in block
    assert 'KALKI_FINANCING_WORKER_MAXIMUM_BACKLOG: "250"' in block
    assert "- database" in block and "- research_egress" in block
    assert "analyst" not in block
    assert "public_connector" not in block
    assert "discord" not in block.casefold()
    assert "ports:" not in block
    assert "Financing and dilution processing" in TEMPLATE
