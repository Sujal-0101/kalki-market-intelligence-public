"""Credential-gated worker for restart-safe supporting publication outcomes."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from kalki_market_intelligence.config import Settings
from kalki_market_intelligence.contracts.domain import CurrencyCode
from kalki_market_intelligence.database import DatabaseOptions, DatabaseRuntime, read_secret_file
from kalki_market_intelligence.prospective.calendar import ExchangeSessionPlanner
from kalki_market_intelligence.prospective.contracts import (
    AttemptStatus,
    ClaimedProspectiveOutcome,
    OutcomeHorizon,
    OutcomeObservationSet,
    ProspectiveOutcome,
    ProspectiveOutcomeAttempt,
    ProspectiveOutcomePlan,
    ProspectivePublication,
    SupportingBarBatch,
    SupportingBarRequest,
    SupportingDailyBar,
)
from kalki_market_intelligence.prospective.engine import ProspectiveOutcomeEvaluator
from kalki_market_intelligence.prospective.provider import (
    ProspectiveMarketDataProvider,
    ProviderHttpError,
    ProviderTransportError,
    SupportingProviderError,
    TwelveDataSupportingProvider,
)
from kalki_market_intelligence.prospective.store import PostgresProspectiveOutcomeStore


class ProspectiveStore(Protocol):
    def publications_for_enrollment(
        self, *, limit: int = 100
    ) -> tuple[ProspectivePublication, ...]: ...

    def enroll(self, plan: ProspectiveOutcomePlan, *, now: datetime) -> bool: ...

    def claim_due(self, *, now: datetime) -> ClaimedProspectiveOutcome | None: ...

    def attempts_for_plan(self, plan_id: UUID) -> tuple[ProspectiveOutcomeAttempt, ...]: ...

    def retry_with_attempt(
        self,
        plan_id: UUID,
        attempt: ProspectiveOutcomeAttempt,
        *,
        now: datetime,
        next_attempt_at: datetime,
    ) -> None: ...

    def complete_with_attempt(
        self,
        outcome: ProspectiveOutcome,
        attempt: ProspectiveOutcomeAttempt,
    ) -> None: ...

    def requeue_stale(self, *, now: datetime, lease_seconds: int = 900) -> int: ...


class ProspectiveOutcomeWorker:
    def __init__(
        self,
        *,
        store: ProspectiveStore,
        provider: ProspectiveMarketDataProvider,
        batch_size: int = 8,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not 1 <= batch_size <= 50:
            raise ValueError("prospective outcome batch size must be 1-50")
        self._store = store
        self._provider = provider
        self._batch_size = batch_size
        self._now = now or (lambda: datetime.now(UTC))
        self._planner = ExchangeSessionPlanner()
        self._evaluator = ProspectiveOutcomeEvaluator()

    def run_once(self) -> tuple[int, int]:
        now = self._utc_now()
        self._store.requeue_stale(now=now)
        enrolled = self._enroll_publications(now=now)
        processed = 0
        for _ in range(self._batch_size):
            claimed = self._store.claim_due(now=self._utc_now())
            if claimed is None:
                break
            self._process(claimed)
            processed += 1
        return enrolled, processed

    def _enroll_publications(self, *, now: datetime) -> int:
        enrolled = 0
        for publication in self._store.publications_for_enrollment():
            mapping = _map_us_listing(publication)
            if mapping is None:
                continue
            assert publication.ticker is not None
            asset_mic, calendar_name = mapping
            for horizon in OutcomeHorizon:
                plan = self._planner.plan(
                    publication_id=publication.publication_id,
                    published_at=publication.published_at,
                    asset_symbol=publication.ticker,
                    asset_mic=asset_mic,
                    benchmark_symbol="SPY",
                    benchmark_mic="ARCX",
                    calendar_name=calendar_name,
                    currency=CurrencyCode.US_DOLLAR,
                    enrolled_at=now,
                    horizon=horizon,
                )
                enrolled += int(self._store.enroll(plan, now=now))
        return enrolled

    def _process(self, claimed: ClaimedProspectiveOutcome) -> None:
        started_at = self._utc_now()
        asset: SupportingBarBatch | None = None
        try:
            asset = self._provider.get_daily_bars(_bar_request(claimed.plan, asset=True))
            benchmark = self._provider.get_daily_bars(_bar_request(claimed.plan, asset=False))
        except SupportingProviderError as error:
            retryable = not isinstance(error, ProviderHttpError) or error.retryable
            if isinstance(error, ProviderTransportError):
                retryable = True
            self._finish_failure(
                claimed,
                started_at=started_at,
                error_code=type(error).__name__,
                retryable=retryable,
                response_hashes=(asset.response_sha256,) if asset is not None else (),
                response_rows=len(asset.bars) if asset is not None else 0,
            )
            return
        observations = _observations(claimed.plan, asset, benchmark)
        missing = any(
            item is None
            for item in (
                observations.asset_reference,
                observations.asset_target,
                observations.benchmark_reference,
                observations.benchmark_target,
            )
        )
        completed_at = self._utc_now()
        if missing:
            self._finish_failure(
                claimed,
                started_at=started_at,
                error_code="provider_observation_missing",
                retryable=True,
                observations=observations,
                response_hashes=(asset.response_sha256, benchmark.response_sha256),
                response_rows=len(asset.bars) + len(benchmark.bars),
            )
            return
        receipt = ProspectiveOutcomeAttempt(
            attempt_id=uuid4(),
            publication_id=claimed.plan.publication_id,
            horizon=claimed.plan.horizon,
            attempt_number=claimed.attempt_number,
            started_at=started_at,
            completed_at=completed_at,
            status=AttemptStatus.SUCCEEDED,
            response_sha256=(asset.response_sha256, benchmark.response_sha256),
            response_row_count=len(asset.bars) + len(benchmark.bars),
        )
        attempts = self._store.attempts_for_plan(claimed.plan_id) + (receipt,)
        outcome = self._evaluator.evaluate(
            plan=claimed.plan,
            observations=observations,
            attempts=attempts,
            evaluated_at=completed_at,
            appended_at=completed_at,
        )
        self._store.complete_with_attempt(outcome, receipt)

    def _finish_failure(
        self,
        claimed: ClaimedProspectiveOutcome,
        *,
        started_at: datetime,
        error_code: str,
        retryable: bool,
        observations: OutcomeObservationSet | None = None,
        response_hashes: tuple[str, ...] = (),
        response_rows: int = 0,
    ) -> None:
        completed_at = self._utc_now()
        terminal = not retryable or claimed.attempt_number >= 6
        receipt = ProspectiveOutcomeAttempt(
            attempt_id=uuid4(),
            publication_id=claimed.plan.publication_id,
            horizon=claimed.plan.horizon,
            attempt_number=claimed.attempt_number,
            started_at=started_at,
            completed_at=completed_at,
            status=(
                AttemptStatus.TERMINAL_FAILURE if terminal else AttemptStatus.RETRYABLE_FAILURE
            ),
            response_sha256=response_hashes,
            response_row_count=response_rows,
            error_code=error_code,
        )
        if not terminal:
            delay_seconds = min(86_400, 300 * (2 ** (claimed.attempt_number - 1)))
            self._store.retry_with_attempt(
                claimed.plan_id,
                receipt,
                now=completed_at,
                next_attempt_at=completed_at + timedelta(seconds=delay_seconds),
            )
            return
        attempts = self._store.attempts_for_plan(claimed.plan_id) + (receipt,)
        outcome = self._evaluator.evaluate(
            plan=claimed.plan,
            observations=observations
            or OutcomeObservationSet(
                asset_reference=None,
                asset_target=None,
                benchmark_reference=None,
                benchmark_target=None,
            ),
            attempts=attempts,
            evaluated_at=completed_at,
            appended_at=completed_at,
        )
        self._store.complete_with_attempt(outcome, receipt)

    def _utc_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("prospective outcome worker clock must be timezone-aware")
        return value.astimezone(UTC)


def _map_us_listing(publication: ProspectivePublication) -> tuple[str, str] | None:
    if publication.ticker is None or publication.exchange is None:
        return None
    exchange = publication.exchange.casefold().replace(" ", "")
    mic = {
        "nasdaq": "XNAS",
        "nyse": "XNYS",
        "nysearca": "ARCX",
        "nyseamerican": "XASE",
    }.get(exchange)
    return (mic, "XNYS") if mic is not None else None


def _bar_request(plan: ProspectiveOutcomePlan, *, asset: bool) -> SupportingBarRequest:
    return SupportingBarRequest(
        symbol=plan.asset_symbol if asset else plan.benchmark_symbol,
        mic=plan.asset_mic if asset else plan.benchmark_mic,
        start_date=plan.reference_session_date,
        end_date=plan.target_session_date,
        currency=plan.currency,
    )


def _observations(
    plan: ProspectiveOutcomePlan,
    asset: SupportingBarBatch,
    benchmark: SupportingBarBatch,
) -> OutcomeObservationSet:
    return OutcomeObservationSet(
        asset_reference=_bar_on(asset, plan.reference_session_date),
        asset_target=_bar_on(asset, plan.target_session_date),
        benchmark_reference=_bar_on(benchmark, plan.reference_session_date),
        benchmark_target=_bar_on(benchmark, plan.target_session_date),
    )


def _bar_on(batch: SupportingBarBatch, session_date: object) -> SupportingDailyBar | None:
    return next((bar for bar in batch.bars if bar.session_date == session_date), None)


def prospective_worker_main() -> int:
    settings = Settings.load()
    if not settings.prospective_outcomes_enabled:
        print("Prospective outcome worker is disabled.", file=sys.stderr)
        return 2
    assert settings.twelve_data_api_key_file is not None
    assert settings.database_password_file is not None
    api_key = read_secret_file(settings.twelve_data_api_key_file, label="Twelve Data API key")
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
    runtime.open()
    try:
        worker = ProspectiveOutcomeWorker(
            store=PostgresProspectiveOutcomeStore(runtime.connection),
            provider=TwelveDataSupportingProvider(api_key=api_key),
            batch_size=settings.prospective_outcomes_batch_size,
        )
        while True:
            worker.run_once()
            time.sleep(settings.prospective_outcomes_poll_seconds)
    except KeyboardInterrupt:
        return 0
    finally:
        runtime.close()
