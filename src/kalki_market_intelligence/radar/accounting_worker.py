"""Private bounded worker for deterministic SEC accounting intelligence."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from kalki_market_intelligence.config import Settings
from kalki_market_intelligence.database import DatabaseOptions, DatabaseRuntime
from kalki_market_intelligence.forensics.accounting import (
    AccountingFilingReceipt,
    AccountingParseError,
    AccountingTier0Receipt,
    choose_accounting_tier,
    normalize_accounting_form,
)
from kalki_market_intelligence.providers.sec.accounting import (
    AccountingDiscoveryCandidate,
    AccountingNoSupportedEvents,
    SecAccountingIngestionService,
    accounting_filing_from_submissions,
)
from kalki_market_intelligence.providers.sec.accounting_store import (
    AccountingReplayConflict,
    ClaimedAccountingJob,
    PostgresAccountingStore,
)
from kalki_market_intelligence.providers.sec.client import (
    RateLimiter,
    SecClient,
    SecFetchedDocument,
    SecFetchedPrimaryDocument,
    SecProviderError,
)
from kalki_market_intelligence.providers.sec.contracts import SecFilingRecord
from kalki_market_intelligence.radar.accounting_source import parse_accounting_master_index
from kalki_market_intelligence.radar.filing_change_lifecycle import (
    FilingChangeLifecycleStore,
    observe_sec_primary_filing_change,
)
from kalki_market_intelligence.radar.sec_source import SecRadarClient, SecRadarDocument
from kalki_market_intelligence.radar.store import PostgresRadarStore


class AccountingIndexClient(Protocol):
    def latest_master_index(self, observed_on: date) -> SecRadarDocument: ...


class AccountingSecClient(Protocol):
    def fetch_submissions(self, cik: str | int) -> SecFetchedDocument: ...

    def fetch_primary_html_document(
        self,
        *,
        cik: str | int,
        accession_number: str,
        document_name: str,
    ) -> SecFetchedPrimaryDocument: ...


class AccountingWorkerStore(Protocol):
    def recover_stale(self, *, now: datetime, lease: timedelta = ...) -> int: ...

    def discover(
        self,
        candidates: tuple[AccountingDiscoveryCandidate, ...],
        *,
        maximum_backlog: int,
    ) -> int: ...

    def claim(self, *, now: datetime) -> ClaimedAccountingJob | None: ...

    def prior_receipts(
        self,
        *,
        issuer_cik: str,
        accepted_before: datetime,
        retrieved_by: datetime,
        limit: int = ...,
    ) -> tuple[AccountingFilingReceipt, ...]: ...

    def complete(
        self,
        claimed: ClaimedAccountingJob,
        receipt: AccountingFilingReceipt,
        routing: AccountingTier0Receipt,
        *,
        now: datetime,
    ) -> None: ...

    def complete_no_events(self, claimed: ClaimedAccountingJob, *, now: datetime) -> None: ...

    def fail(
        self,
        claimed: ClaimedAccountingJob,
        *,
        category: str,
        now: datetime,
        retry_delay: timedelta = ...,
    ) -> str: ...


class AccountingWorker:
    def __init__(
        self,
        *,
        store: AccountingWorkerStore,
        index_client: AccountingIndexClient,
        sec_client: AccountingSecClient,
        poll_seconds: int = 900,
        batch_size: int = 2,
        maximum_backlog: int = 250,
        filing_change_store: FilingChangeLifecycleStore | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not 300 <= poll_seconds <= 86_400:
            raise ValueError("accounting poll interval must be 300-86400 seconds")
        if not 1 <= batch_size <= 8:
            raise ValueError("accounting batch size must be 1-8")
        if not 1 <= maximum_backlog <= 1_000:
            raise ValueError("accounting backlog limit must be 1-1000")
        self._store = store
        self._index_client = index_client
        self._sec_client = sec_client
        self._poll_seconds = poll_seconds
        self._batch_size = batch_size
        self._maximum_backlog = maximum_backlog
        self._filing_change_store = filing_change_store
        self._now = now or (lambda: datetime.now(UTC))

    def run_once(self) -> int:
        observed = self._utc_now()
        self._store.recover_stale(now=observed)
        try:
            index = self._index_client.latest_master_index(observed.date())
            candidates = parse_accounting_master_index(index)
        except (SecProviderError, AccountingParseError):
            return self._poll_seconds
        self._store.discover(candidates, maximum_backlog=self._maximum_backlog)
        for _ in range(self._batch_size):
            claimed = self._store.claim(now=self._utc_now())
            if claimed is None:
                break
            self._process(claimed)
        return self._poll_seconds

    def _process(self, claimed: ClaimedAccountingJob) -> None:
        receipt, failure = self._resolve_receipt(claimed.candidate)
        if receipt is None:
            if failure == "no_supported_events":
                self._store.complete_no_events(claimed, now=self._utc_now())
            else:
                self._fail(claimed, failure)
            return
        try:
            self._store.complete(
                claimed,
                receipt,
                choose_accounting_tier(receipt),
                now=self._utc_now(),
            )
        except (AccountingReplayConflict, RuntimeError):
            self._fail(claimed, "persistence_error")
        except ValueError:
            self._fail(claimed, "other")

    def _resolve_receipt(
        self, candidate: AccountingDiscoveryCandidate
    ) -> tuple[AccountingFilingReceipt | None, str]:
        if len(candidate.index_ciks) != 1:
            return None, "metadata_unavailable"
        try:
            submissions = self._sec_client.fetch_submissions(candidate.index_ciks[0])
            metadata = accounting_filing_from_submissions(
                submissions,
                accession_number=candidate.accession_number,
            )
            if (
                metadata is None
                or normalize_accounting_form(metadata.filing.form) is not candidate.form
            ):
                return None, "metadata_unavailable"
            prior = self._store.prior_receipts(
                issuer_cik=metadata.filing.cik,
                accepted_before=metadata.filing.accepted_at,
                retrieved_by=submissions.retrieved_at,
            )
            receipt = SecAccountingIngestionService(self._sec_client).ingest(
                metadata,
                prior_receipts=prior,
                # The bounded prospective ledger is not a complete historical search.
                prior_search_complete=False,
                primary_document_observer=(
                    self._observe_filing_change if self._filing_change_store is not None else None
                ),
            )
        except AccountingNoSupportedEvents:
            return None, "no_supported_events"
        except SecProviderError:
            return None, "primary_document_error"
        except AccountingParseError:
            return None, "parse_error"
        except ValueError:
            return None, "other"
        except RuntimeError:
            return None, "persistence_error"
        if receipt.issuer_cik != candidate.index_ciks[0]:
            return None, "parse_error"
        return receipt, "other"

    def _observe_filing_change(
        self,
        filing: SecFilingRecord,
        document: SecFetchedPrimaryDocument,
    ) -> None:
        if self._filing_change_store is None:
            return
        observe_sec_primary_filing_change(self._filing_change_store, filing, document)

    def _fail(self, claimed: ClaimedAccountingJob, category: str) -> None:
        self._store.fail(
            claimed,
            category=category,
            now=self._utc_now(),
            retry_delay=timedelta(hours=1),
        )

    def _utc_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("accounting worker clock must be timezone-aware")
        return value.astimezone(UTC)


def accounting_worker_main() -> int:
    settings = Settings.load()
    if not settings.accounting_worker_enabled:
        print("Accounting worker is disabled.", file=sys.stderr)
        return 2
    if settings.database_password_file is None or settings.sec_user_agent is None:
        print("Accounting worker database secret or SEC identity is absent.", file=sys.stderr)
        return 2
    runtime = DatabaseRuntime(
        DatabaseOptions(
            host=settings.database_host,
            port=settings.database_port,
            name=settings.database_name,
            user=settings.database_user,
            password_file=settings.database_password_file,
            minimum_pool_size=settings.database_pool_minimum,
            maximum_pool_size=settings.database_pool_maximum,
        )
    )
    limiter = RateLimiter(settings.sec_requests_per_second)
    index_client = SecRadarClient(
        user_agent=settings.sec_user_agent,
        requests_per_second=settings.sec_requests_per_second,
        timeout_seconds=settings.sec_timeout_seconds,
        maximum_response_bytes=settings.sec_maximum_response_bytes,
        limiter=limiter,
    )
    sec_client = SecClient(
        user_agent=settings.sec_user_agent,
        requests_per_second=settings.sec_requests_per_second,
        timeout_seconds=settings.sec_timeout_seconds,
        maximum_response_bytes=settings.sec_maximum_response_bytes,
        limiter=limiter,
    )
    runtime.open()
    try:
        worker = AccountingWorker(
            store=PostgresAccountingStore(runtime.connection),
            filing_change_store=PostgresRadarStore(runtime.connection),
            index_client=index_client,
            sec_client=sec_client,
            poll_seconds=settings.accounting_worker_poll_seconds,
            batch_size=settings.accounting_worker_batch_size,
            maximum_backlog=settings.accounting_worker_maximum_backlog,
        )
        while True:
            time.sleep(worker.run_once())
    except KeyboardInterrupt:
        return 0
    finally:
        runtime.close()
