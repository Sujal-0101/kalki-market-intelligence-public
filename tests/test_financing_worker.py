"""The financing worker is bounded, restart-safe, fail-closed, and model-free."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from pydantic import HttpUrl

from kalki_market_intelligence.forensics import (
    FinancingFilingReceipt,
    FinancingForm,
    FinancingTier0Receipt,
)
from kalki_market_intelligence.forensics.filing_change import (
    FilingChangeSelectionReceipt,
    FilingChangeSnapshot,
)
from kalki_market_intelligence.providers.sec.client import (
    SecFetchedDocument,
    SecFetchedPrimaryDocument,
)
from kalki_market_intelligence.providers.sec.financing import FinancingDiscoveryCandidate
from kalki_market_intelligence.providers.sec.financing_store import ClaimedFinancingJob
from kalki_market_intelligence.radar.financing_source import parse_financing_master_index
from kalki_market_intelligence.radar.financing_worker import FinancingWorker
from kalki_market_intelligence.radar.sec_source import SecRadarDocument

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)
ACCESSION = "0001213900-26-094944"
CIK = "0001990251"
FIXTURE = (
    Path(__file__).parent / "fixtures/financing/wellchange-2026-424b4-priced-offering-excerpt.html"
)


def candidate() -> FinancingDiscoveryCandidate:
    return FinancingDiscoveryCandidate(
        accession_number=ACCESSION,
        index_ciks=(CIK,),
        index_names=("Wellchange Holdings Company Limited",),
        form=FinancingForm.FORM_424B4,
        filed_on=date(2026, 8, 28),
        discovered_at=NOW,
        source_index_url=HttpUrl(
            "https://www.sec.gov/Archives/edgar/daily-index/2026/QTR3/master.20260830.idx"
        ),
        source_index_sha256="a" * 64,
    )


class IndexClient:
    def latest_master_index(self, observed_on: date) -> SecRadarDocument:
        assert observed_on == NOW.date()
        return SecRadarDocument(
            url=str(candidate().source_index_url),
            body=(
                b"1990251|Wellchange Holdings Company Limited|424B4|2026-08-28|"
                b"edgar/data/1990251/0001213900-26-094944.txt\n"
                b"1|Ignored issuer|10-Q|2026-08-28|edgar/data/1/0000000001-26-000001.txt"
            ),
            content_sha256="a" * 64,
            retrieved_at=NOW,
            media_type="text/plain",
        )


class Store:
    def __init__(self) -> None:
        self.claims: list[ClaimedFinancingJob] = []
        self.completed: list[tuple[FinancingFilingReceipt, FinancingTier0Receipt]] = []
        self.no_terms: list[str] = []
        self.failures: list[str] = []

    def recover_stale(self, *, now: datetime, lease: timedelta = timedelta(minutes=30)) -> int:
        assert now == NOW and lease == timedelta(minutes=30)
        return 0

    def discover(
        self,
        candidates: tuple[FinancingDiscoveryCandidate, ...],
        *,
        maximum_backlog: int,
    ) -> int:
        assert maximum_backlog == 250
        self.claims.extend(ClaimedFinancingJob(item, 1) for item in candidates)
        return len(candidates)

    def claim(self, *, now: datetime) -> ClaimedFinancingJob | None:
        assert now == NOW
        return self.claims.pop(0) if self.claims else None

    def complete(
        self,
        claimed: ClaimedFinancingJob,
        receipt: FinancingFilingReceipt,
        routing: FinancingTier0Receipt,
        *,
        now: datetime,
    ) -> None:
        assert claimed.candidate.accession_number == receipt.accession_number and now == NOW
        self.completed.append((receipt, routing))

    def complete_no_terms(self, claimed: ClaimedFinancingJob, *, now: datetime) -> None:
        assert now == NOW
        self.no_terms.append(claimed.candidate.accession_number)

    def fail(
        self,
        claimed: ClaimedFinancingJob,
        *,
        category: str,
        now: datetime,
        retry_delay: timedelta = timedelta(hours=1),
    ) -> str:
        assert now == NOW and retry_delay == timedelta(hours=1)
        self.failures.append(category)
        return "retry_wait"


class SecClient:
    def __init__(self, body: bytes | None = None) -> None:
        self.body = FIXTURE.read_bytes() if body is None else body
        self.primary_fetches = 0

    def fetch_submissions(self, cik: str | int) -> SecFetchedDocument:
        normalized = str(cik).zfill(10)
        body = json.dumps(
            {
                "cik": normalized,
                "name": "Wellchange Holdings Company Limited",
                "filings": {
                    "recent": {
                        "accessionNumber": [ACCESSION],
                        "filingDate": ["2026-08-28"],
                        "reportDate": ["2026-08-28"],
                        "acceptanceDateTime": ["2026-08-28T14:13:51Z"],
                        "form": ["424B4"],
                        "fileNumber": ["333-297294"],
                        "primaryDocument": ["ea0303809-424b4_wellchange.htm"],
                        "primaryDocDescription": ["PROSPECTUS"],
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
        url = f"https://www.sec.gov/Archives/edgar/data/1990251/000121390026094944/{document_name}"
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


def test_daily_index_selects_only_supported_financing_forms() -> None:
    parsed = parse_financing_master_index(IndexClient().latest_master_index(NOW.date()))
    assert parsed == (candidate(),)


def test_worker_persists_exact_receipt_and_model_free_route() -> None:
    store = Store()
    filing_change_store = FilingChangeStore()
    body = (
        b"<html><h1>Risk Factors</h1><p>"
        + b"The offered securities involve risks described by this exact filing. " * 4
        + b"</p>"
        + FIXTURE.read_bytes()
        + b"</html>"
    )
    sec_client = SecClient(body)
    worker = FinancingWorker(
        store=store,
        index_client=IndexClient(),
        sec_client=sec_client,
        filing_change_store=filing_change_store,
        now=lambda: NOW,
    )
    assert worker.run_once() == 900
    assert store.failures == [] and store.no_terms == []
    receipt, routing = store.completed[0]
    assert receipt.issuer_cik == CIK
    assert receipt.terms[0].offered_shares == 50_000_000
    assert routing.decision.requires_model is False
    assert routing.decision.outcome.value == "retain"
    assert sec_client.primary_fetches == 1
    assert [item.accession_number for item in filing_change_store.snapshots] == [ACCESSION]


def test_valid_filing_without_exact_terms_closes_as_no_terms() -> None:
    store = Store()
    filing_change_store = FilingChangeStore()
    body = (
        b"<html><h1>Risk Factors</h1><p>"
        + b"Ordinary operational uncertainty remains under review without financing terms. " * 4
        + b"</p></html>"
    )
    sec_client = SecClient(body)
    worker = FinancingWorker(
        store=store,
        index_client=IndexClient(),
        sec_client=sec_client,
        filing_change_store=filing_change_store,
        now=lambda: NOW,
    )
    worker.run_once()
    assert store.no_terms == [ACCESSION]
    assert store.completed == [] and store.failures == []
    assert sec_client.primary_fetches == 1
    assert [item.accession_number for item in filing_change_store.snapshots] == [ACCESSION]


def test_filing_change_persistence_failure_retries_parent_job() -> None:
    store = Store()
    body = (
        b"<html><h1>Risk Factors</h1><p>"
        + b"The offered securities involve risks described by this exact filing. " * 4
        + b"</p>"
        + FIXTURE.read_bytes()
        + b"</html>"
    )
    worker = FinancingWorker(
        store=store,
        index_client=IndexClient(),
        sec_client=SecClient(body),
        filing_change_store=FailingFilingChangeStore(),
        now=lambda: NOW,
    )

    worker.run_once()

    assert store.completed == [] and store.no_terms == []
    assert store.failures == ["persistence_error"]


def test_multiple_index_issuers_fail_closed_without_guessing() -> None:
    base = candidate()
    ambiguous = base.model_copy(
        update={
            "index_ciks": ("0000000001", CIK),
            "index_names": ("Co-registrant", "Wellchange Holdings Company Limited"),
        }
    )
    store = Store()
    store.claims.append(ClaimedFinancingJob(ambiguous, 1))
    worker = FinancingWorker(
        store=store,
        index_client=IndexClient(),
        sec_client=SecClient(),
        batch_size=1,
        now=lambda: NOW,
    )
    worker._process(store.claims.pop())
    assert store.failures == ["metadata_unavailable"]
