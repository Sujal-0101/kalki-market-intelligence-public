"""Static safety checks for the human research-lead migration."""

from pathlib import Path

ROOT = Path(__file__).parents[1]
MIGRATION = (ROOT / "migrations/0007_human_research_leads.sql").read_text(encoding="utf-8")
COMPOSE = (ROOT / "compose.production.yaml").read_text(encoding="utf-8")


def test_human_lead_migration_is_bounded_and_auditable() -> None:
    assert "CREATE TABLE research_human_leads" in MIGRATION
    assert "CREATE TABLE research_human_lead_events" in MIGRATION
    assert "original_submission_sha256" in MIGRATION
    assert "dedupe_key" in MIGRATION
    assert "cardinality(urls) <= 8" in MIGRATION
    assert "research_human_lead_events_no_update_delete" in MIGRATION
    assert "research_human_lead_events_no_truncate" in MIGRATION
    assert "0007_human_research_leads" in MIGRATION


def test_production_compose_mounts_human_lead_migration_read_only() -> None:
    assert "0007_human_research_leads.sql" in COMPOSE
    assert ":ro" in COMPOSE.split("0007_human_research_leads.sql", 1)[1].splitlines()[0]
