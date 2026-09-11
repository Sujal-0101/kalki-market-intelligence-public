"""Validated inputs and outputs for deterministic quantitative calculations."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from kalki_market_intelligence.contracts.common import (
    ContractModel,
    NonEmptyText,
    Sha256Hex,
    ShortText,
    UtcDatetime,
)
from kalki_market_intelligence.contracts.domain import CurrencyCode
from kalki_market_intelligence.providers.market_data.contracts import (
    PriceAdjustment,
    VolumeAdjustment,
)

CALCULATION_VERSION = "1.0.0"
type CalculationVersion = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$"),
]


class FinancialUnit(StrEnum):
    CURRENCY = "currency"
    SHARES = "shares"
    PURE = "pure"
    CURRENCY_PER_SHARE = "currency_per_share"


class FinancialPeriodKind(StrEnum):
    INSTANT = "instant"
    DURATION = "duration"


class FinancialFact(ContractModel):
    """One point-in-time financial input with its original source lineage."""

    fact_id: NonEmptyText
    issuer_id: UUID
    concept: ShortText
    value: Decimal
    unit: FinancialUnit
    currency: CurrencyCode | None = None
    period_kind: FinancialPeriodKind
    period_start: date | None = None
    period_end: date
    available_at: UtcDatetime
    retrieved_at: UtcDatetime
    source_record_id: NonEmptyText
    source_content_sha256: Sha256Hex

    @model_validator(mode="after")
    def unit_period_and_times_are_consistent(self) -> Self:
        monetary = self.unit in {FinancialUnit.CURRENCY, FinancialUnit.CURRENCY_PER_SHARE}
        if monetary != (self.currency is not None):
            raise ValueError("currency is required exactly for monetary financial units")
        if self.period_kind is FinancialPeriodKind.INSTANT and self.period_start is not None:
            raise ValueError("instant facts must not have period_start")
        if self.period_kind is FinancialPeriodKind.DURATION and self.period_start is None:
            raise ValueError("duration facts require period_start")
        if self.period_start is not None and self.period_start > self.period_end:
            raise ValueError("financial fact period_start must not follow period_end")
        if self.retrieved_at < self.available_at:
            raise ValueError("financial fact retrieved_at must not precede available_at")
        return self


class InputValue(ContractModel):
    name: ShortText
    value: Decimal
    unit: ShortText


class CalculationInput(ContractModel):
    """The exact source row and values consumed by one calculation."""

    input_id: NonEmptyText
    input_kind: ShortText
    subject_id: UUID
    period_start: date | None = None
    effective_date: date
    values: tuple[InputValue, ...]
    currency: CurrencyCode | None = None
    price_adjustment: PriceAdjustment | None = None
    volume_adjustment: VolumeAdjustment | None = None
    available_at: UtcDatetime
    retrieved_at: UtcDatetime
    source_record_id: NonEmptyText
    source_content_sha256: Sha256Hex

    @model_validator(mode="after")
    def values_and_times_are_valid(self) -> Self:
        if not self.values:
            raise ValueError("calculation input must record at least one value")
        names = tuple(item.name for item in self.values)
        if len(set(names)) != len(names):
            raise ValueError("calculation input value names must be unique")
        if self.retrieved_at < self.available_at:
            raise ValueError("calculation input retrieved_at must not precede available_at")
        if self.period_start is not None and self.period_start > self.effective_date:
            raise ValueError("calculation input period_start must not follow effective_date")
        return self


class MetricParameter(ContractModel):
    name: ShortText
    value: NonEmptyText


class MetricPoint(ContractModel):
    effective_date: date
    component: ShortText
    value: Decimal


class MetricResult(ContractModel):
    """Versioned output with every consumed source row attached."""

    metric_name: ShortText
    implementation_version: CalculationVersion = CALCULATION_VERSION
    as_of_date: date
    knowledge_cutoff_at: UtcDatetime
    unit: ShortText
    currency: CurrencyCode | None = None
    parameters: tuple[MetricParameter, ...] = ()
    points: tuple[MetricPoint, ...] = Field(min_length=1)
    inputs: tuple[CalculationInput, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def temporal_integrity_and_keys_are_valid(self) -> Self:
        if self.as_of_date > self.knowledge_cutoff_at.date():
            raise ValueError("as_of_date must not follow the UTC knowledge cutoff date")
        parameter_names = tuple(item.name for item in self.parameters)
        if len(set(parameter_names)) != len(parameter_names):
            raise ValueError("metric parameter names must be unique")
        point_keys = tuple((item.effective_date, item.component) for item in self.points)
        if len(set(point_keys)) != len(point_keys):
            raise ValueError("metric points must have unique date/component keys")
        input_ids = tuple(item.input_id for item in self.inputs)
        if len(set(input_ids)) != len(input_ids):
            raise ValueError("metric input IDs must be unique")
        for item in self.inputs:
            if item.available_at > self.knowledge_cutoff_at:
                raise ValueError("calculation input was unavailable at the knowledge cutoff")
            if item.retrieved_at > self.knowledge_cutoff_at:
                raise ValueError("calculation input was not retrieved by the knowledge cutoff")
            if item.effective_date > self.as_of_date:
                raise ValueError("calculation input is later than the result as_of_date")
        if any(point.effective_date > self.as_of_date for point in self.points):
            raise ValueError("metric point is later than the result as_of_date")
        point_dates = tuple(point.effective_date for point in self.points)
        if tuple(sorted(point_dates)) != point_dates:
            raise ValueError("metric points must be sorted by date")
        return self
