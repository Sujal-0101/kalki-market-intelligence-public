"""Disposable PostgreSQL gate for immutable Phase 41 accounting receipts."""

from __future__ import annotations

import base64
import gzip
import os
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from pydantic import HttpUrl

from kalki_market_intelligence.database import DatabaseOptions, DatabaseRuntime
from kalki_market_intelligence.forensics.accounting import (
    AccountingFilingReceipt,
    AccountingForm,
    build_accounting_filing_receipt,
    choose_accounting_tier,
)
from kalki_market_intelligence.providers.sec.accounting import AccountingDiscoveryCandidate
from kalki_market_intelligence.providers.sec.accounting_store import (
    AccountingReplayConflict,
    PostgresAccountingStore,
)
from kalki_market_intelligence.web.repository import PostgresResearchRepository

GATE_PASSWORD_FILE = os.environ.get("KALKI_ACCOUNTING_GATE_PASSWORD_FILE")
GATE_PORT = int(os.environ.get("KALKI_ACCOUNTING_GATE_PORT", "55446"))
NOW = datetime(2026, 8, 31, 20, tzinfo=UTC)
FIXTURE = Path(__file__).parent / "fixtures/accounting/geovax-2026-item-3-01.html.gz.b64"


def _body() -> bytes:
    encoded = "".join(FIXTURE.read_text(encoding="ascii").splitlines())
    return gzip.decompress(base64.b64decode(encoded, validate=True))


def _receipt() -> AccountingFilingReceipt:
    return build_accounting_filing_receipt(
        accession_number="0001437749-26-029184",
        issuer_cik="0000832489",
        issuer_name="GeoVax Labs, Inc.",
        form=AccountingForm.FORM_8_K,
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/832489/000143774926029184/govx20260828_8k.htm"
        ),
        body=_body(),
        accepted_at=datetime(2026, 8, 28, 16, 16, 41, tzinfo=UTC),
        retrieved_at=NOW,
        prior_search_complete=False,
    )


def _candidate(*, accession: str = "0001437749-26-029184") -> AccountingDiscoveryCandidate:
    return AccountingDiscoveryCandidate(
        accession_number=accession,
        index_ciks=("0000832489",),
        index_names=("GeoVax Labs, Inc.",),
        form=AccountingForm.FORM_8_K,
        filed_on=datetime(2026, 8, 28, tzinfo=UTC).date(),
        discovered_at=NOW,
        source_index_url=HttpUrl(
            "https://www.sec.gov/Archives/edgar/daily-index/2026/QTR3/master.20260831.idx"
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
    reason="Phase 41 accounting PostgreSQL gate is not running",
)
def test_accounting_pair_is_idempotent_reconciled_prior_readable_and_append_only() -> None:
    runtime = _runtime()
    receipt = _receipt()
    routing = choose_accounting_tier(receipt)
    runtime.open()
    try:
        store = PostgresAccountingStore(runtime.connection)
        store.append(receipt, routing)
        store.append(receipt, routing)
        prior = store.prior_receipts(
            issuer_cik=receipt.issuer_cik,
            accepted_before=datetime(2026, 9, 1, tzinfo=UTC),
            retrieved_by=datetime(2026, 9, 1, tzinfo=UTC),
        )
        assert prior == (receipt,)
        changed = receipt.model_copy(update={"issuer_name": "Changed issuer"})
        with pytest.raises(AccountingReplayConflict):
            store.append(changed, choose_accounting_tier(changed))
    finally:
        runtime.close()

    with psycopg.connect(
        host="127.0.0.1", port=GATE_PORT, dbname="kalki_test", user="postgres"
    ) as owner:
        counts = owner.execute(
            """
            SELECT (SELECT count(*) FROM research_accounting_receipts),
                   (SELECT count(*) FROM research_accounting_routing_receipts)
            """
        ).fetchone()
        assert counts == (1, 1)
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            owner.execute("UPDATE research_accounting_receipts SET issuer_cik = issuer_cik")
        owner.rollback()
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            owner.execute("TRUNCATE research_accounting_routing_receipts")


@pytest.mark.skipif(
    GATE_PASSWORD_FILE is None,
    reason="Phase 41 accounting PostgreSQL gate is not running",
)
def test_accounting_queue_recovers_and_closes_retained_and_no_events() -> None:
    runtime = _runtime()
    runtime.open()
    try:
        store = PostgresAccountingStore(runtime.connection)
        retained_candidate = _candidate()
        empty_candidate = _candidate(accession="0000000001-26-000001").model_copy(
            update={"form": AccountingForm.FORM_10_Q}
        )
        assert store.discover((retained_candidate, empty_candidate), maximum_backlog=2) == 2
        claimed = store.claim(now=NOW)
        assert claimed is not None and claimed.attempt == 1
        assert claimed.candidate.form is AccountingForm.FORM_10_Q
        store.complete_no_events(claimed, now=NOW)
        retained = store.claim(now=NOW)
        assert retained is not None and retained.attempt == 1
        later = NOW.replace(hour=21)
        assert store.recover_stale(now=later) == 1
        reclaimed = store.claim(now=later)
        assert reclaimed is not None and reclaimed.attempt == 1
        receipt = _receipt()
        store.complete(reclaimed, receipt, choose_accounting_tier(receipt), now=later)
        operations = PostgresResearchRepository(runtime.connection).get_accounting_operations()
        assert operations is not None
        assert (operations.completed, operations.no_events, operations.receipt_count) == (1, 1, 1)
        assert operations.model_free_retained == 1
        assert operations.forms[0].name == "8-K"
        assert operations.event_types[0].name == "LISTING_COMPLIANCE"
        assert operations.comparisons[0].name == "PRIOR_COMPARISON_UNAVAILABLE"
    finally:
        runtime.close()

    with psycopg.connect(
        host="127.0.0.1", port=GATE_PORT, dbname="kalki_test", user="postgres"
    ) as owner:
        rows = owner.execute(
            """
            SELECT status, attempts, terminal_reason FROM research_accounting_jobs
            ORDER BY accession_number
            """
        ).fetchall()
        assert rows == [("no_events", 1, "no_supported_events"), ("completed", 1, None)]
        with pytest.raises(psycopg.errors.RaiseException, match="terminal accounting jobs"):
            owner.execute("UPDATE research_accounting_jobs SET status = 'failed'")


@pytest.mark.skipif(
    GATE_PASSWORD_FILE is None,
    reason="Phase 41 accounting PostgreSQL gate is not running",
)
def test_application_role_cannot_mutate_accounting_history() -> None:
    with psycopg.connect(
        host="127.0.0.1", port=GATE_PORT, dbname="kalki_test", user="kalki_app"
    ) as application:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            application.execute("UPDATE research_accounting_receipts SET issuer_cik = issuer_cik")
