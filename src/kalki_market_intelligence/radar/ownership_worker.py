"""Private, bounded worker for deterministic SEC ownership intelligence."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from kalki_market_intelligence.config import Settings
from kalki_market_intelligence.database import DatabaseOptions, DatabaseRuntime
from kalki_market_intelligence.forensics import OwnershipTier0Receipt, choose_ownership_tier
from kalki_market_intelligence.forensics.contradiction_store import PostgresContradictionStore
from kalki_market_intelligence.forensics.convergence_producers import (
    ownership_convergence_decision,
)
from kalki_market_intelligence.forensics.convergence_service import ConvergenceValidationService
from kalki_market_intelligence.providers.sec.client import (
    RateLimiter,
    SecClient,
    SecFetchedDocument,
    SecFetchedPrimaryDocument,
    SecProviderError,
)
from kalki_market_intelligence.providers.sec.ownership import (
    OwnershipDiscoveryCandidate,
    OwnershipFilingReceipt,
    OwnershipForm,
    OwnershipIdentityMismatch,
    OwnershipParseError,
    SecOwnershipIngestionService,
    normalize_ownership_form,
    ownership_filing_from_submissions,
)
from kalki_market_intelligence.providers.sec.ownership_store import (
    ClaimedOwnershipJob,
    OwnershipReplayConflict,
    PostgresOwnershipStore,
)
from kalki_market_intelligence.radar.ownership_source import parse_ownership_master_index
from kalki_market_intelligence.radar.sec_source import SecRadarClient, SecRadarDocument


class OwnershipIndexClient(Protocol):
    def latest_master_index(self, observed_on: date) -> SecRadarDocument: ...


class OwnershipSecClient(Protocol):
    def fetch_submissions(self, cik: str | int) -> SecFetchedDocument: ...

    def fetch_primary_document(
        self,
        *,
        cik: str | int,
        accession_number: str,
        document_name: str,
    ) -> SecFetchedPrimaryDocument: ...


class OwnershipWorkerStore(Protocol):
    def recover_stale(self, *, now: datetime, lease: timedelta = ...) -> int: ...

    def discover(
        self,
        candidates: tuple[OwnershipDiscoveryCandidate, ...],
        *,
        maximum_backlog: int,
    ) -> int: ...

    def claim(self, *, now: datetime) -> ClaimedOwnershipJob | None: ...

    def previous_schedule_form(
        self,
        *,
        receipt: OwnershipFilingReceipt,
    ) -> OwnershipForm | None: ...

    def complete(
        self,
        claimed: ClaimedOwnershipJob,
        receipt: OwnershipFilingReceipt,
        routing: OwnershipTier0Receipt,
        *,
        now: datetime,
    ) -> None: ...

    def fail(
        self,
        claimed: ClaimedOwnershipJob,
        *,
        category: str,
        now: datetime,
        retry_delay: timedelta = ...,
    ) -> str: ...


class OwnershipWorker:
    """Poll one index and process only a small, separately persisted batch."""

    def __init__(
        self,
        *,
        store: OwnershipWorkerStore,
        index_client: OwnershipIndexClient,
        sec_client: OwnershipSecClient,
        poll_seconds: int = 900,
        batch_size: int = 2,
        maximum_backlog: int = 250,
        convergence_service: ConvergenceValidationService | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not 300 <= poll_seconds <= 86_400:
            raise ValueError("ownership poll interval must be 300-86400 seconds")
        if not 1 <= batch_size <= 8:
            raise ValueError("ownership batch size must be 1-8")
        if not 1 <= maximum_backlog <= 1_000:
            raise ValueError("ownership backlog limit must be 1-1000")
        self._store = store
        self._index_client = index_client
        self._sec_client = sec_client
        self._poll_seconds = poll_seconds
        self._batch_size = batch_size
        self._maximum_backlog = maximum_backlog
        self._convergence_service = convergence_service
        self._now = now or (lambda: datetime.now(UTC))

    def run_once(self) -> int:
        """Discover and process one bounded batch; failures remain private and closed."""

        observed = self._utc_now()
        self._store.recover_stale(now=observed)
        try:
            index = self._index_client.latest_master_index(observed.date())
        except SecProviderError:
            return self._poll_seconds
        try:
            candidates = parse_ownership_master_index(index)
        except OwnershipParseError:
            return self._poll_seconds
        self._store.discover(candidates, maximum_backlog=self._maximum_backlog)
        for _ in range(self._batch_size):
            claimed = self._store.claim(now=self._utc_now())
            if claimed is None:
                break
            self._process(claimed)
        return self._poll_seconds

    def _process(self, claimed: ClaimedOwnershipJob) -> None:
        receipt, failure = self._resolve_receipt(claimed.candidate)
        if receipt is None:
            self._fail(claimed, failure)
            return

        try:
            previous_form = self._store.previous_schedule_form(
                receipt=receipt,
            )
            routing = choose_ownership_tier(receipt, previous_schedule_form=previous_form)
            if self._convergence_service is not None:
                producer = ownership_convergence_decision(
                    receipt,
                    routing,
                    knowledge_cutoff_at=self._utc_now(),
                    previous_schedule_form=previous_form,
                )
                for request in producer.requests:
                    self._convergence_service.evaluate_and_persist(request)
            self._store.complete(claimed, receipt, routing, now=self._utc_now())
        except (OwnershipReplayConflict, RuntimeError):
            self._fail(claimed, "persistence_error")
        except ValueError:
            self._fail(claimed, "other")

    def _resolve_receipt(
        self, candidate: OwnershipDiscoveryCandidate
    ) -> tuple[OwnershipFilingReceipt | None, str]:
        """Resolve duplicate SEC index identities through authoritative primary metadata."""

        saw_primary_error = False
        saw_parse_error = False
        for index_cik in candidate.index_ciks:
            try:
                submissions = self._sec_client.fetch_submissions(index_cik)
                filing = ownership_filing_from_submissions(
                    submissions,
                    accession_number=candidate.accession_number,
                )
                if filing is None or normalize_ownership_form(filing.form) is not candidate.form:
                    continue
            except (SecProviderError, OwnershipParseError, ValueError):
                continue
            try:
                receipt = SecOwnershipIngestionService(self._sec_client).ingest(filing)
            except OwnershipIdentityMismatch:
                continue
            except OwnershipParseError:
                saw_parse_error = True
                continue
            except SecProviderError:
                saw_primary_error = True
                continue
            if receipt.issuer_cik not in candidate.index_ciks:
                saw_parse_error = True
                continue
            return receipt, "other"
        if saw_parse_error:
            return None, "parse_error"
        if saw_primary_error:
            return None, "primary_document_error"
        return None, "metadata_unavailable"

    def _fail(self, claimed: ClaimedOwnershipJob, category: str) -> None:
        self._store.fail(
            claimed,
            category=category,
            now=self._utc_now(),
            retry_delay=timedelta(hours=1),
        )

    def _utc_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ownership worker clock must be timezone-aware")
        return value.astimezone(UTC)


def ownership_worker_main() -> int:
    settings = Settings.load()
    if not settings.ownership_worker_enabled:
        print("Ownership worker is disabled.", file=sys.stderr)
        return 2
    if settings.database_password_file is None or settings.sec_user_agent is None:
        print("Ownership worker database secret or SEC identity is absent.", file=sys.stderr)
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
        worker = OwnershipWorker(
            store=PostgresOwnershipStore(runtime.connection),
            convergence_service=ConvergenceValidationService(
                PostgresContradictionStore(runtime.connection)
            ),
            index_client=index_client,
            sec_client=sec_client,
            poll_seconds=settings.ownership_worker_poll_seconds,
            batch_size=settings.ownership_worker_batch_size,
            maximum_backlog=settings.ownership_worker_maximum_backlog,
        )
        while True:
            time.sleep(worker.run_once())
    except KeyboardInterrupt:
        return 0
    finally:
        runtime.close()
