"""Closed contracts for honest point-in-time historical evaluation."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from kalki_market_intelligence.contracts.common import (
    ContractModel,
    NonEmptyText,
    Sha256Hex,
    ShortText,
    UtcDatetime,
)
from kalki_market_intelligence.predictions.contracts import SecurityOutcomeStatus
from kalki_market_intelligence.signals.contracts import SignalLabel


class DatasetSplit(StrEnum):
    TUNING = "tuning"
    VALIDATION = "validation"
    HELD_OUT = "held_out"


class ErrorCategory(StrEnum):
    FAVORABLE = "favorable"
    ADVERSE_OUTCOME = "adverse_outcome"
    DELISTED_OR_BANKRUPT_ADVERSE = "delisted_or_bankrupt_adverse"
    OUTCOME_DATA_UNAVAILABLE = "outcome_data_unavailable"


class UniverseMembership(ContractModel):
    case_id: UUID
    instrument_id: UUID
    effective_from: date
    effective_to: date | None = None
    available_at: UtcDatetime
    retrieved_at: UtcDatetime

    @model_validator(mode="after")
    def valid_membership(self) -> Self:
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("universe membership end precedes its start")
        if self.retrieved_at < self.available_at:
            raise ValueError("universe membership retrieval precedes availability")
        return self


class HistoricalPrediction(ContractModel):
    case_id: UUID
    prediction_id: UUID
    instrument_id: UUID
    benchmark_instrument_id: UUID
    split: DatasetSplit
    as_of_date: date
    knowledge_cutoff_at: UtcDatetime
    published_at: UtcDatetime
    horizon_days: int = Field(ge=30, le=180)
    evaluation_due_on: date
    label: SignalLabel
    opportunity_points: int = Field(ge=0, le=100)
    risk_points: int = Field(ge=0, le=100)
    research_confidence_points: int = Field(ge=0, le=100)
    source_fingerprint: Sha256Hex

    @model_validator(mode="after")
    def valid_prediction_time(self) -> Self:
        if self.as_of_date > self.knowledge_cutoff_at.date():
            raise ValueError("historical prediction as-of date follows its cutoff")
        if self.published_at < self.knowledge_cutoff_at:
            raise ValueError("historical prediction publication precedes its cutoff")
        if self.evaluation_due_on != self.as_of_date.fromordinal(
            self.as_of_date.toordinal() + self.horizon_days
        ):
            raise ValueError("historical evaluation due date does not match the horizon")
        if self.instrument_id == self.benchmark_instrument_id:
            raise ValueError("historical asset and benchmark must differ")
        return self


class HistoricalOutcome(ContractModel):
    case_id: UUID
    prediction_id: UUID
    security_status: SecurityOutcomeStatus
    evaluated_at: UtcDatetime
    available_at: UtcDatetime
    retrieved_at: UtcDatetime
    asset_return: Decimal | None
    benchmark_return: Decimal | None
    limitations: tuple[ShortText, ...] = ()

    @model_validator(mode="after")
    def valid_outcome_availability(self) -> Self:
        if self.available_at > self.retrieved_at or self.retrieved_at > self.evaluated_at:
            raise ValueError("outcome was not available and retrieved by evaluation")
        if (self.asset_return is None) != (self.benchmark_return is None):
            raise ValueError("asset and benchmark returns must both be present or absent")
        if self.security_status is SecurityOutcomeStatus.DATA_UNAVAILABLE:
            if self.asset_return is not None:
                raise ValueError("unavailable security outcome cannot contain returns")
        elif self.asset_return is None:
            raise ValueError("available security outcome requires both returns")
        return self


class HistoricalDataset(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    dataset_name: ShortText
    snapshot_at: UtcDatetime
    policy_locked_at: UtcDatetime
    round_trip_cost_bps: Decimal = Field(ge=0, le=1000)
    expected_universe_count: int = Field(gt=0)
    universe: tuple[UniverseMembership, ...] = Field(min_length=1)
    predictions: tuple[HistoricalPrediction, ...] = Field(min_length=1)
    outcomes: tuple[HistoricalOutcome, ...] = Field(min_length=1)
    disclosure: NonEmptyText

    @model_validator(mode="after")
    def point_in_time_integrity(self) -> Self:
        if len(self.universe) != self.expected_universe_count:
            raise ValueError("historical universe count changed; possible survivorship bias")
        memberships = {item.case_id: item for item in self.universe}
        predictions = {item.case_id: item for item in self.predictions}
        outcomes = {item.case_id: item for item in self.outcomes}
        if any(
            len(items) != len(mapping)
            for items, mapping in (
                (self.universe, memberships),
                (self.predictions, predictions),
                (self.outcomes, outcomes),
            )
        ):
            raise ValueError("historical case IDs must be unique within each dataset section")
        if memberships.keys() != predictions.keys() or predictions.keys() != outcomes.keys():
            raise ValueError(
                "every historical universe member must retain prediction and outcome rows"
            )
        for case_id, prediction in predictions.items():
            membership = memberships[case_id]
            outcome = outcomes[case_id]
            if membership.instrument_id != prediction.instrument_id:
                raise ValueError("historical membership and prediction instruments differ")
            if outcome.prediction_id != prediction.prediction_id:
                raise ValueError("historical outcome belongs to another prediction")
            if not (
                membership.effective_from <= prediction.as_of_date
                and (
                    membership.effective_to is None
                    or prediction.as_of_date <= membership.effective_to
                )
            ):
                raise ValueError("prediction was outside point-in-time universe membership")
            if (
                membership.available_at > prediction.knowledge_cutoff_at
                or membership.retrieved_at > prediction.knowledge_cutoff_at
            ):
                raise ValueError("universe membership leaks knowledge after prediction cutoff")
            if outcome.evaluated_at.date() < prediction.evaluation_due_on:
                raise ValueError("historical outcome was evaluated before its declared horizon")
            if outcome.available_at.date() < prediction.evaluation_due_on:
                raise ValueError("historical endpoint predates its declared horizon")
            if outcome.evaluated_at > self.snapshot_at:
                raise ValueError("historical outcome is later than the dataset snapshot")
        ordered: dict[DatasetSplit, list[HistoricalPrediction]] = {
            split: [] for split in DatasetSplit
        }
        for prediction in self.predictions:
            ordered[prediction.split].append(prediction)
        if any(not values for values in ordered.values()):
            raise ValueError("walk-forward dataset requires tuning, validation, and held-out cases")
        tuning_end = max(item.published_at for item in ordered[DatasetSplit.TUNING])
        validation_start = min(item.published_at for item in ordered[DatasetSplit.VALIDATION])
        validation_end = max(item.published_at for item in ordered[DatasetSplit.VALIDATION])
        held_out_start = min(item.published_at for item in ordered[DatasetSplit.HELD_OUT])
        if not tuning_end < validation_start or not validation_end < held_out_start:
            raise ValueError("walk-forward splits overlap or are not chronological")
        if self.policy_locked_at > held_out_start:
            raise ValueError("evaluation policy was not locked before held-out evaluation")
        return self


class CalibrationRow(ContractModel):
    label: SignalLabel
    sample_count: int = Field(ge=0)
    available_count: int = Field(ge=0)
    favorable_count: int = Field(ge=0)
    observed_favorable_rate: Decimal | None
    wilson_low: Decimal | None
    wilson_high: Decimal | None

    @model_validator(mode="after")
    def counts_and_interval_are_consistent(self) -> Self:
        if self.favorable_count > self.available_count or self.available_count > self.sample_count:
            raise ValueError("calibration counts are inconsistent")
        values = (self.observed_favorable_rate, self.wilson_low, self.wilson_high)
        if self.available_count == 0:
            if any(value is not None for value in values):
                raise ValueError("empty calibration row cannot contain rate or interval")
        elif any(value is None for value in values):
            raise ValueError("non-empty calibration row requires rate and interval")
        elif not all(Decimal(0) <= value <= Decimal(1) for value in values if value is not None):
            raise ValueError("calibration rate and interval must be within zero and one")
        return self


class CaseEvaluation(ContractModel):
    case_id: UUID
    split: DatasetSplit
    label: SignalLabel
    security_status: SecurityOutcomeStatus
    category: ErrorCategory
    asset_return: Decimal | None
    benchmark_return: Decimal | None
    net_benchmark_relative_return: Decimal | None


class BacktestReport(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    dataset_name: ShortText
    dataset_fingerprint: Sha256Hex
    generated_at: UtcDatetime
    policy_locked_at: UtcDatetime
    round_trip_cost_bps: Decimal
    universe_count: int = Field(ge=0)
    retained_delisted_or_bankrupt_count: int = Field(ge=0)
    split_counts: dict[DatasetSplit, int]
    available_count: int = Field(ge=0)
    unavailable_count: int = Field(ge=0)
    coverage_rate: Decimal
    cases: tuple[CaseEvaluation, ...]
    calibration: tuple[CalibrationRow, ...]
    error_counts: dict[ErrorCategory, int]
    limitations: tuple[NonEmptyText, ...]

    @model_validator(mode="after")
    def report_counts_are_consistent(self) -> Self:
        if len(self.cases) != self.universe_count:
            raise ValueError("report cases do not equal historical universe count")
        if self.available_count + self.unavailable_count != self.universe_count:
            raise ValueError("report coverage counts do not equal universe count")
        if sum(self.split_counts.values()) != self.universe_count:
            raise ValueError("report split counts do not equal universe count")
        if sum(self.error_counts.values()) != self.universe_count:
            raise ValueError("report error counts do not equal universe count")
        expected = (
            Decimal(self.available_count) / Decimal(self.universe_count)
            if self.universe_count
            else Decimal(0)
        )
        if self.coverage_rate != expected:
            raise ValueError("report coverage rate is inconsistent")
        return self
