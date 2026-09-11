"""Canonical, adjustment-explicit market-data boundary contracts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from kalki_market_intelligence.contracts.common import (
    ContractModel,
    NonEmptyText,
    Sha256Hex,
    ShortText,
    UtcDatetime,
)
from kalki_market_intelligence.contracts.domain import CountryCode, CurrencyCode, TickerSymbol

type TimeZoneName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=3, max_length=64, pattern=r"^[A-Za-z_]+/[A-Za-z_+-]+$"
    ),
]


class InstrumentKind(StrEnum):
    EQUITY = "equity"
    BENCHMARK = "benchmark"


class PriceAdjustment(StrEnum):
    """One basis applies consistently to every OHLC value in a bar series."""

    UNADJUSTED = "unadjusted"
    SPLIT_ADJUSTED = "split_adjusted"
    SPLIT_AND_DIVIDEND_ADJUSTED = "split_and_dividend_adjusted"


class VolumeAdjustment(StrEnum):
    """Volume adjustment is separate because cash dividends do not change volume."""

    UNADJUSTED = "unadjusted"
    SPLIT_ADJUSTED = "split_adjusted"


class FreshnessStatus(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    NO_DATA = "no_data"


class QualityIssueCode(StrEnum):
    STALE = "stale"
    NO_DATA = "no_data"
    PARTIAL_COVERAGE = "partial_coverage"


class ProviderAccessMode(StrEnum):
    OFFLINE_FIXTURE = "offline_fixture"
    LIVE = "live"


class ProviderCapabilities(ContractModel):
    provider_name: ShortText
    access_mode: ProviderAccessMode
    license_reference: NonEmptyText
    supported_adjustments: tuple[PriceAdjustment, ...]
    supported_volume_adjustments: tuple[VolumeAdjustment, ...]
    supports_corporate_actions: bool
    supports_benchmarks: bool
    requests_per_period: int | None = Field(default=None, ge=1)
    request_period_seconds: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def rate_limit_is_complete_or_absent(self) -> Self:
        if (self.requests_per_period is None) != (self.request_period_seconds is None):
            raise ValueError("rate limit count and period must be set together")
        if not self.supported_adjustments or not self.supported_volume_adjustments:
            raise ValueError("provider must declare supported price and volume adjustments")
        if len(set(self.supported_adjustments)) != len(self.supported_adjustments):
            raise ValueError("supported price adjustments must be unique")
        if len(set(self.supported_volume_adjustments)) != len(self.supported_volume_adjustments):
            raise ValueError("supported volume adjustments must be unique")
        return self


class MarketInstrument(ContractModel):
    instrument_id: UUID
    kind: InstrumentKind
    symbol: TickerSymbol
    exchange_name: ShortText
    country: CountryCode
    currency: CurrencyCode
    exchange_timezone: TimeZoneName
    active_from: date
    active_to: date | None = None
    source_record_id: NonEmptyText
    source_content_sha256: Sha256Hex
    available_at: UtcDatetime
    retrieved_at: UtcDatetime

    @model_validator(mode="after")
    def active_dates_are_ordered(self) -> Self:
        if self.active_to is not None and self.active_to < self.active_from:
            raise ValueError("active_to must not precede active_from")
        if self.retrieved_at < self.available_at:
            raise ValueError("retrieved_at must not precede available_at")
        return self


class DailyBar(ContractModel):
    instrument_id: UUID
    session_date: date
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    volume: int = Field(ge=0)
    currency: CurrencyCode
    adjustment: PriceAdjustment
    volume_adjustment: VolumeAdjustment
    available_at: UtcDatetime
    retrieved_at: UtcDatetime
    source_record_id: NonEmptyText
    source_content_sha256: Sha256Hex

    @model_validator(mode="after")
    def values_and_times_are_consistent(self) -> Self:
        if self.high < max(self.open, self.low, self.close):
            raise ValueError("high must be at least open, low, and close")
        if self.low > min(self.open, self.high, self.close):
            raise ValueError("low must be no greater than open, high, and close")
        if self.retrieved_at < self.available_at:
            raise ValueError("retrieved_at must not precede available_at")
        return self


class BarRequest(ContractModel):
    instrument_id: UUID
    start_date: date
    end_date: date
    currency: CurrencyCode
    adjustment: PriceAdjustment
    volume_adjustment: VolumeAdjustment
    knowledge_cutoff_at: UtcDatetime
    freshness_max_age_seconds: int = Field(gt=0)

    @model_validator(mode="after")
    def dates_are_ordered(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")
        return self


class QualityIssue(ContractModel):
    code: QualityIssueCode
    detail: NonEmptyText


class QualityMetadata(ContractModel):
    provider_name: ShortText
    license_reference: NonEmptyText
    evaluated_at: UtcDatetime
    freshness_status: FreshnessStatus
    row_count: int = Field(ge=0)
    coverage_start: date | None
    coverage_end: date | None
    latest_available_at: UtcDatetime | None
    issues: tuple[QualityIssue, ...]


class BarSeries(ContractModel):
    request: BarRequest
    bars: tuple[DailyBar, ...]
    quality: QualityMetadata

    @model_validator(mode="after")
    def bars_match_request_and_do_not_leak_future_data(self) -> Self:
        if self.quality.evaluated_at != self.request.knowledge_cutoff_at:
            raise ValueError("quality evaluation time must equal the knowledge cutoff")
        sessions: set[date] = set()
        for bar in self.bars:
            if bar.instrument_id != self.request.instrument_id:
                raise ValueError("bar instrument does not match request")
            if bar.currency is not self.request.currency:
                raise ValueError("bar currency does not match request")
            if bar.adjustment is not self.request.adjustment:
                raise ValueError("bar adjustment does not match request")
            if bar.volume_adjustment is not self.request.volume_adjustment:
                raise ValueError("bar volume adjustment does not match request")
            if not self.request.start_date <= bar.session_date <= self.request.end_date:
                raise ValueError("bar session is outside requested dates")
            if bar.available_at > self.request.knowledge_cutoff_at:
                raise ValueError("bar was unavailable at the request knowledge cutoff")
            if bar.retrieved_at > self.request.knowledge_cutoff_at:
                raise ValueError("bar was not retrieved by the request knowledge cutoff")
            if bar.session_date in sessions:
                raise ValueError("bar series contains a duplicate session")
            sessions.add(bar.session_date)
        if tuple(sorted(self.bars, key=lambda item: item.session_date)) != self.bars:
            raise ValueError("bar series must be sorted by session date")
        if self.quality.row_count != len(self.bars):
            raise ValueError("quality row_count does not match bars")
        if self.bars and (
            self.quality.coverage_start != self.bars[0].session_date
            or self.quality.coverage_end != self.bars[-1].session_date
        ):
            raise ValueError("quality coverage does not match bar sessions")
        return self


class CorporateActionBase(ContractModel):
    action_id: Sha256Hex
    instrument_id: UUID
    effective_date: date
    announced_at: UtcDatetime | None
    available_at: UtcDatetime
    retrieved_at: UtcDatetime
    source_record_id: NonEmptyText
    source_content_sha256: Sha256Hex

    @model_validator(mode="after")
    def action_times_are_ordered(self) -> Self:
        if self.announced_at is not None and self.available_at < self.announced_at:
            raise ValueError("available_at must not precede announced_at")
        if self.retrieved_at < self.available_at:
            raise ValueError("retrieved_at must not precede available_at")
        return self


class SplitAction(CorporateActionBase):
    action_type: Literal["split"] = "split"
    new_shares_per_old_share: Decimal = Field(gt=0)


class CashDividendAction(CorporateActionBase):
    action_type: Literal["cash_dividend"] = "cash_dividend"
    amount_per_share: Decimal = Field(ge=0)
    currency: CurrencyCode


class SymbolChangeAction(CorporateActionBase):
    action_type: Literal["symbol_change"] = "symbol_change"
    old_symbol: TickerSymbol
    new_symbol: TickerSymbol


type CorporateAction = SplitAction | CashDividendAction | SymbolChangeAction


class CorporateActionRequest(ContractModel):
    instrument_id: UUID
    start_date: date
    end_date: date
    knowledge_cutoff_at: UtcDatetime

    @model_validator(mode="after")
    def dates_are_ordered(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")
        return self


class CorporateActionSeries(ContractModel):
    request: CorporateActionRequest
    actions: tuple[CorporateAction, ...]
    quality: QualityMetadata

    @model_validator(mode="after")
    def actions_match_request(self) -> Self:
        if self.quality.evaluated_at != self.request.knowledge_cutoff_at:
            raise ValueError("quality evaluation time must equal the knowledge cutoff")
        action_ids: set[str] = set()
        for action in self.actions:
            if action.instrument_id != self.request.instrument_id:
                raise ValueError("corporate action instrument does not match request")
            if not self.request.start_date <= action.effective_date <= self.request.end_date:
                raise ValueError("corporate action is outside requested dates")
            if action.available_at > self.request.knowledge_cutoff_at:
                raise ValueError("corporate action was unavailable at the knowledge cutoff")
            if action.retrieved_at > self.request.knowledge_cutoff_at:
                raise ValueError("corporate action was not retrieved by the knowledge cutoff")
            if action.action_id in action_ids:
                raise ValueError("corporate action series contains a duplicate action")
            action_ids.add(action.action_id)
        if tuple(sorted(self.actions, key=lambda item: (item.effective_date, item.action_id))) != (
            self.actions
        ):
            raise ValueError("corporate action series must be sorted")
        if self.quality.row_count != len(self.actions):
            raise ValueError("quality row_count does not match actions")
        if self.actions and (
            self.quality.coverage_start != self.actions[0].effective_date
            or self.quality.coverage_end != self.actions[-1].effective_date
        ):
            raise ValueError("quality coverage does not match corporate actions")
        return self
