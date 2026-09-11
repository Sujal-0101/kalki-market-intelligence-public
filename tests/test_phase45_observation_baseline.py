from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_GATE = (ROOT / "scripts/test-observation-baseline-v2.sh").read_text()


def test_phase45_gate_covers_static_compose_and_dedicated_database_boundaries() -> None:
    for command in (
        '"$venv_bin/pytest" -q',
        '"$venv_bin/ruff" format --check',
        '"$venv_bin/ruff" check',
        '"$venv_bin/mypy" --strict',
        '"$venv_bin/python" -m pip check',
        "--profile supporting-outcomes config --quiet",
        "compose.cloudflare.yaml",
    ):
        assert command in BASELINE_GATE

    for gate in (
        "test-analyst-attempt-postgres.sh",
        "test-hierarchical-verifier-postgres.sh",
        "test-funnel-telemetry-postgres.sh",
        "test-autonomous-screening-postgres.sh",
        "test-validated-sec-links-postgres.sh",
        "test-event-novelty-postgres.sh",
        "test-focus-universe-postgres.sh",
        "test-engineering-measurements-postgres.sh",
        "test-ownership-postgres.sh",
        "test-financing-postgres.sh",
        "test-accounting-postgres.sh",
        "test-analyst-attempt-recovery-postgres.sh",
        "test-filing-change-lifecycle-postgres.sh",
        "test-contradiction-postgres.sh",
        "test-prospective-outcomes-postgres.sh",
    ):
        assert gate in BASELINE_GATE


def test_legacy_disposable_gates_wait_for_the_requested_database() -> None:
    for name in (
        "test-analyst-attempt-postgres.sh",
        "test-autonomous-screening-postgres.sh",
        "test-hierarchical-verifier-postgres.sh",
        "test-validated-sec-links-postgres.sh",
    ):
        script = (ROOT / "scripts" / name).read_text()
        readiness = script.split('command "CREATE ROLE', maxsplit=1)[0]
        assert "psql --no-psqlrc --username kalki_owner --dbname kalki" in readiness
        assert '--command "SELECT 1"' in readiness
        assert "pg_isready" not in readiness


def test_filing_change_upgrade_gate_stops_at_its_required_prior_schema() -> None:
    script = (ROOT / "scripts/test-filing-change-lifecycle-postgres.sh").read_text()
    pre_upgrade = script.split("latest_version=", maxsplit=1)[0]
    assert "migrations/002[0-4]_*.sql" in pre_upgrade
    assert "migrations/0025_filing_change_lifecycle.sql" not in pre_upgrade
    assert "00[012][0-9]" not in pre_upgrade


def test_contradiction_upgrade_gate_stops_at_its_required_prior_schema() -> None:
    script = (ROOT / "scripts/test-contradiction-postgres.sh").read_text()
    pre_upgrade = script.split("latest_version=", maxsplit=1)[0]
    assert "migrations/002[0-5]_*.sql" in pre_upgrade
    assert "migrations/0026_contradiction_receipts.sql" not in pre_upgrade
    assert "00[012][0-9]" not in pre_upgrade
