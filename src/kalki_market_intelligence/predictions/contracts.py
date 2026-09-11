"""Closed contracts for immutable predictions and appended outcomes."""

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
from kalki_market_intelligence.contracts.domain import CurrencyCode
from kalki_market_intelligence.predictions.calibration import CalibrationReport
from kalki_market_intelligence.signals.contracts import RiskProfile, SignalLabel, SignalResult

PREDICTION_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
OUTCOME_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
OUTCOME_METHODOLOGY_VERSION: Literal["outcome-method-v1"] = "outcome-method-v1"


class EvaluationRule(StrEnum):
    PRICE_RETURN_AND_BENCHMARK = "price_return_and_benchmark"
    TOTAL_RETURN_AND_BENCHMARK = "total_return_and_benchmark"


class ObservationOrigin(StrEnum):
    FORWARD = "forward"
    RECONSTRUCTED = "reconstructed"


class OutcomeMethodologyManifest(ContractModel):
    """Pre-registered evaluation policy carried with future reports."""

    methodology_version: Literal["outcome-method-v1"] = OUTCOME_METHODOLOGY_VERSION
    horizon_days: int = Field(ge=30, le=180)
    evaluation_rule: EvaluationRule
    benchmark_required: bool = True
    observation_origins: tuple[ObservationOrigin, ...] = (
        ObservationOrigin.FORWARD,
        ObservationOrigin.RECONSTRUCTED,
    )


class SecurityOutcomeStatus(StrEnum):
    ACTIVE = "active"
    DELISTED = "delisted"
    ACQUIRED = "acquired"
    BANKRUPT = "bankrupt"
    RENAMED = "renamed"
    DATA_UNAVAILABLE = "data_unavailable"


class OutcomeAssessment(StrEnum):
    POSITIVE_ABSOLUTE_AND_RELATIVE = "positive_absolute_and_relative"
    POSITIVE_ABSOLUTE_ONLY = "positive_absolute_only"
    NON_POSITIVE = "non_positive"
    UNAVAILABLE = "unavailable"


class JobStatus(StrEnum):
    NOT_DUE = "not_due"
    READY = "ready"
    COMPLETED = "completed"
    MISSING_DATA = "missing_data"


class PredictionEvidence(ContractModel):
    evidence_id: UUID
    content_sha256: Sha256Hex
    available_at: UtcDatetime
    retrieved_at: UtcDatetime

    @model_validator(mode="after")
    def retrieval_follows_availability(self) -> Self:
        if self.retrieved_at < self.available_at:
            raise ValueError("prediction evidence retrieval must follow availability")
        return self


class VersionManifest(ContractModel):
    signal_ruleset_version: ShortText
    signal_fingerprint: Sha256Hex
    calculation_versions: tuple[ShortText, ...] = Field(min_length=1)
    analysis_prompt_versions: tuple[ShortText, ...] = Field(min_length=1)
    analysis_model_versions: tuple[ShortText, ...] = Field(min_length=1)


class PredictionScores(ContractModel):
    opportunity_points: int = Field(ge=0, le=100)
    risk_points: int = Field(ge=0, le=100)
    research_confidence_points: int = Field(ge=0, le=100)
    interpretation: Literal["heuristic_points_not_probability"] = "heuristic_points_not_probability"


class PredictionRecord(ContractModel):
    prediction_id: UUID
    schema_version: Literal["1.0.0"] = PREDICTION_SCHEMA_VERSION
    research_subject_id: UUID
    instrument_id: UUID
    benchmark_instrument_id: UUID
    currency: CurrencyCode
    as_of_date: date
    knowledge_cutoff_at: UtcDatetime
    published_at: UtcDatetime
    horizon_days: int = Field(ge=30, le=180)
    evaluation_due_on: date
    evaluation_rule: EvaluationRule
    thesis: NonEmptyText
    label: SignalLabel
    risk_profile: RiskProfile
    scores: PredictionScores
    signal: SignalResult
    evidence: tuple[PredictionEvidence, ...] = Field(min_length=1)
    metric_input_hashes: tuple[Sha256Hex, ...] = Field(min_length=1)
    analysis_input_hashes: tuple[Sha256Hex, ...] = Field(min_length=1)
    versions: VersionManifest
    published_by: ShortText

    @model_validator(mode="after")
    def publication_is_point_in_time_and_complete(self) -> Self:
        if self.as_of_date > self.knowledge_cutoff_at.date():
            raise ValueError("prediction as_of_date must not follow its cutoff")
        if self.published_at < self.knowledge_cutoff_at:
            raise ValueError("prediction publication must not precede its cutoff")
        if self.evaluation_due_on != self.as_of_date.fromordinal(
            self.as_of_date.toordinal() + self.horizon_days
        ):
            raise ValueError("prediction evaluation_due_on must equal as_of_date plus horizon")
        if self.instrument_id == self.benchmark_instrument_id:
            raise ValueError("prediction instrument and benchmark must differ")
        if (
            self.signal.research_subject_id != self.research_subject_id
            or self.signal.as_of_date != self.as_of_date
            or self.signal.knowledge_cutoff_at != self.knowledge_cutoff_at
            or self.signal.horizon_days != self.horizon_days
        ):
            raise ValueError("prediction signal scope does not match the publication")
        if (
            self.signal.label is not self.label
            or self.signal.risk_profile is not self.risk_profile
            or self.signal.opportunity.points != self.scores.opportunity_points
            or self.signal.risk.points != self.scores.risk_points
            or self.signal.research_confidence.points != self.scores.research_confidence_points
        ):
            raise ValueError("prediction scores or labels do not match the immutable signal")
        if (
            self.signal.signal_fingerprint != self.versions.signal_fingerprint
            or self.signal.ruleset_version != self.versions.signal_ruleset_version
        ):
            raise ValueError("prediction signal version manifest does not match")
        ids = tuple(item.evidence_id for item in self.evidence)
        if len(set(ids)) != len(ids):
            raise ValueError("prediction evidence IDs must be unique")
        if any(
            item.available_at > self.knowledge_cutoff_at
            or item.retrieved_at > self.knowledge_cutoff_at
            for item in self.evidence
        ):
            raise ValueError("prediction evidence was not known by its cutoff")
        traced_evidence = {
            evidence_id for trace in self.signal.traces for evidence_id in trace.evidence_ids
        }
        if traced_evidence != set(ids):
            raise ValueError("prediction evidence must exactly match signal trace evidence")
        if len(set(self.metric_input_hashes)) != len(self.metric_input_hashes):
            raise ValueError("prediction metric hashes must be unique")
        if len(set(self.analysis_input_hashes)) != len(self.analysis_input_hashes):
            raise ValueError("prediction analysis hashes must be unique")
        traced_hashes = {item for trace in self.signal.traces for item in trace.input_hashes}
        if traced_hashes != set(self.metric_input_hashes) | set(self.analysis_input_hashes):
            raise ValueError("prediction input hashes must exactly match signal trace hashes")
        return self


class PredictionCorrection(ContractModel):
    correction_id: UUID
    prediction_id: UUID
    appended_at: UtcDatetime
    reason: NonEmptyText
    replacement_text: NonEmptyText | None = None
    appended_by: ShortText


class ReturnObservation(ContractModel):
    instrument_id: UUID
    effective_date: date
    price: Decimal = Field(gt=0)
    cash_distributions_per_share: Decimal = Field(default=Decimal(0), ge=0)
    currency: CurrencyCode
    available_at: UtcDatetime
    retrieved_at: UtcDatetime
    source_record_id: NonEmptyText
    source_content_sha256: Sha256Hex

    @model_validator(mode="after")
    def observation_time_is_consistent(self) -> Self:
        if self.retrieved_at < self.available_at:
            raise ValueError("return observation retrieval must follow availability")
        return self


class CorporateActionRecord(ContractModel):
    action_id: UUID
    instrument_id: UUID
    action_type: ShortText
    effective_date: date
    description: NonEmptyText
    available_at: UtcDatetime
    retrieved_at: UtcDatetime
    source_content_sha256: Sha256Hex

    @model_validator(mode="after")
    def action_time_is_consistent(self) -> Self:
        if self.retrieved_at < self.available_at:
            raise ValueError("corporate action retrieval must follow availability")
        return self


class OutcomeEvaluationInput(ContractModel):
    prediction: PredictionRecord
    evaluated_at: UtcDatetime
    knowledge_cutoff_at: UtcDatetime
    security_status: SecurityOutcomeStatus
    asset_start: ReturnObservation | None
    asset_end: ReturnObservation | None
    benchmark_start: ReturnObservation | None
    benchmark_end: ReturnObservation | None
    corporate_actions: tuple[CorporateActionRecord, ...] = ()
    limitations: tuple[ShortText, ...] = ()
    observation_origin: ObservationOrigin = ObservationOrigin.FORWARD

    @model_validator(mode="after")
    def evaluation_is_temporally_consistent(self) -> Self:
        prediction = self.prediction
        if self.evaluated_at.date() < prediction.evaluation_due_on:
            raise ValueError("outcome evaluation cannot run before its declared horizon")
        if self.knowledge_cutoff_at < self.evaluated_at:
            raise ValueError("outcome knowledge cutoff must include evaluation time")
        observations = tuple(
            item
            for item in (
                self.asset_start,
                self.asset_end,
                self.benchmark_start,
                self.benchmark_end,
            )
            if item is not None
        )
        if any(
            item.available_at > self.knowledge_cutoff_at
            or item.retrieved_at > self.knowledge_cutoff_at
            for item in observations
        ):
            raise ValueError("outcome observation was not known by the evaluation cutoff")
        starts = tuple(
            item for item in (self.asset_start, self.benchmark_start) if item is not None
        )
        if any(
            item.effective_date > prediction.as_of_date
            or item.available_at > prediction.knowledge_cutoff_at
            or item.retrieved_at > prediction.knowledge_cutoff_at
            for item in starts
        ):
            raise ValueError("outcome start observation leaks post-prediction knowledge")
        ends = tuple(item for item in (self.asset_end, self.benchmark_end) if item is not None)
        if any(item.effective_date < prediction.evaluation_due_on for item in ends):
            raise ValueError("outcome end observation precedes the declared horizon")
        for item in self.corporate_actions:
            if item.instrument_id != prediction.instrument_id:
                raise ValueError("corporate action belongs to another instrument")
            if item.effective_date < prediction.as_of_date:
                raise ValueError("corporate action predates the evaluation period")
            if (
                item.available_at > self.knowledge_cutoff_at
                or item.retrieved_at > self.knowledge_cutoff_at
            ):
                raise ValueError("corporate action was not known by the evaluation cutoff")
        expected_ids = {
            prediction.instrument_id,
            prediction.benchmark_instrument_id,
        }
        actual_ids = {item.instrument_id for item in observations}
        if not actual_ids.issubset(expected_ids):
            raise ValueError("outcome observation belongs to an unrelated instrument")
        if any(item.currency is not prediction.currency for item in observations):
            raise ValueError("outcome observation currency does not match the prediction")
        if (
            self.asset_start is not None
            and self.asset_start.instrument_id != prediction.instrument_id
        ):
            raise ValueError("asset start observation belongs to another instrument")
        if self.asset_end is not None and self.asset_end.instrument_id != prediction.instrument_id:
            raise ValueError("asset end observation belongs to another instrument")
        if (
            self.benchmark_start is not None
            and self.benchmark_start.instrument_id != prediction.benchmark_instrument_id
        ):
            raise ValueError("benchmark start observation belongs to another instrument")
        if (
            self.benchmark_end is not None
            and self.benchmark_end.instrument_id != prediction.benchmark_instrument_id
        ):
            raise ValueError("benchmark end observation belongs to another instrument")
        return self


class OutcomeRecord(ContractModel):
    outcome_id: UUID
    schema_version: Literal["1.0.0"] = OUTCOME_SCHEMA_VERSION
    prediction_id: UUID
    appended_at: UtcDatetime
    evaluated_at: UtcDatetime
    knowledge_cutoff_at: UtcDatetime
    security_status: SecurityOutcomeStatus
    asset_return: Decimal | None
    benchmark_return: Decimal | None
    benchmark_relative_return: Decimal | None
    assessment: OutcomeAssessment
    evaluation_rule: EvaluationRule
    observation_hashes: tuple[Sha256Hex, ...]
    corporate_action_ids: tuple[UUID, ...]
    corporate_action_hashes: tuple[Sha256Hex, ...]
    limitations: tuple[ShortText, ...]
    observation_origin: ObservationOrigin = ObservationOrigin.FORWARD

    @model_validator(mode="after")
    def values_are_all_present_or_all_absent(self) -> Self:
        if self.appended_at < self.evaluated_at:
            raise ValueError("outcome append time must not precede evaluation")
        if self.knowledge_cutoff_at < self.evaluated_at:
            raise ValueError("outcome cutoff must include evaluation time")
        values = (self.asset_return, self.benchmark_return, self.benchmark_relative_return)
        if self.assessment is OutcomeAssessment.UNAVAILABLE:
            if any(value is not None for value in values):
                raise ValueError("unavailable outcome must not contain returns")
        elif any(value is None for value in values):
            raise ValueError("evaluated outcome requires all return values")
        return self


class OutcomeJob(ContractModel):
    prediction_id: UUID
    evaluation_due_on: date
    observed_at: UtcDatetime
    status: JobStatus
    outcome_id: UUID | None = None
    explanation: ShortText


class EvaluationReport(ContractModel):
    generated_at: UtcDatetime
    knowledge_cutoff_at: UtcDatetime
    prediction_count: int = Field(ge=0)
    evaluated_count: int = Field(ge=0)
    unavailable_count: int = Field(ge=0)
    status_counts: dict[SecurityOutcomeStatus, int]
    assessment_counts: dict[OutcomeAssessment, int]
    mean_asset_return: Decimal | None
    mean_benchmark_relative_return: Decimal | None
    limitations: tuple[ShortText, ...]
    inference_status: Literal["descriptive_only", "inconclusive"] = "inconclusive"
    forward_observation_count: int = Field(default=0, ge=0)
    reconstructed_observation_count: int = Field(default=0, ge=0)
    calibration: CalibrationReport | None = None

    @model_validator(mode="after")
    def report_counts_are_consistent(self) -> Self:
        if sum(self.status_counts.values()) != self.evaluated_count:
            raise ValueError("report status counts do not equal evaluated count")
        if sum(self.assessment_counts.values()) != self.evaluated_count:
            raise ValueError("report assessment counts do not equal evaluated count")
        if self.unavailable_count != self.assessment_counts.get(OutcomeAssessment.UNAVAILABLE, 0):
            raise ValueError("report unavailable count is inconsistent")
        if self.evaluated_count > self.prediction_count:
            raise ValueError("report cannot evaluate more predictions than supplied")
        if (
            self.forward_observation_count + self.reconstructed_observation_count
            > self.evaluated_count
        ):
            raise ValueError("observation-origin counts cannot exceed evaluated count")
        return self
