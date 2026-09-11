"""Disposable PostgreSQL gate for immutable event novelty lineage."""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import psycopg
import pytest

from kalki_market_intelligence.contracts.evidence import SourceClass
from kalki_market_intelligence.database import DatabaseOptions, DatabaseRuntime
from kalki_market_intelligence.forensics.novelty import (
    EventDisclosure,
    EventNoveltyDisposition,
    EventSourceReceipt,
    classify_event_novelty,
    extract_strategic_partnership_disclosure,
)
from kalki_market_intelligence.radar.contracts import FilingCandidate
from kalki_market_intelligence.radar.store import (
    EventNoveltyReplayConflict,
    PostgresRadarStore,
)

GATE_PASSWORD_FILE = os.environ.get("KALKI_NOVELTY_GATE_PASSWORD_FILE")
GATE_PORT = int(os.environ.get("KALKI_NOVELTY_GATE_PORT", "55446"))
NOW = datetime(2026, 8, 30, 10, tzinfo=UTC)
FIXTURES = Path(__file__).parent / "fixtures" / "novelty"


def _fixture(name: str) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads((FIXTURES / name).read_text(encoding="utf-8")),
    )


def _disclosure(name: str) -> EventDisclosure:
    fixture = _fixture(name)
    source = EventSourceReceipt(
        source_class=SourceClass(fixture["source_class"]),
        publisher=fixture["publisher"],
        canonical_url=fixture["canonical_url"],
        accession_number=fixture.get("accession_number"),
        source_content_sha256=fixture["source_content_sha256"],
        published_at=fixture["published_at"],
        available_at=fixture["available_at"],
        retrieved_at=fixture["retrieved_at"],
    )
    result = extract_strategic_partnership_disclosure(
        issuer_cik=fixture["issuer_cik"],
        issuer_name=fixture["issuer_name"],
        text=fixture["excerpt"],
        source=source,
        supported_event_dates=tuple(
            date.fromisoformat(item) for item in fixture["supported_event_dates"]
        ),
    )
    assert result is not None
    return result


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


@pytest.mark.skipif(
    GATE_PASSWORD_FILE is None,
    reason="Event novelty PostgreSQL gate is not running",
)
def test_synthetic_recap_is_idempotent_reconciled_and_append_only() -> None:
    original = _disclosure("synthetic-original-partnership.json")
    current = _disclosure("synthetic-later-partnership-recap.json")
    runtime = _runtime()
    runtime.open()
    try:
        store = PostgresRadarStore(runtime.connection)
        store.append_event_disclosure(original)
        store.discover(
            (
                FilingCandidate(
                    accession_number="0000000001-26-000001",
                    cik="0000000001",
                    company_name="Example Compute Corp",
                    ticker="EXMPL",
                    exchange="Nasdaq",
                    filing_form="8-K",
                    filed_at=datetime(2026, 8, 26, tzinfo=UTC),
                    source_url=(
                        "https://www.sec.gov/Archives/edgar/data/1/"
                        "000000000126000001/0000000001-26-000001.txt"
                    ),
                    discovered_at=datetime(2026, 8, 27, tzinfo=UTC),
                ),
            )
        )
        priors = store.event_disclosures(
            issuer_cik=current.issuer_cik,
            category=current.category,
            exclude_source_content_sha256=current.source.source_content_sha256,
        )
        assert priors == (original,)
        receipt = classify_event_novelty(
            current,
            prior_disclosures=priors,
            prior_search_complete=True,
            evaluated_at=NOW,
        )
        assert receipt.disposition is EventNoveltyDisposition.RECAP_EXISTING_EVENT
        assert store.append_event_lineage(receipt) == receipt
        assert store.append_event_lineage(receipt) == receipt
        assert current.source.available_at is not None
        later_source = current.source.model_copy(
            update={
                "available_at": current.source.available_at + timedelta(hours=1),
                "retrieved_at": current.source.retrieved_at + timedelta(hours=1),
            }
        )
        later_receipt = receipt.model_copy(
            update={
                "evaluated_at": receipt.evaluated_at + timedelta(hours=1),
                "current_disclosure": current.model_copy(update={"source": later_source}),
            }
        )
        assert store.append_event_lineage(later_receipt) == receipt
        with pytest.raises(EventNoveltyReplayConflict):
            store.append_event_disclosure(
                original.model_copy(update={"issuer_name": "Synthetic replay conflict"})
            )
    finally:
        runtime.close()

    with psycopg.connect(
        host="127.0.0.1", port=GATE_PORT, dbname="kalki_test", user="postgres"
    ) as owner:
        row = owner.execute(
            """
            SELECT
                (SELECT count(*) FROM research_event_disclosures),
                (SELECT count(*) FROM research_event_lineage),
                (SELECT disposition FROM research_event_lineage),
                (SELECT authoritative_first_known_at FROM research_event_lineage)
            """
        ).fetchone()
        assert row == (2, 1, "RECAP_EXISTING_EVENT", None)
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            owner.execute("UPDATE research_event_disclosures SET issuer_cik = issuer_cik")
        owner.rollback()
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            owner.execute("TRUNCATE research_event_lineage")


@pytest.mark.skipif(
    GATE_PASSWORD_FILE is None,
    reason="Event novelty PostgreSQL gate is not running",
)
def test_application_role_cannot_mutate_event_history() -> None:
    with psycopg.connect(
        host="127.0.0.1", port=GATE_PORT, dbname="kalki_test", user="kalki_app"
    ) as application:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            application.execute("UPDATE research_event_lineage SET reason = reason")
