"""Disposable PostgreSQL gate for immutable Phase 39 ownership receipts."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from pydantic import HttpUrl

from kalki_market_intelligence.database import DatabaseOptions, DatabaseRuntime
from kalki_market_intelligence.forensics import choose_ownership_tier
from kalki_market_intelligence.providers.sec.ownership import (
    OwnershipDiscoveryCandidate,
    OwnershipFilingReceipt,
    OwnershipForm,
    parse_ownership_xml,
)
from kalki_market_intelligence.providers.sec.ownership_store import (
    OwnershipReplayConflict,
    PostgresOwnershipStore,
)
from kalki_market_intelligence.web.repository import PostgresResearchRepository

GATE_PASSWORD_FILE = os.environ.get("KALKI_OWNERSHIP_GATE_PASSWORD_FILE")
GATE_PORT = int(os.environ.get("KALKI_OWNERSHIP_GATE_PORT", "55444"))
NOW = datetime(2026, 8, 29, 7, tzinfo=UTC)


def _receipt(*, suffix: str = "") -> OwnershipFilingReceipt:
    body = f"""<ownershipDocument><documentType>4</documentType>
    <periodOfReport>2026-08-26</periodOfReport><issuer><issuerCik>0001001385</issuerCik>
    <issuerName>NWPX Infrastructure, Inc.</issuerName></issuer>
    <nonDerivativeTable><nonDerivativeTransaction><securityTitle><value>Common</value>
    </securityTitle><transactionDate><value>2026-08-26</value></transactionDate>
    <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
    <transactionAmounts><transactionShares><value>4500</value></transactionShares>
    <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
    </transactionAmounts></nonDerivativeTransaction></nonDerivativeTable>{suffix}
    </ownershipDocument>""".encode()
    return parse_ownership_xml(
        body,
        accession_number="0001437749-26-029167",
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/1001385/000143774926029167/rdgdoc.xml"
        ),
        accepted_at=NOW,
        retrieved_at=NOW,
    )


def _candidate() -> OwnershipDiscoveryCandidate:
    return OwnershipDiscoveryCandidate(
        accession_number="0001437749-26-029167",
        index_ciks=("0001001385", "0001922394"),
        index_names=("NWPX Infrastructure, Inc.", "Wray Michael"),
        form=OwnershipForm.FORM_4,
        filed_on=NOW.date(),
        discovered_at=NOW,
        source_index_url=HttpUrl(
            "https://www.sec.gov/Archives/edgar/daily-index/2026/QTR3/master.20260829.idx"
        ),
        source_index_sha256="b" * 64,
    )


def _schedule_receipt(
    *,
    accession: str,
    form: OwnershipForm,
    owner_cik: str,
    owner_name: str,
    accepted_at: datetime,
) -> OwnershipFilingReceipt:
    if form.is_schedule_13d:
        owner = f"""<reportingPersons><reportingPersonInfo>
        <reportingPersonCIK>{owner_cik}</reportingPersonCIK>
        <reportingPersonName>{owner_name}</reportingPersonName>
        <aggregateAmountOwned>100</aggregateAmountOwned>
        </reportingPersonInfo></reportingPersons>"""
        header = """<dateOfEvent>08/28/2026</dateOfEvent><issuerInfo>
        <issuerCIK>0001000694</issuerCIK><issuerName>Issuer</issuerName></issuerInfo>"""
    else:
        owner = f"""<coverPageHeaderReportingPersonDetails>
        <reportingPersonCIK>{owner_cik}</reportingPersonCIK>
        <reportingPersonName>{owner_name}</reportingPersonName>
        <reportingPersonBeneficiallyOwnedAggregateNumberOfShares>100
        </reportingPersonBeneficiallyOwnedAggregateNumberOfShares>
        </coverPageHeaderReportingPersonDetails>"""
        header = """<eventDateRequiresFilingThisStatement>08/28/2026
        </eventDateRequiresFilingThisStatement><issuerInfo>
        <issuerCik>0001000694</issuerCik><issuerName>Issuer</issuerName></issuerInfo>"""
    body = f"""<edgarSubmission><headerData><submissionType>{form.value}</submissionType>
    </headerData><formData><coverPageHeader>{header}</coverPageHeader>{owner}</formData>
    </edgarSubmission>""".encode()
    return parse_ownership_xml(
        body,
        accession_number=accession,
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/1000694/"
            f"{accession.replace('-', '')}/primary.xml"
        ),
        accepted_at=accepted_at,
        retrieved_at=accepted_at,
    )


@pytest.mark.skipif(
    GATE_PASSWORD_FILE is None,
    reason="Phase 39 ownership PostgreSQL gate is not running",
)
def test_postgres_ownership_pair_is_idempotent_reconciled_and_append_only() -> None:
    assert GATE_PASSWORD_FILE is not None
    runtime = DatabaseRuntime(
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
    receipt = _receipt()
    routing = choose_ownership_tier(receipt)
    runtime.open()
    try:
        store = PostgresOwnershipStore(runtime.connection)
        store.append(receipt, routing)
        store.append(receipt, routing)
        changed = _receipt(suffix="<!-- same accession, different primary bytes -->")
        with pytest.raises(OwnershipReplayConflict):
            store.append(changed, choose_ownership_tier(changed))
    finally:
        runtime.close()

    with psycopg.connect(
        host="127.0.0.1",
        port=GATE_PORT,
        dbname="kalki_test",
        user="postgres",
    ) as owner:
        counts = owner.execute(
            """
            SELECT
                (SELECT count(*) FROM research_ownership_receipts),
                (SELECT count(*) FROM research_ownership_routing_receipts)
            """
        ).fetchone()
        assert counts == (1, 1)
        stored = owner.execute(
            """
            SELECT r.source_content_sha256, r.record->>'source_content_sha256',
                   t.event_context, t.record->>'event_context', t.requires_model
            FROM research_ownership_receipts r
            JOIN research_ownership_routing_receipts t USING (accession_number)
            """
        ).fetchone()
        assert stored == (
            receipt.source_content_sha256,
            receipt.source_content_sha256,
            "INSIDER_OWNERSHIP_DISCLOSURE",
            "INSIDER_OWNERSHIP_DISCLOSURE",
            False,
        )
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            owner.execute("UPDATE research_ownership_receipts SET issuer_cik = issuer_cik")
        owner.rollback()
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            owner.execute("TRUNCATE research_ownership_routing_receipts")
        owner.rollback()
        with pytest.raises(psycopg.errors.RaiseException):
            owner.execute(
                """
                INSERT INTO research_ownership_receipts (
                    accession_number, issuer_cik, form, period_or_event_date,
                    accepted_at, retrieved_at, source_url, source_content_sha256,
                    parser_version, record
                ) VALUES (
                    '0001437749-26-029168', '0001001385', '4', '2026-08-26',
                    %s, %s,
                    'https://www.sec.gov/Archives/edgar/data/1001385/other.xml',
                    %s, 'sec-ownership-v1', '{}'::jsonb
                )
                """,
                (NOW, NOW, "a" * 64),
            )


@pytest.mark.skipif(
    GATE_PASSWORD_FILE is None,
    reason="Phase 39 ownership PostgreSQL gate is not running",
)
def test_application_role_cannot_mutate_ownership_history() -> None:
    assert GATE_PASSWORD_FILE is not None
    with psycopg.connect(
        host="127.0.0.1",
        port=GATE_PORT,
        dbname="kalki_test",
        user="kalki_app",
    ) as application:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            application.execute("UPDATE research_ownership_receipts SET issuer_cik = issuer_cik")


@pytest.mark.skipif(
    GATE_PASSWORD_FILE is None,
    reason="Phase 39 ownership PostgreSQL gate is not running",
)
def test_ownership_queue_is_bounded_restart_safe_and_closes_atomically() -> None:
    assert GATE_PASSWORD_FILE is not None
    runtime = DatabaseRuntime(
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
    runtime.open()
    try:
        store = PostgresOwnershipStore(runtime.connection)
        candidate = _candidate()
        assert store.discover((candidate,), maximum_backlog=1) == 1
        later_replay = candidate.model_copy(
            update={
                "discovered_at": NOW.replace(hour=8),
                "source_index_sha256": "c" * 64,
            }
        )
        assert store.discover((later_replay,), maximum_backlog=2) == 0
        conflicting = candidate.model_copy(
            update={"index_names": ("Conflicting issuer", "Wray Michael")}
        )
        with pytest.raises(OwnershipReplayConflict):
            store.discover((conflicting,), maximum_backlog=2)
        claimed = store.claim(now=NOW)
        assert claimed is not None and claimed.attempt == 1
        recovered_at = NOW.replace(hour=8)
        assert store.recover_stale(now=recovered_at) == 1
        reclaimed = store.claim(now=recovered_at)
        assert reclaimed is not None and reclaimed.attempt == 1
        receipt = _receipt()
        store.complete(reclaimed, receipt, choose_ownership_tier(receipt), now=recovered_at)
        assert store.claim(now=recovered_at) is None
        operations = PostgresResearchRepository(runtime.connection).get_ownership_operations()
        assert operations is not None
        assert (operations.completed, operations.receipt_count) == (1, 1)
        assert operations.model_free_retained == 1
        assert operations.escalated_for_review == 0
        assert operations.forms[0].name == "4"
    finally:
        runtime.close()

    with psycopg.connect(
        host="127.0.0.1",
        port=GATE_PORT,
        dbname="kalki_test",
        user="postgres",
    ) as owner:
        job = owner.execute(
            """
            SELECT status, attempts, last_error_category, resolved_issuer_cik,
                   (SELECT count(*) FROM research_candidates)
            FROM research_ownership_jobs
            """
        ).fetchone()
        assert job == ("completed", 1, None, "0001001385", 0)
        with pytest.raises(psycopg.errors.RaiseException, match="terminal ownership jobs"):
            owner.execute("UPDATE research_ownership_jobs SET status = 'failed'")


@pytest.mark.skipif(
    GATE_PASSWORD_FILE is None,
    reason="Phase 39 ownership PostgreSQL gate is not running",
)
def test_schedule_transition_history_requires_the_same_reporting_owner_set() -> None:
    assert GATE_PASSWORD_FILE is not None
    runtime = DatabaseRuntime(
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
    first = _schedule_receipt(
        accession="0000000001-26-000001",
        form=OwnershipForm.SCHEDULE_13G,
        owner_cik="0000000101",
        owner_name="Same Holder",
        accepted_at=NOW,
    )
    unrelated = _schedule_receipt(
        accession="0000000001-26-000002",
        form=OwnershipForm.SCHEDULE_13D,
        owner_cik="0000000202",
        owner_name="Different Holder",
        accepted_at=NOW.replace(hour=8),
    )
    current = _schedule_receipt(
        accession="0000000001-26-000003",
        form=OwnershipForm.SCHEDULE_13D,
        owner_cik="0000000101",
        owner_name="Same Holder",
        accepted_at=NOW.replace(hour=9),
    )
    runtime.open()
    try:
        store = PostgresOwnershipStore(runtime.connection)
        store.append(first, choose_ownership_tier(first))
        store.append(unrelated, choose_ownership_tier(unrelated))
        assert store.previous_schedule_form(receipt=current) is OwnershipForm.SCHEDULE_13G
    finally:
        runtime.close()
