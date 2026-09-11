from pathlib import Path

ROOT = Path(__file__).parents[1]
MIGRATION = (ROOT / "migrations/0027_outcome_science_invariants.sql").read_text()
COMPOSE = (ROOT / "compose.production.yaml").read_text()
RUNNER = (ROOT / "scripts/migrate-outcome-science-invariants.sh").read_text()
GATE = (ROOT / "scripts/test-prospective-outcomes-postgres.sh").read_text()
RESTORE = (ROOT / "scripts/restore-postgres-gate.sh").read_text()
APP = (ROOT / "src/kalki_market_intelligence/web/app.py").read_text()
REPOSITORY = (ROOT / "src/kalki_market_intelligence/web/repository.py").read_text()
TEMPLATE = (ROOT / "src/kalki_market_intelligence/web/templates/admin_operations.html").read_text()


def test_outcome_science_migration_hardens_the_existing_private_ledger() -> None:
    assert "enrolled_at >= published_at" in MIGRATION
    assert "CREATE OR REPLACE FUNCTION validate_prospective_outcome_plan()" in MIGRATION
    assert "CREATE OR REPLACE FUNCTION validate_prospective_outcome_attempt()" in MIGRATION
    assert "CREATE OR REPLACE FUNCTION validate_prospective_outcome_result()" in MIGRATION
    assert "validate_prospective_outcome_bar(" in MIGRATION
    assert "outcome_price_return_decimal34(" in MIGRATION
    assert "outcome_decimal34(" in MIGRATION
    assert "requires a limitation and no return" in MIGRATION
    assert "UPDATE research_" not in MIGRATION
    assert "DELETE FROM research_" not in MIGRATION


def test_outcome_science_migration_is_in_fresh_upgrade_and_restore_paths() -> None:
    assert "0027_outcome_science_invariants.sql" in COMPOSE
    assert "0027_outcome_science_invariants.sql" in RUNNER
    assert "0027_outcome_science_invariants.sql" in GATE
    assert "0027_outcome_science_invariants" in RESTORE


def test_outcome_science_projection_is_private_aggregate_and_non_predictive() -> None:
    assert '"outcome_science": state.repository.get_outcome_science_operations()' in APP
    assert "Prospective outcome science" in TEMPLATE
    assert "not a calibrated probability" in TEMPLATE
    assert "No supporting outcome exists" in TEMPLATE
    assert "PostgresOutcomeScienceRepository" in REPOSITORY
    for forbidden in (
        "publication_id",
        "accession_number",
        "source_document_sha256",
        "source_content_sha256",
        "response_sha256",
        "case_set_sha256",
    ):
        assert forbidden not in TEMPLATE
