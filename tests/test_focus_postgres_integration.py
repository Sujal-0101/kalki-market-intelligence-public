"""Disposable PostgreSQL gate for Focus history and fair one-queue claims."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import psycopg
import pytest

from kalki_market_intelligence.database import DatabaseOptions, DatabaseRuntime
from kalki_market_intelligence.radar.contracts import FilingCandidate
from kalki_market_intelligence.radar.focus import (
    FocusMembershipAction,
    FocusMembershipEvent,
    FocusMembershipReason,
)
from kalki_market_intelligence.radar.store import (
    FocusMembershipReplayConflict,
    PostgresRadarStore,
)

GATE_PASSWORD_FILE = os.environ.get("KALKI_FOCUS_GATE_PASSWORD_FILE")
GATE_PORT = int(os.environ.get("KALKI_FOCUS_GATE_PORT", "55447"))
NOW = datetime(2026, 8, 30, 18, tzinfo=UTC)


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


def _membership(*, event_id: UUID, cik: str, recorded_at: datetime) -> FocusMembershipEvent:
    return FocusMembershipEvent(
        event_id=event_id,
        canonical_cik=cik,
        ticker="TEST",
        company_name=f"Synthetic Focus Issuer {cik}",
        action=FocusMembershipAction.ADDED,
        reason=FocusMembershipReason.CURATED_REVIEW,
        effective_at=recorded_at - timedelta(days=1),
        recorded_at=recorded_at,
        universe_version="TEST-2026.08",
    )


def _candidate(accession: str, cik: str, age: timedelta) -> FilingCandidate:
    return FilingCandidate(
        accession_number=accession,
        cik=cik,
        company_name=f"Synthetic Queue Issuer {cik}",
        ticker=None,
        exchange=None,
        filing_form="8-K",
        filed_at=NOW - age,
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/"
            f"{int(cik)}/{accession.replace('-', '')}/{accession}.txt"
        ),
        discovered_at=NOW - age,
    )


@pytest.mark.skipif(GATE_PASSWORD_FILE is None, reason="Focus PostgreSQL gate is not running")
def test_membership_replay_point_in_time_removal_and_immutability() -> None:
    add = _membership(
        event_id=UUID("30000000-0000-4000-8000-000000000001"),
        cik="0000003001",
        recorded_at=NOW - timedelta(hours=2),
    )
    removal = add.model_copy(
        update={
            "event_id": UUID("30000000-0000-4000-8000-000000000002"),
            "action": FocusMembershipAction.REMOVED,
            "effective_at": NOW - timedelta(hours=1),
            "recorded_at": NOW - timedelta(hours=1),
            "supersedes_event_id": add.event_id,
        }
    )
    runtime = _runtime()
    runtime.open()
    try:
        store = PostgresRadarStore(runtime.connection)
        store.append_focus_membership_event(add)
        store.append_focus_membership_event(add)
        assert store.focus_universe(as_of=add.recorded_at - timedelta(seconds=1)).members == ()
        assert tuple(
            member.canonical_cik for member in store.focus_universe(as_of=add.recorded_at).members
        ) == (add.canonical_cik,)
        with pytest.raises(FocusMembershipReplayConflict):
            store.append_focus_membership_event(
                add.model_copy(update={"company_name": "Synthetic replay conflict"})
            )
        store.append_focus_membership_event(removal)
        assert store.focus_universe(as_of=NOW).members == ()
    finally:
        runtime.close()

    with psycopg.connect(
        host="127.0.0.1", port=GATE_PORT, dbname="kalki_test", user="postgres"
    ) as owner:
        assert owner.execute(
            "SELECT count(*) FROM research_focus_membership_events"
        ).fetchone() == (2,)
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            owner.execute(
                "UPDATE research_focus_membership_events SET canonical_cik = canonical_cik"
            )
        owner.rollback()
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            owner.execute("TRUNCATE research_focus_membership_events")


@pytest.mark.skipif(GATE_PASSWORD_FILE is None, reason="Focus PostgreSQL gate is not running")
def test_claim_uses_focus_material_bands_and_aged_fairness_in_one_queue() -> None:
    focus_cik = "0000004001"
    runtime = _runtime()
    runtime.open()
    try:
        store = PostgresRadarStore(runtime.connection)
        store.append_focus_membership_event(
            _membership(
                event_id=UUID("40000000-0000-4000-8000-000000000001"),
                cik=focus_cik,
                recorded_at=NOW - timedelta(days=2),
            )
        )
        candidates = (
            _candidate("0000004002-26-000001", "4002", timedelta(hours=26)),
            _candidate("0000004001-26-000002", "4001", timedelta(hours=1)),
            _candidate("0000004003-26-000003", "4003", timedelta(hours=1)),
            _candidate("0000004001-26-000004", "4001", timedelta(minutes=30)),
            _candidate("0000004004-26-000005", "4004", timedelta(minutes=30)),
        )
        assert store.discover(candidates) == 5
        with psycopg.connect(
            host="127.0.0.1", port=GATE_PORT, dbname="kalki_test", user="postgres"
        ) as owner:
            owner.execute(
                """
                UPDATE research_candidates SET tier_outcome = 'escalate'
                WHERE accession_number IN (
                    '0000004001-26-000002', '0000004003-26-000003'
                )
                """
            )
        claimed = tuple(store.claim(now=NOW) for _ in candidates)
        assert tuple(item.candidate.accession_number for item in claimed if item) == (
            "0000004002-26-000001",
            "0000004001-26-000002",
            "0000004003-26-000003",
            "0000004001-26-000004",
            "0000004004-26-000005",
        )
    finally:
        runtime.close()


@pytest.mark.skipif(GATE_PASSWORD_FILE is None, reason="Focus PostgreSQL gate is not running")
def test_application_role_cannot_rewrite_focus_history() -> None:
    with psycopg.connect(
        host="127.0.0.1", port=GATE_PORT, dbname="kalki_test", user="kalki_app"
    ) as application:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            application.execute("UPDATE research_focus_membership_events SET reason = reason")
