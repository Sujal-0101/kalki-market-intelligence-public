"""The ownership worker is bounded, restart-safe, and model-free."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta

from pydantic import HttpUrl

from kalki_market_intelligence.forensics import OwnershipTier0Receipt
from kalki_market_intelligence.providers.sec.client import (
    SecFetchedDocument,
    SecFetchedPrimaryDocument,
    SecHttpError,
)
from kalki_market_intelligence.providers.sec.ownership import (
    OwnershipDiscoveryCandidate,
    OwnershipFilingReceipt,
    OwnershipForm,
)
from kalki_market_intelligence.providers.sec.ownership_store import ClaimedOwnershipJob
from kalki_market_intelligence.radar.ownership_worker import OwnershipWorker
from kalki_market_intelligence.radar.sec_source import SecRadarDocument

NOW = datetime(2026, 8, 29, 17, tzinfo=UTC)
ACCESSION = "0001437749-26-029167"


def candidate() -> OwnershipDiscoveryCandidate:
    return OwnershipDiscoveryCandidate(
        accession_number=ACCESSION,
        index_ciks=("0000000001", "0001001385"),
        index_names=("Reporting owner", "NWPX Infrastructure, Inc."),
        form=OwnershipForm.FORM_4,
        filed_on=NOW.date(),
        discovered_at=NOW,
        source_index_url=HttpUrl(
            "https://www.sec.gov/Archives/edgar/daily-index/2026/QTR3/master.20260829.idx"
        ),
        source_index_sha256="a" * 64,
    )


class IndexClient:
    def latest_master_index(self, observed_on: date) -> SecRadarDocument:
        assert observed_on == NOW.date()
        return SecRadarDocument(
            url=str(candidate().source_index_url),
            body=(
                b"1|Reporting owner|4|2026-08-29|"
                b"edgar/data/1/0001437749-26-029167.txt\n"
                b"1001385|NWPX Infrastructure, Inc.|4|2026-08-29|"
                b"edgar/data/1001385/0001437749-26-029167.txt"
            ),
            content_sha256="a" * 64,
            retrieved_at=NOW,
            media_type="text/plain",
        )


class UnavailableIndexClient:
    def latest_master_index(self, observed_on: date) -> SecRadarDocument:
        raise SecHttpError(503, "https://www.sec.gov/Archives/edgar/daily-index/")


class Store:
    def __init__(self) -> None:
        self.claims: list[ClaimedOwnershipJob] = []
        self.completed: list[tuple[OwnershipFilingReceipt, OwnershipTier0Receipt]] = []
        self.failures: list[str] = []
        self.discovered = 0
        self.recovered = 0

    def recover_stale(self, *, now: datetime, lease: timedelta = timedelta(minutes=30)) -> int:
        assert now == NOW and lease == timedelta(minutes=30)
        return self.recovered

    def discover(
        self,
        candidates: tuple[OwnershipDiscoveryCandidate, ...],
        *,
        maximum_backlog: int,
    ) -> int:
        assert maximum_backlog == 250
        self.discovered += len(candidates)
        self.claims.extend(ClaimedOwnershipJob(item, 1) for item in candidates)
        return len(candidates)

    def claim(self, *, now: datetime) -> ClaimedOwnershipJob | None:
        assert now == NOW
        return self.claims.pop(0) if self.claims else None

    def previous_schedule_form(
        self,
        *,
        receipt: OwnershipFilingReceipt,
    ) -> OwnershipForm | None:
        assert receipt.issuer_cik == "0001001385" and receipt.accepted_at == NOW
        return None

    def complete(
        self,
        claimed: ClaimedOwnershipJob,
        receipt: OwnershipFilingReceipt,
        routing: OwnershipTier0Receipt,
        *,
        now: datetime,
    ) -> None:
        assert claimed.candidate.accession_number == receipt.accession_number
        assert now == NOW
        self.completed.append((receipt, routing))

    def fail(
        self,
        claimed: ClaimedOwnershipJob,
        *,
        category: str,
        now: datetime,
        retry_delay: timedelta = timedelta(hours=1),
    ) -> str:
        assert claimed.candidate.accession_number == ACCESSION
        assert now == NOW and retry_delay == timedelta(hours=1)
        self.failures.append(category)
        return "retry_wait"


class SecClient:
    def __init__(self, *, malformed_primary: bool = False, missing_metadata: bool = False) -> None:
        self.malformed_primary = malformed_primary
        self.missing_metadata = missing_metadata
        self.submission_ciks: list[str] = []

    def fetch_submissions(self, cik: str | int) -> SecFetchedDocument:
        normalized_cik = str(cik).zfill(10)
        self.submission_ciks.append(normalized_cik)
        accession = "0001437749-26-999999" if self.missing_metadata else ACCESSION
        body = json.dumps(
            {
                "cik": normalized_cik,
                "name": (
                    "NWPX Infrastructure, Inc."
                    if normalized_cik == "0001001385"
                    else "Reporting owner"
                ),
                "tickers": ["NWPX"],
                "exchanges": ["Nasdaq"],
                "filings": {
                    "recent": {
                        "accessionNumber": [accession],
                        "filingDate": ["2026-08-29"],
                        "reportDate": ["2026-08-26"],
                        "acceptanceDateTime": ["2026-08-29T17:00:00Z"],
                        "form": ["4"],
                        "fileNumber": [""],
                        "primaryDocument": ["rdgdoc.xml"],
                        "primaryDocDescription": ["FORM 4"],
                    },
                    "files": [],
                },
            }
        ).encode()
        return SecFetchedDocument(
            endpoint="submissions",
            cik=normalized_cik,
            url=f"https://data.sec.gov/submissions/CIK{normalized_cik}.json",
            status_code=200,
            headers={"content-type": "application/json"},
            body=body,
            content_sha256=hashlib.sha256(body).hexdigest(),
            retrieved_at=NOW,
        )

    def fetch_primary_document(
        self,
        *,
        cik: str | int,
        accession_number: str,
        document_name: str,
    ) -> SecFetchedPrimaryDocument:
        normalized_cik = str(cik).zfill(10)
        assert (accession_number, document_name) == (ACCESSION, "rdgdoc.xml")
        body = (
            b"<bad"
            if self.malformed_primary
            else b"""<ownershipDocument><documentType>4</documentType>
            <periodOfReport>2026-08-26</periodOfReport><issuer>
            <issuerCik>0001001385</issuerCik><issuerName>NWPX Infrastructure, Inc.</issuerName>
            </issuer></ownershipDocument>"""
        )
        return SecFetchedPrimaryDocument(
            cik=normalized_cik,
            accession_number=ACCESSION,
            document_name="rdgdoc.xml",
            url=(
                "https://www.sec.gov/Archives/edgar/data/"
                f"{int(normalized_cik)}/000143774926029167/rdgdoc.xml"
            ),
            status_code=200,
            headers={"content-type": "text/xml"},
            body=body,
            content_sha256=hashlib.sha256(body).hexdigest(),
            retrieved_at=NOW,
        )


def worker(store: Store, client: SecClient) -> OwnershipWorker:
    return OwnershipWorker(
        store=store,
        index_client=IndexClient(),
        sec_client=client,
        batch_size=2,
        now=lambda: NOW,
    )


def test_worker_persists_model_free_primary_source_receipt() -> None:
    store = Store()
    client = SecClient()

    assert worker(store, client).run_once() == 900

    assert store.discovered == 1
    assert not store.failures
    receipt, routing = store.completed[0]
    assert receipt.accession_number == ACCESSION
    assert routing.accession_number == ACCESSION
    assert not routing.decision.requires_model
    assert client.submission_ciks == ["0000000001", "0001001385"]


def test_worker_classifies_missing_metadata_and_parse_failure_without_details() -> None:
    missing_store = Store()
    worker(missing_store, SecClient(missing_metadata=True)).run_once()
    assert missing_store.failures == ["metadata_unavailable"]
    assert not missing_store.completed

    malformed_store = Store()
    worker(malformed_store, SecClient(malformed_primary=True)).run_once()
    assert malformed_store.failures == ["parse_error"]
    assert not malformed_store.completed


def test_index_provider_failure_returns_normal_long_poll_without_claiming_work() -> None:
    store = Store()
    ownership_worker = OwnershipWorker(
        store=store,
        index_client=UnavailableIndexClient(),
        sec_client=SecClient(),
        now=lambda: NOW,
    )

    assert ownership_worker.run_once() == 900
    assert store.discovered == 0
    assert not store.completed and not store.failures
