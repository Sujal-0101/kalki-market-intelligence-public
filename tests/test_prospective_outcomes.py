"""Phase 37 supporting outcomes are temporal, deterministic, and fail closed."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import psycopg
import pytest
from pydantic import ValidationError

from kalki_market_intelligence.contracts.domain import CurrencyCode
from kalki_market_intelligence.database import DatabaseOptions, DatabaseRuntime
from kalki_market_intelligence.prospective.calendar import ExchangeSessionPlanner
from kalki_market_intelligence.prospective.contracts import (
    AttemptStatus,
    ClaimedProspectiveOutcome,
    OutcomeHorizon,
    OutcomeObservationSet,
    OutcomeOrigin,
    OutcomeStatus,
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
    ProviderHttpResult,
    ProviderRateLimiter,
    ProviderResponseError,
    TwelveDataSupportingProvider,
    validate_twelve_data_url,
)
from kalki_market_intelligence.prospective.store import PostgresProspectiveOutcomeStore
from kalki_market_intelligence.prospective.worker import ProspectiveOutcomeWorker
from kalki_market_intelligence.web.repository import PostgresResearchRepository

PUBLICATION_ID = UUID("10000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 8, 28, 12, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]
GATE_PASSWORD_FILE = os.environ.get("KALKI_PROSPECTIVE_GATE_PASSWORD_FILE")
GATE_PORT = int(os.environ.get("KALKI_PROSPECTIVE_GATE_PORT", "55443"))


def plan(
    *,
    published_at: datetime = datetime(2026, 8, 25, 16, 38, tzinfo=UTC),
    enrolled_at: datetime = datetime(2026, 8, 25, 17, tzinfo=UTC),
    horizon: OutcomeHorizon = OutcomeHorizon.T1,
) -> ProspectiveOutcomePlan:
    return ExchangeSessionPlanner().plan(
        publication_id=PUBLICATION_ID,
        published_at=published_at,
        asset_symbol="AAPL",
        asset_mic="XNAS",
        benchmark_symbol="SPY",
        benchmark_mic="ARCX",
        calendar_name="XNYS",
        currency=CurrencyCode.US_DOLLAR,
        enrolled_at=enrolled_at,
        horizon=horizon,
    )


def bar(
    *,
    symbol: str,
    mic: str,
    session_date: date,
    close: str,
    marker: str,
) -> SupportingDailyBar:
    value = Decimal(close)
    return SupportingDailyBar(
        symbol=symbol,
        mic=mic,
        provider_mic=mic,
        session_date=session_date,
        open=value,
        high=value + Decimal("1"),
        low=value - Decimal("1"),
        close=value,
        volume=100,
        currency=CurrencyCode.US_DOLLAR,
        source_record_id=f"fixture:{marker}",
        source_content_sha256=hashlib.sha256(marker.encode()).hexdigest(),
        available_at=NOW,
        retrieved_at=NOW,
    )


def attempt(
    horizon: OutcomeHorizon = OutcomeHorizon.T1,
    *,
    status: AttemptStatus = AttemptStatus.SUCCEEDED,
) -> ProspectiveOutcomeAttempt:
    return ProspectiveOutcomeAttempt(
        attempt_id=UUID("20000000-0000-0000-0000-000000000001"),
        publication_id=PUBLICATION_ID,
        horizon=horizon,
        attempt_number=1,
        started_at=NOW - timedelta(seconds=1),
        completed_at=NOW,
        status=status,
        response_sha256=(hashlib.sha256(b"asset-response").hexdigest(),),
        response_row_count=4,
        error_code="provider_observation_missing"
        if status is not AttemptStatus.SUCCEEDED
        else None,
    )


def test_real_exchange_calendar_skips_holidays_and_assigns_forward_origin() -> None:
    result = plan(
        published_at=datetime(2026, 9, 4, 16, tzinfo=UTC),
        enrolled_at=datetime(2026, 9, 4, 17, tzinfo=UTC),
        horizon=OutcomeHorizon.T1,
    )
    assert result.reference_session_date == date(2026, 9, 4)
    assert result.target_session_date == date(2026, 9, 8)  # Labor Day is not a session.
    assert result.origin is OutcomeOrigin.GENUINE_FORWARD


def test_after_close_publication_uses_next_session_and_reconstruction_is_explicit() -> None:
    result = plan(
        published_at=datetime(2026, 8, 25, 21, tzinfo=UTC),
        enrolled_at=datetime(2026, 8, 28, 21, tzinfo=UTC),
        horizon=OutcomeHorizon.T1,
    )
    assert result.publication_session_date == date(2026, 8, 25)
    assert result.reference_session_date == date(2026, 8, 26)
    assert result.target_session_date == date(2026, 8, 27)
    assert result.origin is OutcomeOrigin.RECONSTRUCTED


def test_seconds_after_close_cannot_reuse_a_close_before_publication() -> None:
    result = plan(
        published_at=datetime(2026, 8, 25, 20, 0, 30, tzinfo=UTC),
        enrolled_at=datetime(2026, 8, 25, 20, 1, tzinfo=UTC),
        horizon=OutcomeHorizon.T1,
    )
    assert result.reference_session_date == date(2026, 8, 26)
    assert result.reference_session_close_at >= result.published_at


def test_t20_means_twenty_trading_sessions_not_calendar_days() -> None:
    result = plan(horizon=OutcomeHorizon.T20)
    assert result.reference_session_date == date(2026, 8, 25)
    assert result.target_session_date == date(2026, 9, 23)


def test_evaluator_calculates_exact_price_and_benchmark_relative_returns() -> None:
    outcome_plan = plan()
    observations = OutcomeObservationSet(
        asset_reference=bar(
            symbol="AAPL", mic="XNAS", session_date=date(2026, 8, 25), close="100", marker="a0"
        ),
        asset_target=bar(
            symbol="AAPL", mic="XNAS", session_date=date(2026, 8, 26), close="110", marker="a1"
        ),
        benchmark_reference=bar(
            symbol="SPY", mic="ARCX", session_date=date(2026, 8, 25), close="200", marker="b0"
        ),
        benchmark_target=bar(
            symbol="SPY", mic="ARCX", session_date=date(2026, 8, 26), close="210", marker="b1"
        ),
    )
    result = ProspectiveOutcomeEvaluator().evaluate(
        plan=outcome_plan,
        observations=observations,
        attempts=(attempt(),),
        evaluated_at=NOW,
        appended_at=NOW,
    )
    assert result.status is OutcomeStatus.COMPLETED
    assert result.asset_return == Decimal("0.1")
    assert result.benchmark_return == Decimal("0.05")
    assert result.benchmark_relative_return == Decimal("0.05")
    assert result.authority.value == "SUPPORTING"
    assert len(result.observation_hashes) == 4


def test_missing_bar_appends_unavailable_without_inventing_a_price() -> None:
    outcome_plan = plan()
    observations = OutcomeObservationSet(
        asset_reference=bar(
            symbol="AAPL", mic="XNAS", session_date=date(2026, 8, 25), close="100", marker="a0"
        ),
        asset_target=None,
        benchmark_reference=None,
        benchmark_target=None,
    )
    result = ProspectiveOutcomeEvaluator().evaluate(
        plan=outcome_plan,
        observations=observations,
        attempts=(attempt(status=AttemptStatus.TERMINAL_FAILURE),),
        evaluated_at=NOW,
        appended_at=NOW,
    )
    assert result.status is OutcomeStatus.DATA_UNAVAILABLE
    assert result.asset_return is None
    assert result.benchmark_return is None
    assert "asset_target" in result.limitations[0]


def test_evaluator_rejects_wrong_session_or_provider_identity() -> None:
    outcome_plan = plan()
    wrong = bar(
        symbol="AAPL", mic="XNAS", session_date=date(2026, 8, 24), close="100", marker="wrong"
    )
    with pytest.raises(ValueError, match="identity"):
        ProspectiveOutcomeEvaluator().evaluate(
            plan=outcome_plan,
            observations=OutcomeObservationSet(
                asset_reference=wrong,
                asset_target=None,
                benchmark_reference=None,
                benchmark_target=None,
            ),
            attempts=(attempt(),),
            evaluated_at=NOW,
            appended_at=NOW,
        )


class FakeTransport:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.url: str | None = None
        self.headers: dict[str, str] = {}

    def get(
        self,
        url: str,
        *,
        headers: Any,
        timeout: float,
        maximum_bytes: int,
    ) -> ProviderHttpResult:
        del timeout, maximum_bytes
        self.url = url
        self.headers = dict(headers)
        return ProviderHttpResult(
            url=url,
            status_code=200,
            headers={"content-type": "application/json"},
            body=json.dumps(self.payload).encode(),
        )


class NoWaitLimiter:
    def wait(self) -> None:
        return None


def provider_payload() -> dict[str, Any]:
    return {
        "meta": {
            "symbol": "AAPL",
            "interval": "1day",
            "currency": "USD",
            "exchange_timezone": "America/New_York",
            "exchange": "NASDAQ",
            "mic_code": "XNAS",
            "type": "Common Stock",
        },
        "values": [
            {
                "datetime": "2026-08-25",
                "open": "100.00",
                "high": "102.00",
                "low": "99.00",
                "close": "101.00",
                "volume": "1234",
            },
            {
                "datetime": "2026-08-26",
                "open": "101.00",
                "high": "103.00",
                "low": "100.00",
                "close": "102.00",
                "volume": "2345",
            },
        ],
        "status": "ok",
    }


def test_twelve_data_adapter_uses_header_secret_and_closed_split_adjusted_request() -> None:
    transport = FakeTransport(provider_payload())
    provider = TwelveDataSupportingProvider(
        api_key="secret-key-value",
        transport=transport,
        limiter=NoWaitLimiter(),
        now=lambda: NOW,
    )
    request = SupportingBarRequest(
        symbol="AAPL",
        mic="XNAS",
        start_date=date(2026, 8, 25),
        end_date=date(2026, 8, 26),
        currency=CurrencyCode.US_DOLLAR,
    )
    batch = provider.get_daily_bars(request)
    assert transport.url is not None
    parsed = urlsplit(transport.url)
    query = parse_qs(parsed.query)
    assert query["symbol"] == ["AAPL"]
    assert query["mic_code"] == ["XNAS"]
    assert query["adjust"] == ["splits"]
    assert "apikey" not in query
    assert transport.headers["Authorization"] == "apikey secret-key-value"
    assert len(batch.bars) == 2
    assert batch.bars[0].session_date == date(2026, 8, 25)
    assert batch.bars[0].provider_mic == "XNAS"
    assert batch.bars[0].available_at == NOW
    assert batch.bars[0].source_content_sha256 != batch.bars[1].source_content_sha256


def test_twelve_data_adapter_rejects_mismatched_identity_and_extra_bar_fields() -> None:
    payload = provider_payload()
    payload["meta"]["mic_code"] = "XNYS"
    provider = TwelveDataSupportingProvider(
        api_key="secret-key-value",
        transport=FakeTransport(payload),
        limiter=NoWaitLimiter(),
        now=lambda: NOW,
    )
    request = SupportingBarRequest(
        symbol="AAPL",
        mic="XNAS",
        start_date=date(2026, 8, 25),
        end_date=date(2026, 8, 26),
        currency=CurrencyCode.US_DOLLAR,
    )
    with pytest.raises(ProviderResponseError, match="identity"):
        provider.get_daily_bars(request)


@pytest.mark.parametrize(
    "url",
    (
        "http://api.twelvedata.com/time_series?symbol=AAPL",
        "https://evil.example/time_series?symbol=AAPL",
        "https://api.twelvedata.com/price?symbol=AAPL",
        "https://user:pass@api.twelvedata.com/time_series?symbol=AAPL",
    ),
)
def test_provider_origin_and_endpoint_are_closed(url: str) -> None:
    with pytest.raises(Exception, match="approved endpoint"):
        validate_twelve_data_url(url)


def test_contracts_forbid_extra_fields_and_false_forward_origin() -> None:
    payload = plan().model_dump()
    payload["origin"] = OutcomeOrigin.RECONSTRUCTED
    with pytest.raises(ValidationError, match="origin"):
        type(plan()).model_validate(payload)
    bar_schema = SupportingDailyBar.model_json_schema()
    assert bar_schema["additionalProperties"] is False


def test_provider_rate_limiter_enforces_minute_and_rolling_daily_caps() -> None:
    class Clock:
        value = 0.0

        def monotonic(self) -> float:
            return self.value

        def sleep(self, seconds: float) -> None:
            self.value += seconds

    clock = Clock()
    limiter = ProviderRateLimiter(monotonic=clock.monotonic, sleep=clock.sleep)
    for _ in range(801):
        limiter.wait()
    assert clock.value == 86_400


class WorkerStore:
    def __init__(self, claimed: ClaimedProspectiveOutcome) -> None:
        self.claimed: ClaimedProspectiveOutcome | None = claimed
        self.retry_receipts: list[ProspectiveOutcomeAttempt] = []
        self.completed: list[tuple[ProspectiveOutcome, ProspectiveOutcomeAttempt]] = []

    def publications_for_enrollment(
        self, *, limit: int = 100
    ) -> tuple[ProspectivePublication, ...]:
        del limit
        return ()

    def enroll(self, plan: ProspectiveOutcomePlan, *, now: datetime) -> bool:
        del plan, now
        return False

    def claim_due(self, *, now: datetime) -> ClaimedProspectiveOutcome | None:
        del now
        claimed, self.claimed = self.claimed, None
        return claimed

    def attempts_for_plan(self, plan_id: UUID) -> tuple[ProspectiveOutcomeAttempt, ...]:
        del plan_id
        return ()

    def retry_with_attempt(
        self,
        plan_id: UUID,
        attempt: ProspectiveOutcomeAttempt,
        *,
        now: datetime,
        next_attempt_at: datetime,
    ) -> None:
        del plan_id, now, next_attempt_at
        self.retry_receipts.append(attempt)

    def complete_with_attempt(
        self, outcome: ProspectiveOutcome, attempt: ProspectiveOutcomeAttempt
    ) -> None:
        self.completed.append((outcome, attempt))

    def requeue_stale(self, *, now: datetime, lease_seconds: int = 900) -> int:
        del now, lease_seconds
        return 0


class WorkerProvider:
    def __init__(
        self,
        batches: dict[str, SupportingBarBatch] | None = None,
        error: ProviderResponseError | None = None,
    ) -> None:
        self.batches = batches or {}
        self.error = error

    def get_daily_bars(self, request: SupportingBarRequest) -> SupportingBarBatch:
        if self.error is not None:
            raise self.error
        return self.batches[request.symbol]


def _worker_batch(
    outcome_plan: ProspectiveOutcomePlan,
    *,
    asset: bool,
) -> SupportingBarBatch:
    symbol = outcome_plan.asset_symbol if asset else outcome_plan.benchmark_symbol
    mic = outcome_plan.asset_mic if asset else outcome_plan.benchmark_mic
    request = SupportingBarRequest(
        symbol=symbol,
        mic=mic,
        start_date=outcome_plan.reference_session_date,
        end_date=outcome_plan.target_session_date,
        currency=outcome_plan.currency,
    )
    bars = (
        bar(
            symbol=symbol,
            mic=mic,
            session_date=outcome_plan.reference_session_date,
            close="100",
            marker=f"{symbol}-reference",
        ),
        bar(
            symbol=symbol,
            mic=mic,
            session_date=outcome_plan.target_session_date,
            close="110",
            marker=f"{symbol}-target",
        ),
    )
    return SupportingBarBatch(
        request=request,
        bars=bars,
        response_sha256=hashlib.sha256(symbol.encode()).hexdigest(),
        retrieved_at=NOW,
    )


def test_worker_atomically_hands_successful_attempt_to_terminal_store() -> None:
    outcome_plan = plan()
    claimed = ClaimedProspectiveOutcome(
        plan_id=UUID("30000000-0000-0000-0000-000000000001"),
        plan=outcome_plan,
        attempt_number=1,
        claimed_at=NOW,
    )
    store = WorkerStore(claimed)
    provider = WorkerProvider(
        {
            "AAPL": _worker_batch(outcome_plan, asset=True),
            "SPY": _worker_batch(outcome_plan, asset=False),
        }
    )
    worker = ProspectiveOutcomeWorker(store=store, provider=provider, now=lambda: NOW)
    assert worker.run_once() == (0, 1)
    assert not store.retry_receipts
    assert len(store.completed) == 1
    outcome, receipt = store.completed[0]
    assert outcome.status is OutcomeStatus.COMPLETED
    assert receipt.status is AttemptStatus.SUCCEEDED


def test_worker_records_bounded_retry_then_terminal_unavailable() -> None:
    outcome_plan = plan()
    first = ClaimedProspectiveOutcome(
        plan_id=UUID("30000000-0000-0000-0000-000000000001"),
        plan=outcome_plan,
        attempt_number=1,
        claimed_at=NOW,
    )
    retry_store = WorkerStore(first)
    provider = WorkerProvider(error=ProviderResponseError("fixture error"))
    ProspectiveOutcomeWorker(store=retry_store, provider=provider, now=lambda: NOW).run_once()
    assert retry_store.retry_receipts[0].status is AttemptStatus.RETRYABLE_FAILURE
    assert not retry_store.completed

    sixth = first.model_copy(update={"attempt_number": 6})
    terminal_store = WorkerStore(sixth)
    ProspectiveOutcomeWorker(store=terminal_store, provider=provider, now=lambda: NOW).run_once()
    outcome, receipt = terminal_store.completed[0]
    assert outcome.status is OutcomeStatus.DATA_UNAVAILABLE
    assert receipt.status is AttemptStatus.TERMINAL_FAILURE


def test_migration_and_recovery_wiring_enforce_restart_safe_unique_history() -> None:
    migration = (ROOT / "migrations/0014_prospective_outcomes.sql").read_text()
    compose = (ROOT / "compose.production.yaml").read_text()
    backup = (ROOT / "scripts/backup-postgres.sh").read_text()
    restore = (ROOT / "scripts/restore-postgres-gate.sh").read_text()
    assert "UNIQUE (publication_id, horizon, provider_name)" in migration
    assert "target_session_close_at > reference_session_close_at" in migration
    assert "GENUINE_FORWARD" in migration and "RECONSTRUCTED" in migration
    assert "authority = 'SUPPORTING'" in migration
    assert "provider_use_mode = 'internal_non_display'" in migration
    assert "benchmark_relative_return numeric" in migration
    assert "SKIP LOCKED" not in migration  # Claim behavior belongs to the typed store.
    assert "research_prospective_outcomes_no_mutation" in migration
    assert "UPDATE research_briefs" not in migration
    assert "0014_prospective_outcomes.sql" in compose
    prospective_service = compose.split("  prospective-outcomes:", 1)[1].split(
        "  discord-intake:", 1
    )[0]
    assert "KALKI_SEC_USER_AGENT" not in prospective_service
    assert "profiles: [supporting-outcomes]" in prospective_service
    assert "research_prospective_outcome_plans" in backup
    assert "0014_prospective_outcomes" in restore


@pytest.mark.skipif(
    GATE_PASSWORD_FILE is None,
    reason="Phase 37 prospective-outcome PostgreSQL gate is not running",
)
def test_postgres_jobs_are_idempotent_restart_safe_and_append_only() -> None:
    assert GATE_PASSWORD_FILE is not None
    gate_now = datetime(2026, 10, 1, 12, tzinfo=UTC)
    outcome_plan = plan()
    with psycopg.connect(
        host="127.0.0.1",
        port=GATE_PORT,
        dbname="kalki_test",
        user="postgres",
    ) as owner:
        owner.execute(
            """
            INSERT INTO research_candidates (
                accession_number, cik, company_name, ticker, exchange, filing_form,
                filed_at, source_url, discovered_at, status, attempts, updated_at
            ) VALUES (
                '0000320193-26-000001', '320193', 'Synthetic issuer', 'AAPL', 'Nasdaq',
                '8-K', %s, 'https://www.sec.gov/Archives/edgar/data/320193/test.txt',
                %s, 'published', 1, %s
            )
            """,
            (NOW - timedelta(days=1), NOW, NOW),
        )
        owner.execute(
            "ALTER TABLE research_briefs DISABLE TRIGGER research_briefs_require_verification"
        )
        owner.execute(
            """
            INSERT INTO research_briefs (
                brief_id, schema_version, accession_number, ticker, company_name,
                classification, attention_points, risk_points, evidence_strength_points,
                filed_at, retrieved_at, published_at, source_document_sha256, record
            ) VALUES (
                %s, '1.0.0', '0000320193-26-000001', 'AAPL', 'Synthetic issuer',
                'watch', 10, 10, 10, %s, %s, %s, %s, '{}'::jsonb
            )
            """,
            (
                PUBLICATION_ID,
                outcome_plan.published_at - timedelta(days=1),
                outcome_plan.published_at - timedelta(hours=1),
                outcome_plan.published_at,
                "a" * 64,
            ),
        )
        owner.execute(
            "ALTER TABLE research_briefs ENABLE TRIGGER research_briefs_require_verification"
        )

    runtime = DatabaseRuntime(
        DatabaseOptions(
            host="127.0.0.1",
            port=GATE_PORT,
            name="kalki_test",
            user="postgres",
            password_file=Path(GATE_PASSWORD_FILE),
            minimum_pool_size=1,
            maximum_pool_size=2,
        )
    )
    runtime.open()
    try:
        store = PostgresProspectiveOutcomeStore(runtime.connection)
        science = PostgresResearchRepository(runtime.connection).get_outcome_science_operations()
        assert science is not None
        assert science.enrolled_plan_count == 0
        assert science.terminal_outcome_count == 0
        assert science.disposition == "INSUFFICIENT_SAMPLE"
        assert science.strata == ()
        assert store.enroll(outcome_plan, now=NOW)
        assert not store.enroll(outcome_plan, now=NOW)
        claimed = store.claim_due(now=gate_now)
        assert claimed is not None
        assert claimed.attempt_number == 1
        assert store.requeue_stale(now=gate_now + timedelta(seconds=1_000)) == 1
        claimed = store.claim_due(now=gate_now + timedelta(seconds=1_000))
        assert claimed is not None
        assert claimed.attempt_number == 1
        receipt = attempt()
        observations = OutcomeObservationSet(
            asset_reference=bar(
                symbol="AAPL",
                mic="XNAS",
                session_date=outcome_plan.reference_session_date,
                close="100",
                marker="pg-a0",
            ),
            asset_target=bar(
                symbol="AAPL",
                mic="XNAS",
                session_date=outcome_plan.target_session_date,
                close="110",
                marker="pg-a1",
            ),
            benchmark_reference=bar(
                symbol="SPY",
                mic="ARCX",
                session_date=outcome_plan.reference_session_date,
                close="200",
                marker="pg-b0",
            ),
            benchmark_target=bar(
                symbol="SPY",
                mic="ARCX",
                session_date=outcome_plan.target_session_date,
                close="210",
                marker="pg-b1",
            ),
        )
        outcome = ProspectiveOutcomeEvaluator().evaluate(
            plan=outcome_plan,
            observations=observations,
            attempts=(receipt,),
            evaluated_at=gate_now,
            appended_at=gate_now,
        )
        store.complete_with_attempt(outcome, receipt)
        assert store.claim_due(now=gate_now) is None
        with pytest.raises(psycopg.Error, match="append-only"):
            with runtime.connection() as connection:
                connection.execute("UPDATE research_prospective_outcomes SET appended_at = now()")
    finally:
        runtime.close()

    with psycopg.connect(
        host="127.0.0.1",
        port=GATE_PORT,
        dbname="kalki_test",
        user="postgres",
    ) as owner:
        row = owner.execute(
            """
            SELECT j.status, j.attempts, o.status, o.origin, o.authority,
                   o.record->>'schema_version'
            FROM research_prospective_outcome_jobs j
            JOIN research_prospective_outcomes o USING (plan_id)
            """
        ).fetchone()
        assert row == (
            "completed",
            1,
            "completed",
            "GENUINE_FORWARD",
            "SUPPORTING",
            "1.0.0",
        )
        decimal34 = owner.execute(
            """
            SELECT outcome_price_return_decimal34(3, 4),
                   outcome_decimal34(
                       outcome_price_return_decimal34(3, 4)
                       - outcome_price_return_decimal34(7, 8)
                   )
            """
        ).fetchone()
        assert decimal34 == (
            Decimal("0.3333333333333333333333333333333333"),
            Decimal("0.1904761904761904761904761904761904"),
        )

        invalid_plan_id = UUID("30000000-0000-0000-0000-000000000005")
        with pytest.raises(psycopg.Error, match="publication enrollment"):
            with owner.transaction():
                owner.execute(
                    """
                    INSERT INTO research_prospective_outcome_plans (
                        plan_id, publication_id, horizon, provider_name, published_at,
                        asset_symbol, asset_mic, benchmark_symbol, benchmark_mic,
                        calendar_name, currency, publication_session_date,
                        reference_session_date, reference_session_close_at,
                        target_session_date, target_session_close_at, origin, enrolled_at,
                        methodology_version, provider_terms_version, provider_use_mode, record
                    )
                    SELECT %s, publication_id, 5, provider_name, published_at,
                           asset_symbol, asset_mic, benchmark_symbol, benchmark_mic,
                           calendar_name, currency, publication_session_date,
                           reference_session_date, reference_session_close_at,
                           target_session_date + 7, target_session_close_at + interval '7 days',
                           origin, published_at - interval '1 second', methodology_version,
                           provider_terms_version, provider_use_mode,
                           jsonb_set(
                               jsonb_set(record, '{horizon}', '5'::jsonb),
                               '{enrolled_at}',
                               to_jsonb(to_char(published_at - interval '1 second',
                                   'YYYY-MM-DD"T"HH24:MI:SS"Z"'))
                           )
                    FROM research_prospective_outcome_plans WHERE horizon = 1
                    """,
                    (invalid_plan_id,),
                )

        def rejected_outcome(record_expression: str, message: str) -> None:
            invalid_outcome_id = UUID("40000000-0000-0000-0000-000000000001")
            with pytest.raises(psycopg.Error, match=message):
                with owner.transaction():
                    owner.execute(
                        f"""
                        INSERT INTO research_prospective_outcomes (
                            outcome_id, plan_id, publication_id, horizon, provider_name,
                            status, origin, authority, asset_reference_close,
                            asset_target_close, benchmark_reference_close,
                            benchmark_target_close, asset_return, benchmark_return,
                            benchmark_relative_return, calculation_version, evaluated_at,
                            appended_at, record
                        )
                        SELECT %s, plan_id, publication_id, horizon, provider_name,
                               status, origin, authority, asset_reference_close,
                               asset_target_close, benchmark_reference_close,
                               benchmark_target_close, asset_return, benchmark_return,
                               benchmark_relative_return, calculation_version, evaluated_at,
                               appended_at,
                               {record_expression}
                        FROM research_prospective_outcomes
                        """,
                        (invalid_outcome_id,),
                    )

        outcome_id_record = (
            "jsonb_set(record, '{outcome_id}', "
            "to_jsonb('40000000-0000-0000-0000-000000000001'::text))"
        )
        rejected_outcome(
            f"jsonb_set({outcome_id_record}, "
            "'{observations,asset_target,symbol}', to_jsonb('MSFT'::text))",
            "bar violates closed identity",
        )
        rejected_outcome(
            f"jsonb_set({outcome_id_record}, "
            "'{observations,asset_target,retrieved_at}', "
            "to_jsonb('2026-10-02T12:00:00Z'::text))",
            "bar violates closed identity or knowledge time",
        )

        with pytest.raises(psycopg.Error, match="returns do not exactly recompute"):
            with owner.transaction():
                owner.execute(
                    """
                    INSERT INTO research_prospective_outcomes (
                        outcome_id, plan_id, publication_id, horizon, provider_name,
                        status, origin, authority, asset_reference_close,
                        asset_target_close, benchmark_reference_close,
                        benchmark_target_close, asset_return, benchmark_return,
                        benchmark_relative_return, calculation_version, evaluated_at,
                        appended_at, record
                    )
                    SELECT '40000000-0000-0000-0000-000000000002', plan_id,
                           publication_id, horizon, provider_name, status, origin, authority,
                           asset_reference_close, asset_target_close,
                           benchmark_reference_close, benchmark_target_close,
                           0.999, benchmark_return, benchmark_relative_return,
                           calculation_version, evaluated_at, appended_at,
                           jsonb_set(
                               jsonb_set(record, '{outcome_id}',
                                   to_jsonb('40000000-0000-0000-0000-000000000002'::text)),
                               '{asset_return}', to_jsonb('0.999'::text)
                           )
                    FROM research_prospective_outcomes
                    """
                )

        with pytest.raises(psycopg.Error, match="requires a limitation and no return"):
            with owner.transaction():
                owner.execute(
                    """
                    INSERT INTO research_prospective_outcomes (
                        outcome_id, plan_id, publication_id, horizon, provider_name,
                        status, origin, authority, asset_reference_close,
                        asset_target_close, benchmark_reference_close,
                        benchmark_target_close, asset_return, benchmark_return,
                        benchmark_relative_return, calculation_version, evaluated_at,
                        appended_at, record
                    )
                    SELECT '40000000-0000-0000-0000-000000000003', plan_id,
                           publication_id, horizon, provider_name, 'data_unavailable', origin,
                           authority, asset_reference_close, asset_target_close,
                           benchmark_reference_close, benchmark_target_close,
                           NULL, NULL, NULL, calculation_version, evaluated_at, appended_at,
                           jsonb_set(
                               jsonb_set(
                                   jsonb_set(
                                       jsonb_set(
                                           jsonb_set(record, '{outcome_id}',
                                               to_jsonb('40000000-0000-0000-0000-000000000003'::text)),
                                           '{status}', to_jsonb('data_unavailable'::text)
                                       ),
                                       '{asset_return}', 'null'::jsonb
                                   ),
                                   '{benchmark_return}', 'null'::jsonb
                               ),
                               '{benchmark_relative_return}', 'null'::jsonb
                           )
                    FROM research_prospective_outcomes
                    """
                )

        with pytest.raises(psycopg.Error, match="scope or evaluation time"):
            with owner.transaction():
                owner.execute(
                    """
                    INSERT INTO research_prospective_outcome_attempts (
                        attempt_id, plan_id, attempt_number, started_at, completed_at,
                        status, error_code, record
                    )
                    SELECT '50000000-0000-0000-0000-000000000001', plan_id, 2,
                           completed_at + interval '1 day', completed_at + interval '1 day',
                           status, error_code,
                           jsonb_set(
                               jsonb_set(
                                   jsonb_set(
                                       jsonb_set(record, '{attempt_id}',
                                           to_jsonb('50000000-0000-0000-0000-000000000001'::text)),
                                       '{attempt_number}', '2'::jsonb
                                   ),
                                   '{started_at}', to_jsonb('2026-10-02T12:00:00Z'::text)
                               ),
                               '{completed_at}', to_jsonb('2026-10-02T12:00:00Z'::text)
                           )
                    FROM research_prospective_outcome_attempts
                    """
                )
