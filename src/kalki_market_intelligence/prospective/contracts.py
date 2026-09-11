"""Closed contracts for supporting T+1/T+5/T+20 publication outcomes."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, localcontext
from enum import IntEnum, StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from kalki_market_intelligence.contracts.common import (
    ContractModel,
    Sha256Hex,
    ShortText,
    UtcDatetime,
)
from kalki_market_intelligence.contracts.domain import CurrencyCode, TickerSymbol
from kalki_market_intelligence.quantitative.algorithms import CALCULATION_CONTEXT

type MarketIdentifierCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Z0-9]{4}$"),
]


class OutcomeHorizon(IntEnum):
    T1 = 1
    T5 = 5
    T20 = 20


class OutcomeOrigin(StrEnum):
    GENUINE_FORWARD = "GENUINE_FORWARD"
    RECONSTRUCTED = "RECONSTRUCTED"


class OutcomeStatus(StrEnum):
    COMPLETED = "completed"
    DATA_UNAVAILABLE = "data_unavailable"


class AttemptStatus(StrEnum):
    SUCCEEDED = "succeeded"
    RETRYABLE_FAILURE = "retryable_failure"
    TERMINAL_FAILURE = "terminal_failure"


class OutcomeJobStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    RETRY_WAIT = "retry_wait"
    COMPLETED = "completed"
    DATA_UNAVAILABLE = "data_unavailable"


class SupportingDataAuthority(StrEnum):
    SUPPORTING = "SUPPORTING"


class ProspectiveOutcomePlan(ContractModel):
    """Immutable event-study dates fixed before an outcome is fetched."""

    publication_id: UUID
    published_at: UtcDatetime
    asset_symbol: TickerSymbol
    asset_mic: MarketIdentifierCode
    benchmark_symbol: TickerSymbol
    benchmark_mic: MarketIdentifierCode
    calendar_name: MarketIdentifierCode
    currency: CurrencyCode
    provider_name: Literal["twelve_data"] = "twelve_data"
    enrolled_at: UtcDatetime
    publication_session_date: date
    reference_session_date: date
    reference_session_close_at: UtcDatetime
    horizon: OutcomeHorizon
    target_session_date: date
    target_session_close_at: UtcDatetime
    origin: OutcomeOrigin
    methodology_version: Literal["prospective-outcome-v1"] = "prospective-outcome-v1"
    provider_terms_version: Literal["2026-01-01"] = "2026-01-01"
    provider_use_mode: Literal["internal_non_display"] = "internal_non_display"

    @model_validator(mode="after")
    def dates_and_origin_are_consistent(self) -> Self:
        if self.asset_symbol == self.benchmark_symbol and self.asset_mic == self.benchmark_mic:
            raise ValueError("asset and benchmark must differ")
        if self.enrolled_at < self.published_at:
            raise ValueError("outcome enrollment cannot precede publication")
        if self.reference_session_close_at < self.published_at:
            raise ValueError("reference session must not close before publication")
        if self.target_session_date <= self.reference_session_date:
            raise ValueError("target session must follow reference session")
        if self.target_session_close_at <= self.reference_session_close_at:
            raise ValueError("target close must follow reference close")
        expected_origin = (
            OutcomeOrigin.GENUINE_FORWARD
            if self.enrolled_at < self.target_session_close_at
            else OutcomeOrigin.RECONSTRUCTED
        )
        if self.origin is not expected_origin:
            raise ValueError("outcome origin does not match enrollment and target close")
        return self


class ProspectivePublication(ContractModel):
    publication_id: UUID
    published_at: UtcDatetime
    ticker: TickerSymbol | None
    exchange: ShortText | None


class SupportingDailyBar(ContractModel):
    """One split-adjusted provider observation; never authoritative evidence."""

    symbol: TickerSymbol
    mic: MarketIdentifierCode
    provider_mic: MarketIdentifierCode
    session_date: date
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    volume: int = Field(ge=0)
    currency: CurrencyCode
    adjustment: Literal["splits"] = "splits"
    provider_name: Literal["twelve_data"] = "twelve_data"
    authority: Literal[SupportingDataAuthority.SUPPORTING] = SupportingDataAuthority.SUPPORTING
    source_record_id: ShortText
    source_content_sha256: Sha256Hex
    available_at: UtcDatetime
    retrieved_at: UtcDatetime

    @model_validator(mode="after")
    def values_and_times_are_consistent(self) -> Self:
        if self.high < max(self.open, self.low, self.close):
            raise ValueError("bar high is below another OHLC value")
        if self.low > min(self.open, self.high, self.close):
            raise ValueError("bar low is above another OHLC value")
        if self.retrieved_at < self.available_at:
            raise ValueError("bar retrieval must not precede availability")
        return self


class SupportingBarRequest(ContractModel):
    symbol: TickerSymbol
    mic: MarketIdentifierCode
    start_date: date
    end_date: date
    currency: CurrencyCode

    @model_validator(mode="after")
    def dates_are_ordered(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("bar request end must not precede start")
        if (self.end_date - self.start_date).days > 90:
            raise ValueError("bar request window cannot exceed 90 days")
        return self


class SupportingBarBatch(ContractModel):
    request: SupportingBarRequest
    bars: tuple[SupportingDailyBar, ...]
    provider_name: Literal["twelve_data"] = "twelve_data"
    response_sha256: Sha256Hex
    retrieved_at: UtcDatetime

    @model_validator(mode="after")
    def bars_match_request(self) -> Self:
        if any(
            bar.symbol != self.request.symbol
            or bar.mic != self.request.mic
            or bar.currency is not self.request.currency
            or not self.request.start_date <= bar.session_date <= self.request.end_date
            or bar.provider_name != self.provider_name
            or bar.retrieved_at != self.retrieved_at
            for bar in self.bars
        ):
            raise ValueError("provider batch contains a bar outside its request")
        sessions = tuple(bar.session_date for bar in self.bars)
        if sessions != tuple(sorted(set(sessions))):
            raise ValueError("provider batch sessions must be sorted and unique")
        return self


class OutcomeObservationSet(ContractModel):
    asset_reference: SupportingDailyBar | None
    asset_target: SupportingDailyBar | None
    benchmark_reference: SupportingDailyBar | None
    benchmark_target: SupportingDailyBar | None


class ProspectiveOutcomeAttempt(ContractModel):
    attempt_id: UUID
    publication_id: UUID
    horizon: OutcomeHorizon
    provider_name: Literal["twelve_data"] = "twelve_data"
    attempt_number: int = Field(ge=1, le=6)
    started_at: UtcDatetime
    completed_at: UtcDatetime
    status: AttemptStatus
    response_sha256: tuple[Sha256Hex, ...] = Field(default=(), max_length=2)
    response_row_count: int = Field(ge=0, le=10_000)
    error_code: ShortText | None = None

    @model_validator(mode="after")
    def completion_and_error_match_status(self) -> Self:
        if self.completed_at < self.started_at:
            raise ValueError("attempt completion must follow its start")
        if (self.status is AttemptStatus.SUCCEEDED) == (self.error_code is not None):
            raise ValueError("only failed attempts require an error code")
        return self


class ClaimedProspectiveOutcome(ContractModel):
    plan_id: UUID
    plan: ProspectiveOutcomePlan
    attempt_number: int = Field(ge=1, le=6)
    claimed_at: UtcDatetime


class ProspectiveOutcome(ContractModel):
    outcome_id: UUID
    plan: ProspectiveOutcomePlan
    status: OutcomeStatus
    evaluated_at: UtcDatetime
    appended_at: UtcDatetime
    observations: OutcomeObservationSet
    asset_return: Decimal | None
    benchmark_return: Decimal | None
    benchmark_relative_return: Decimal | None
    observation_hashes: tuple[Sha256Hex, ...] = Field(max_length=4)
    attempts: tuple[ProspectiveOutcomeAttempt, ...] = Field(min_length=1, max_length=6)
    limitations: tuple[ShortText, ...] = Field(max_length=8)
    authority: Literal[SupportingDataAuthority.SUPPORTING] = SupportingDataAuthority.SUPPORTING
    calculation_version: Literal["price-return-v1"] = "price-return-v1"
    schema_version: Literal["1.0.0"] = "1.0.0"

    @model_validator(mode="after")
    def outcome_is_complete_or_explicitly_unavailable(self) -> Self:
        if self.evaluated_at < self.plan.target_session_close_at:
            raise ValueError("outcome cannot be evaluated before its target session closes")
        if self.appended_at < self.evaluated_at:
            raise ValueError("outcome append must not precede evaluation")
        if any(
            attempt.publication_id != self.plan.publication_id
            or attempt.horizon is not self.plan.horizon
            or attempt.provider_name != self.plan.provider_name
            for attempt in self.attempts
        ):
            raise ValueError("attempt scope does not match outcome plan")
        if any(attempt.completed_at > self.evaluated_at for attempt in self.attempts):
            raise ValueError("outcome cannot precede a retained provider attempt")
        if self.status is OutcomeStatus.COMPLETED and (
            not self.attempts or self.attempts[-1].status is not AttemptStatus.SUCCEEDED
        ):
            raise ValueError("completed outcome requires a successful final attempt")
        if self.status is OutcomeStatus.DATA_UNAVAILABLE and (
            not self.attempts or self.attempts[-1].status is not AttemptStatus.TERMINAL_FAILURE
        ):
            raise ValueError("unavailable outcome requires a terminal failed attempt")
        attempt_ids = tuple(attempt.attempt_id for attempt in self.attempts)
        attempt_numbers = tuple(attempt.attempt_number for attempt in self.attempts)
        if len(set(attempt_ids)) != len(attempt_ids):
            raise ValueError("outcome attempts must be unique")
        if attempt_numbers != tuple(sorted(set(attempt_numbers))):
            raise ValueError("outcome attempts must be ordered and uniquely numbered")
        values = (self.asset_return, self.benchmark_return, self.benchmark_relative_return)
        bars = (
            self.observations.asset_reference,
            self.observations.asset_target,
            self.observations.benchmark_reference,
            self.observations.benchmark_target,
        )
        expected_bars = (
            (
                self.observations.asset_reference,
                self.plan.asset_symbol,
                self.plan.asset_mic,
                self.plan.reference_session_date,
            ),
            (
                self.observations.asset_target,
                self.plan.asset_symbol,
                self.plan.asset_mic,
                self.plan.target_session_date,
            ),
            (
                self.observations.benchmark_reference,
                self.plan.benchmark_symbol,
                self.plan.benchmark_mic,
                self.plan.reference_session_date,
            ),
            (
                self.observations.benchmark_target,
                self.plan.benchmark_symbol,
                self.plan.benchmark_mic,
                self.plan.target_session_date,
            ),
        )
        if any(
            bar is not None
            and (
                bar.symbol != symbol
                or bar.mic != mic
                or bar.session_date != session_date
                or bar.provider_name != self.plan.provider_name
                or bar.currency is not self.plan.currency
                or bar.retrieved_at > self.evaluated_at
            )
            for bar, symbol, mic, session_date in expected_bars
        ):
            raise ValueError("outcome observation identity or time does not match its plan")
        if self.status is OutcomeStatus.COMPLETED:
            if any(value is None for value in values) or any(bar is None for bar in bars):
                raise ValueError("completed outcome requires all bars and returns")
            if self.limitations:
                raise ValueError("completed outcome cannot claim limitations")
            assert self.observations.asset_reference is not None
            assert self.observations.asset_target is not None
            assert self.observations.benchmark_reference is not None
            assert self.observations.benchmark_target is not None
            assert self.asset_return is not None
            assert self.benchmark_return is not None
            assert self.benchmark_relative_return is not None
            with localcontext(CALCULATION_CONTEXT):
                expected_asset_return = (
                    self.observations.asset_target.close - self.observations.asset_reference.close
                ) / self.observations.asset_reference.close
                expected_benchmark_return = (
                    self.observations.benchmark_target.close
                    - self.observations.benchmark_reference.close
                ) / self.observations.benchmark_reference.close
                expected_relative_return = expected_asset_return - expected_benchmark_return
            if (
                self.asset_return != expected_asset_return
                or self.benchmark_return != expected_benchmark_return
                or self.benchmark_relative_return != expected_relative_return
            ):
                raise ValueError("outcome returns do not match retained observations")
        else:
            if any(value is not None for value in values):
                raise ValueError("unavailable outcome cannot claim returns")
            if not self.limitations:
                raise ValueError("unavailable outcome requires an explicit limitation")
        expected_hashes = tuple(
            sorted(bar.source_content_sha256 for bar in bars if bar is not None)
        )
        if self.observation_hashes != expected_hashes:
            raise ValueError("outcome hashes do not exactly match retained observations")
        if len(set(self.observation_hashes)) != len(self.observation_hashes):
            raise ValueError("outcome observation hashes must be unique")
        return self
