"""Disposable PostgreSQL gate for immutable Phase 42 lifecycle records."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest

from kalki_market_intelligence.database import DatabaseOptions, DatabaseRuntime
from kalki_market_intelligence.forensics.filing_change import (
    FilingChangeForm,
    FilingChangeRelationship,
    FilingChangeSnapshot,
    compare_and_select_filing_changes,
)
from kalki_market_intelligence.providers.sec.filing_change import (
    build_snapshot_from_filing_change_extraction,
    extract_filing_change_sections,
)
from kalki_market_intelligence.radar.store import PostgresRadarStore

GATE_PASSWORD_FILE = os.environ.get("KALKI_FILING_CHANGE_GATE_PASSWORD_FILE")
GATE_PORT = int(os.environ.get("KALKI_FILING_CHANGE_GATE_PORT", "55448"))
PREVIOUS_AT = datetime(2026, 9, 1, 10, tzinfo=UTC)
CURRENT_AT = datetime(2026, 9, 2, 10, tzinfo=UTC)


def _runtime() -> DatabaseRuntime:
    assert GATE_PASSWORD_FILE is not None
    return DatabaseRuntime(
        DatabaseOptions(
            host="127.0.0.1",
            port=GATE_PORT,
            name="kalki_test",
            user="kalki_app",
            password_file=Path(GATE_PASSWORD_FILE),
            minimum_pool_size=1,
            maximum_pool_size=1,
        )
    )


def _snapshot(
    accession_number: str, *, available_at: datetime, changed: bool
) -> FilingChangeSnapshot:
    narrative = (
        "The issuer reports a revised bounded liquidity risk description tied to this test source. "
        if changed
        else "The issuer reports a bounded liquidity risk description tied to this test source. "
    )
    body = f"<html><h1>RISK FACTORS</h1><p>{narrative * 4}</p></html>".encode()
    extraction = extract_filing_change_sections(body, filing_form=FilingChangeForm.FORM_424_B_5)
    compact = accession_number.replace("-", "")
    return build_snapshot_from_filing_change_extraction(
        extraction,
        accession_number=accession_number,
        cik="1075880",
        filed_at=available_at.replace(hour=0),
        available_at=available_at,
        retrieved_at=available_at + timedelta(minutes=1),
        source_url=(f"https://www.sec.gov/Archives/edgar/data/1075880/{compact}/fixture.htm"),
    )


@pytest.mark.skipif(
    GATE_PASSWORD_FILE is None,
    reason="Filing-change lifecycle PostgreSQL gate is not running",
)
def test_snapshots_and_selection_are_exact_idempotent_private_history() -> None:
    previous = _snapshot("0001213900-26-000001", available_at=PREVIOUS_AT, changed=False)
    current = _snapshot("0001213900-26-000002", available_at=CURRENT_AT, changed=True)
    selection = compare_and_select_filing_changes(
        previous,
        current,
        relationship=FilingChangeRelationship.PROSPECTUS_UPDATE,
    )
    runtime = _runtime()
    runtime.open()
    try:
        store = PostgresRadarStore(runtime.connection)
        tampered = selection.model_copy(
            update={"selected_characters": selection.selected_characters + 1}
        )
        with pytest.raises(ValueError, match="character count"):
            store.append_filing_change_selection(previous, current, tampered)
        store.append_filing_change_selection(previous, current, selection)
        store.append_filing_change_selection(previous, current, selection)
        store.append_filing_change_snapshot(previous)
        assert store.filing_change_snapshots(
            cik="1075880",
            knowledge_cutoff_at=current.available_at,
            exclude_accession_number=current.accession_number,
        ) == (previous,)
        with runtime.connection() as connection:
            snapshot_rows = connection.execute(
                """
                SELECT manifest_sha256, record FROM research_filing_change_snapshots
                ORDER BY available_at
                """
            ).fetchall()
            selection_rows = connection.execute(
                """
                SELECT receipt_id, recorded_at, record
                FROM research_filing_change_selections
                """
            ).fetchall()

        assert [FilingChangeSnapshot.model_validate(row["record"]) for row in snapshot_rows] == [
            previous,
            current,
        ]
        assert len(selection_rows) == 1
        assert selection_rows[0]["receipt_id"] == selection.receipt_id
        assert selection_rows[0]["recorded_at"] == current.retrieved_at
        assert selection_rows[0]["record"] == selection.model_dump(mode="json")
        record_keys = set(selection_rows[0]["record"])
        assert not record_keys & {"prompt", "response", "human_hypothesis", "publication"}
    finally:
        runtime.close()

    with psycopg.connect(
        host="127.0.0.1", port=GATE_PORT, dbname="kalki_test", user="postgres"
    ) as owner:
        with pytest.raises(psycopg.errors.RaiseException):
            owner.execute(
                """
                INSERT INTO research_filing_change_snapshots
                SELECT repeat('b', 64), accession_number, canonical_cik, filing_form,
                       filed_at, available_at, retrieved_at, source_url,
                       source_content_sha256, normalized_visible_sha256, section_count,
                       extraction_version, schema_version, record
                FROM research_filing_change_snapshots LIMIT 1
                """
            )
        owner.rollback()
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            owner.execute("UPDATE research_filing_change_snapshots SET filing_form = filing_form")
        owner.rollback()
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            owner.execute("TRUNCATE research_filing_change_selections")
        owner.rollback()

    with psycopg.connect(
        host="127.0.0.1", port=GATE_PORT, dbname="kalki_test", user="kalki_app"
    ) as application:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            application.execute("DELETE FROM research_filing_change_selections")
