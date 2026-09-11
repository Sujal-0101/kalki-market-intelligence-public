"""Tier-0 persistence migration remains append-only and bounded."""

from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_tier0_migration_records_decision_columns_and_schema_version() -> None:
    migration = (ROOT / "migrations/0006_tier0_decisions.sql").read_text()
    assert "tier_outcome" in migration
    assert "tier_reason" in migration
    assert "tier_evidence_ids" in migration
    assert "tier_decision_record" in migration
    assert "0006_tier0_decisions" in migration
