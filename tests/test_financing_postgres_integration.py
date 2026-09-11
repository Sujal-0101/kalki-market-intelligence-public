"""Disposable PostgreSQL gate for immutable Phase 40 financing receipts."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from pydantic import HttpUrl

from kalki_market_intelligence.database import DatabaseOptions, DatabaseRuntime
from kalki_market_intelligence.forensics import (
    FinancingFilingReceipt,
    FinancingForm,
    choose_financing_tier,
    extract_financing_evidence,
    parse_public_offering_terms,
)
from kalki_market_intelligence.providers.sec.financing import FinancingDiscoveryCandidate
from kalki_market_intelligence.providers.sec.financing_store import (
    FinancingReplayConflict,
    PostgresFinancingStore,
)
from kalki_market_intelligence.web.repository import PostgresResearchRepository

GATE_PASSWORD_FILE = os.environ.get("KALKI_FINANCING_GATE_PASSWORD_FILE")
GATE_PORT = int(os.environ.get("KALKI_FINANCING_GATE_PORT", "55445"))
NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)
FIXTURE = (
    Path(__file__).parent / "fixtures/financing/wellchange-2026-424b4-priced-offering-excerpt.html"
)


def _receipt() -> FinancingFilingReceipt:
    bundle = extract_financing_evidence(FIXTURE.read_bytes())
    return FinancingFilingReceipt(
        accession_number="0001213900-26-094944",
        issuer_cik="0001990251",
        issuer_name="Wellchange Holdings Company Limited",
        form=FinancingForm.FORM_424B4,
        terms=parse_public_offering_terms(bundle),
        evidence_bundle=bundle,
        source_url=HttpUrl(
            "https://www.sec.gov/Archives/edgar/data/1990251/000121390026094944/"
            "ea0303809-424b4_wellchange.htm"
        ),
        source_content_sha256=bundle.source_content_sha256,
        accepted_at=NOW,
        retrieved_at=NOW,
    )


def _candidate(*, accession: str = "0001213900-26-094944") -> FinancingDiscoveryCandidate:
    return FinancingDiscoveryCandidate(
        accession_number=accession,
        index_ciks=("0001990251",),
        index_names=("Wellchange Holdings Company Limited",),
        form=FinancingForm.FORM_424B4,
        filed_on=NOW.date(),
        discovered_at=NOW,
        source_index_url=HttpUrl(
            "https://www.sec.gov/Archives/edgar/daily-index/2026/QTR3/master.20260830.idx"
        ),
        source_index_sha256="b" * 64,
    )


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
    reason="Phase 40 financing PostgreSQL gate is not running",
)
def test_financing_pair_is_idempotent_reconciled_and_append_only() -> None:
    runtime = _runtime()
    receipt = _receipt()
    routing = choose_financing_tier(receipt)
    runtime.open()
    try:
        store = PostgresFinancingStore(runtime.connection)
        store.append(receipt, routing)
        store.append(receipt, routing)
        changed = receipt.model_copy(update={"issuer_name": "Changed issuer"})
        with pytest.raises(FinancingReplayConflict):
            store.append(changed, choose_financing_tier(changed))
    finally:
        runtime.close()

    with psycopg.connect(
        host="127.0.0.1", port=GATE_PORT, dbname="kalki_test", user="postgres"
    ) as owner:
        counts = owner.execute(
            """
            SELECT (SELECT count(*) FROM research_financing_receipts),
                   (SELECT count(*) FROM research_financing_routing_receipts)
            """
        ).fetchone()
        assert counts == (1, 1)
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            owner.execute("UPDATE research_financing_receipts SET issuer_cik = issuer_cik")
        owner.rollback()
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            owner.execute("TRUNCATE research_financing_routing_receipts")


@pytest.mark.skipif(
    GATE_PASSWORD_FILE is None,
    reason="Phase 40 financing PostgreSQL gate is not running",
)
def test_financing_queue_recovers_and_closes_retained_and_no_terms() -> None:
    runtime = _runtime()
    runtime.open()
    try:
        store = PostgresFinancingStore(runtime.connection)
        candidate = _candidate()
        empty_candidate = _candidate(accession="0000000001-26-000001").model_copy(
            update={"form": FinancingForm.FORM_8_K}
        )
        assert store.discover((candidate, empty_candidate), maximum_backlog=2) == 2
        claimed = store.claim(now=NOW)
        assert claimed is not None and claimed.attempt == 1
        assert claimed.candidate.form is FinancingForm.FORM_424B4
        later = NOW.replace(hour=13)
        assert store.recover_stale(now=later) == 1
        reclaimed = store.claim(now=later)
        assert reclaimed is not None and reclaimed.attempt == 1
        receipt = _receipt()
        store.complete(reclaimed, receipt, choose_financing_tier(receipt), now=later)
        no_terms = store.claim(now=later)
        assert no_terms is not None
        store.complete_no_terms(no_terms, now=later)
        operations = PostgresResearchRepository(runtime.connection).get_financing_operations()
        assert operations is not None
        assert (operations.completed, operations.no_terms, operations.receipt_count) == (1, 1, 1)
        assert operations.model_free_retained == 1
        assert operations.forms[0].name == "424B4"
        assert operations.contexts[0].name == "EQUITY_FINANCING"
    finally:
        runtime.close()

    with psycopg.connect(
        host="127.0.0.1", port=GATE_PORT, dbname="kalki_test", user="postgres"
    ) as owner:
        rows = owner.execute(
            """
            SELECT status, attempts, terminal_reason FROM research_financing_jobs
            ORDER BY accession_number
            """
        ).fetchall()
        assert rows == [("no_terms", 1, "no_supported_terms"), ("completed", 1, None)]
        with pytest.raises(psycopg.errors.RaiseException, match="terminal financing jobs"):
            owner.execute("UPDATE research_financing_jobs SET status = 'failed'")


@pytest.mark.skipif(
    GATE_PASSWORD_FILE is None,
    reason="Phase 40 financing PostgreSQL gate is not running",
)
def test_financing_claim_prefers_resolvable_identity_within_same_form() -> None:
    runtime = _runtime()
    single = _candidate(accession="0000000001-26-000010").model_copy(
        update={"form": FinancingForm.FORM_424B2}
    )
    ambiguous = _candidate(accession="0000000001-26-000009").model_copy(
        update={
            "form": FinancingForm.FORM_424B2,
            "index_ciks": ("0000000001", "0001990251"),
            "index_names": ("Co-registrant", "Wellchange Holdings Company Limited"),
        }
    )
    runtime.open()
    try:
        store = PostgresFinancingStore(runtime.connection)
        assert store.discover((ambiguous, single), maximum_backlog=100) == 2

        claimed = store.claim(now=NOW)

        assert claimed is not None
        assert claimed.candidate.accession_number == single.accession_number
        store.complete_no_terms(claimed, now=NOW)
    finally:
        runtime.close()


@pytest.mark.skipif(
    GATE_PASSWORD_FILE is None,
    reason="Phase 40 financing PostgreSQL gate is not running",
)
def test_application_role_cannot_mutate_financing_history() -> None:
    with psycopg.connect(
        host="127.0.0.1", port=GATE_PORT, dbname="kalki_test", user="kalki_app"
    ) as application:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            application.execute("UPDATE research_financing_receipts SET issuer_cik = issuer_cik")
