"""The accounting worker is bounded, restart-safe, fail-closed, and model-free."""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from pydantic import HttpUrl

from kalki_market_intelligence.forensics.accounting import (
    AccountingFilingReceipt,
    AccountingForm,
    AccountingTier0Receipt,
)
from kalki_market_intelligence.forensics.filing_change import (
    FilingChangeSelectionReceipt,
    FilingChangeSnapshot,
)
from kalki_market_intelligence.providers.sec.accounting import AccountingDiscoveryCandidate
from kalki_market_intelligence.providers.sec.accounting_store import ClaimedAccountingJob
from kalki_market_intelligence.providers.sec.client import (
    SecFetchedDocument,
    SecFetchedPrimaryDocument,
)
from kalki_market_intelligence.radar.accounting_source import parse_accounting_master_index
from kalki_market_intelligence.radar.accounting_worker import AccountingWorker
from kalki_market_intelligence.radar.sec_source import SecRadarDocument

NOW = datetime(2026, 8, 31, 20, tzinfo=UTC)
ACCESSION = "0001437749-26-029184"
CIK = "0000832489"
FIXTURE = Path(__file__).parent / "fixtures/accounting/geovax-2026-item-3-01.html.gz.b64"


def _body() -> bytes:
    encoded = "".join(FIXTURE.read_text(encoding="ascii").splitlines())
    return gzip.decompress(base64.b64decode(encoded, validate=True))


def candidate() -> AccountingDiscoveryCandidate:
    return AccountingDiscoveryCandidate(
        accession_number=ACCESSION,
        index_ciks=(CIK,),
        index_names=("GeoVax Labs, Inc.",),
        form=AccountingForm.FORM_8_K,
        filed_on=date(2026, 8, 28),
        discovered_at=NOW,
        source_index_url=HttpUrl(
            "https://www.sec.gov/Archives/edgar/daily-index/2026/QTR3/master.20260831.idx"
        ),
        source_index_sha256="a" * 64,
    )


class IndexClient:
    def latest_master_index(self, observed_on: date) -> SecRadarDocument:
        assert observed_on == NOW.date()
        return SecRadarDocument(
            url=str(candidate().source_index_url),
            body=(
                b"832489|GeoVax Labs, Inc.|8-K|2026-08-28|"
                b"edgar/data/832489/0001437749-26-029184.txt\n"
                b"1|Ignored issuer|20-F|2026-08-28|edgar/data/1/0000000001-26-000001.txt"
            ),
            content_sha256="a" * 64,
            retrieved_at=NOW,
            media_type="text/plain",
        )


class Store:
    def __init__(self) -> None:
        self.claims: list[ClaimedAccountingJob] = []
        self.completed: list[tuple[AccountingFilingReceipt, AccountingTier0Receipt]] = []
        self.no_events: list[str] = []
        self.failures: list[str] = []

    def recover_stale(self, *, now: datetime, lease: timedelta = timedelta(minutes=30)) -> int:
        assert now == NOW and lease == timedelta(minutes=30)
        return 0

    def discover(
        self,
        candidates: tuple[AccountingDiscoveryCandidate, ...],
        *,
        maximum_backlog: int,
    ) -> int:
        assert maximum_backlog == 250
        self.claims.extend(ClaimedAccountingJob(item, 1) for item in candidates)
        return len(candidates)

    def claim(self, *, now: datetime) -> ClaimedAccountingJob | None:
        assert now == NOW
        return self.claims.pop(0) if self.claims else None

    def prior_receipts(
        self,
        *,
        issuer_cik: str,
        accepted_before: datetime,
        retrieved_by: datetime,
        limit: int = 32,
    ) -> tuple[AccountingFilingReceipt, ...]:
        assert issuer_cik == CIK and retrieved_by == NOW and limit == 32
        assert accepted_before == datetime(2026, 8, 28, 16, 16, 41, tzinfo=UTC)
        return ()

    def complete(
        self,
        claimed: ClaimedAccountingJob,
        receipt: AccountingFilingReceipt,
        routing: AccountingTier0Receipt,
        *,
        now: datetime,
    ) -> None:
        assert claimed.candidate.accession_number == receipt.accession_number and now == NOW
        self.completed.append((receipt, routing))

    def complete_no_events(self, claimed: ClaimedAccountingJob, *, now: datetime) -> None:
        assert now == NOW
        self.no_events.append(claimed.candidate.accession_number)

    def fail(
        self,
        claimed: ClaimedAccountingJob,
        *,
        category: str,
        now: datetime,
        retry_delay: timedelta = timedelta(hours=1),
    ) -> str:
        assert now == NOW and retry_delay == timedelta(hours=1)
        self.failures.append(category)
        return "retry_wait"


class SecClient:
    def __init__(self, body: bytes | None = None, *, form: str = "8-K") -> None:
        self.body = _body() if body is None else body
        self.form = form
        self.primary_fetches = 0

    def fetch_submissions(self, cik: str | int) -> SecFetchedDocument:
        normalized = str(cik).zfill(10)
        body = json.dumps(
            {
                "cik": normalized,
                "name": "GeoVax Labs, Inc.",
                "filings": {
                    "recent": {
                        "accessionNumber": [ACCESSION],
                        "filingDate": ["2026-08-28"],
                        "reportDate": ["2026-08-28"],
                        "acceptanceDateTime": ["2026-08-28T16:16:41Z"],
                        "form": [self.form],
                        "fileNumber": ["001-33092"],
                        "primaryDocument": ["govx20260828_8k.htm"],
                        "primaryDocDescription": ["FORM 8-K"],
                    }
                },
            }
        ).encode()
        return SecFetchedDocument(
            endpoint="submissions",
            cik=normalized,
            url=f"https://data.sec.gov/submissions/CIK{normalized}.json",
            status_code=200,
            headers={"content-type": "application/json"},
            body=body,
            content_sha256=hashlib.sha256(body).hexdigest(),
            retrieved_at=NOW,
        )

    def fetch_primary_html_document(
        self,
        *,
        cik: str | int,
        accession_number: str,
        document_name: str,
    ) -> SecFetchedPrimaryDocument:
        assert str(cik).zfill(10) == CIK and accession_number == ACCESSION
        self.primary_fetches += 1
        url = f"https://www.sec.gov/Archives/edgar/data/832489/000143774926029184/{document_name}"
        return SecFetchedPrimaryDocument(
            cik=CIK,
            accession_number=accession_number,
            document_name=document_name,
            url=url,
            status_code=200,
            headers={"content-type": "text/html"},
            body=self.body,
            content_sha256=hashlib.sha256(self.body).hexdigest(),
            retrieved_at=NOW,
        )


class FilingChangeStore:
    def __init__(self) -> None:
        self.snapshots: list[FilingChangeSnapshot] = []
        self.selections: list[FilingChangeSelectionReceipt] = []

    def append_filing_change_snapshot(self, snapshot: FilingChangeSnapshot) -> None:
        if snapshot not in self.snapshots:
            self.snapshots.append(snapshot)

    def filing_change_snapshot_for_accession(
        self,
        *,
        cik: str,
        accession_number: str,
        knowledge_cutoff_at: datetime,
    ) -> FilingChangeSnapshot | None:
        return next(
            (
                item
                for item in self.snapshots
                if item.cik == cik
                and item.accession_number == accession_number
                and item.retrieved_at <= knowledge_cutoff_at
            ),
            None,
        )

    def filing_change_snapshots(
        self,
        *,
        cik: str,
        knowledge_cutoff_at: datetime,
        exclude_accession_number: str | None = None,
        limit: int = 16,
    ) -> tuple[FilingChangeSnapshot, ...]:
        return tuple(
            item
            for item in self.snapshots
            if item.cik == cik
            and item.available_at <= knowledge_cutoff_at
            and item.retrieved_at <= knowledge_cutoff_at
            and item.accession_number != exclude_accession_number
        )[:limit]

    def append_filing_change_selection(
        self,
        previous: FilingChangeSnapshot,
        current: FilingChangeSnapshot,
        receipt: FilingChangeSelectionReceipt,
    ) -> None:
        self.append_filing_change_snapshot(previous)
        self.append_filing_change_snapshot(current)
        if receipt not in self.selections:
            self.selections.append(receipt)


class FailingFilingChangeStore(FilingChangeStore):
    def append_filing_change_snapshot(self, snapshot: FilingChangeSnapshot) -> None:
        raise RuntimeError("simulated filing-change persistence failure")


def test_daily_index_selects_only_supported_accounting_forms() -> None:
    assert parse_accounting_master_index(IndexClient().latest_master_index(NOW.date())) == (
        candidate(),
    )


def test_worker_persists_exact_receipt_and_model_free_route() -> None:
    store = Store()
    filing_change_store = FilingChangeStore()
    sec_client = SecClient()
    worker = AccountingWorker(
        store=store,
        index_client=IndexClient(),
        sec_client=sec_client,
        filing_change_store=filing_change_store,
        now=lambda: NOW,
    )
    assert worker.run_once() == 900
    assert store.failures == [] and store.no_events == []
    receipt, routing = store.completed[0]
    assert receipt.issuer_cik == CIK
    assert receipt.prior_search_complete is False
    assert {item.event_type.value for item in receipt.events} == {"LISTING_COMPLIANCE"}
    assert routing.decision.requires_model is False
    assert sec_client.primary_fetches == 1
    assert filing_change_store.snapshots == []


def test_valid_filing_without_exact_events_closes_separately() -> None:
    store = Store()
    filing_change_store = FilingChangeStore()
    body = (
        b"<html><h1>Liquidity and Capital Resources</h1><p>"
        + b"Ordinary operating activity and customer demand are discussed without a closed "
        b"accounting or compliance event. " * 4 + b"</p><h1>Item 6. Exhibits</h1></html>"
    )
    periodic_candidate = candidate().model_copy(update={"form": AccountingForm.FORM_10_Q})
    sec_client = SecClient(body, form="10-Q")
    worker = AccountingWorker(
        store=store,
        index_client=IndexClient(),
        sec_client=sec_client,
        filing_change_store=filing_change_store,
        now=lambda: NOW,
    )
    worker._process(ClaimedAccountingJob(periodic_candidate, 1))
    assert store.no_events == [ACCESSION]
    assert store.completed == [] and store.failures == []
    assert sec_client.primary_fetches == 1
    assert [item.accession_number for item in filing_change_store.snapshots] == [ACCESSION]


def test_filing_change_persistence_failure_retries_parent_job() -> None:
    store = Store()
    body = (
        b"<html><h1>Liquidity and Capital Resources</h1><p>"
        + b"Ordinary operating activity is discussed without a closed accounting event. " * 4
        + b"</p><h1>Item 6. Exhibits</h1></html>"
    )
    periodic_candidate = candidate().model_copy(update={"form": AccountingForm.FORM_10_Q})
    worker = AccountingWorker(
        store=store,
        index_client=IndexClient(),
        sec_client=SecClient(body, form="10-Q"),
        filing_change_store=FailingFilingChangeStore(),
        now=lambda: NOW,
    )

    worker._process(ClaimedAccountingJob(periodic_candidate, 1))

    assert store.completed == [] and store.no_events == []
    assert store.failures == ["persistence_error"]


def test_multiple_index_issuers_fail_closed_without_guessing() -> None:
    base = candidate()
    ambiguous = base.model_copy(
        update={
            "index_ciks": ("0000000001", CIK),
            "index_names": ("Co-registrant", "GeoVax Labs, Inc."),
        }
    )
    store = Store()
    worker = AccountingWorker(
        store=store,
        index_client=IndexClient(),
        sec_client=SecClient(),
        batch_size=1,
        now=lambda: NOW,
    )
    worker._process(ClaimedAccountingJob(ambiguous, 1))
    assert store.failures == ["metadata_unavailable"]
