"""Closed inputs and outputs for the versioned signal ruleset."""

from __future__ import annotations

import re
from datetime import date
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from kalki_market_intelligence.analysis.contracts import (
    AnalystEvidence,
    AnalystRole,
    ValidatedAnalysis,
)
from kalki_market_intelligence.contracts.common import (
    ContractModel,
    Sha256Hex,
    ShortText,
    UtcDatetime,
)
from kalki_market_intelligence.quantitative.contracts import MetricResult

RULESET_VERSION: Literal["1.0.0"] = "1.0.0"
SCORE_INTERPRETATION: Literal["heuristic_points_not_probability"] = (
    "heuristic_points_not_probability"
)
RESEARCH_DISCLAIMER: Literal[
    "Research-only ordinal signal; not a probability, return promise, or trade instruction."
] = "Research-only ordinal signal; not a probability, return promise, or trade instruction."


class ScoreDimension(StrEnum):
    OPPORTUNITY = "opportunity"
    RISK = "risk"
    RESEARCH_CONFIDENCE = "research_confidence"


class SignalLabel(StrEnum):
    STRONG_OPPORTUNITY = "Strong opportunity"
    MODERATE_OPPORTUNITY = "Moderate opportunity"
    SPECULATIVE_OPPORTUNITY = "Speculative opportunity"
    WEAK_OPPORTUNITY = "Weak opportunity"
    INSUFFICIENT_EVIDENCE = "Insufficient evidence"


class RiskProfile(StrEnum):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    ELEVATED_RISK = "elevated_risk"
    AGGRESSIVE_SPECULATIVE = "aggressive_speculative"
    UNCLASSIFIED = "unclassified"


class MissingSeverity(StrEnum):
    CRITICAL = "critical"
    REDUCES_CONFIDENCE = "reduces_confidence"


class HeuristicScore(ContractModel):
    points: int = Field(ge=0, le=100)
    interpretation: Literal["heuristic_points_not_probability"] = SCORE_INTERPRETATION


class MissingInput(ContractModel):
    slot: ShortText
    severity: MissingSeverity
    explanation: ShortText


class RuleTrace(ContractModel):
    rule_id: ShortText
    ruleset_version: Literal["1.0.0"] = RULESET_VERSION
    dimension: ScoreDimension
    points: int = Field(ge=-100, le=100)
    explanation: ShortText
    metric_names: tuple[ShortText, ...] = ()
    analysis_roles: tuple[AnalystRole, ...] = ()
    evidence_ids: tuple[UUID, ...] = ()
    input_hashes: tuple[Sha256Hex, ...] = ()


class SignalRequest(ContractModel):
    research_subject_id: UUID
    allowed_metric_subject_ids: tuple[UUID, ...] = Field(min_length=1)
    as_of_date: date
    knowledge_cutoff_at: UtcDatetime
    horizon_days: int = Field(ge=30, le=180)
    metrics: tuple[MetricResult, ...] = Field(max_length=32)
    analyses: tuple[ValidatedAnalysis, ...] = Field(max_length=8)
    evidence: tuple[AnalystEvidence, ...] = Field(max_length=32)

    @model_validator(mode="after")
    def inputs_are_temporally_and_referentially_consistent(self) -> Self:
        if self.as_of_date > self.knowledge_cutoff_at.date():
            raise ValueError("signal as_of_date must not follow the knowledge cutoff")
        if len(set(self.allowed_metric_subject_ids)) != len(self.allowed_metric_subject_ids):
            raise ValueError("allowed metric subject IDs must be unique")
        metric_names = tuple(metric.metric_name for metric in self.metrics)
        if len(set(metric_names)) != len(metric_names):
            raise ValueError("signal metrics must have unique metric names")
        allowed_subjects = set(self.allowed_metric_subject_ids)
        for metric in self.metrics:
            if metric.as_of_date > self.as_of_date:
                raise ValueError("signal metric is later than the signal as_of_date")
            if metric.knowledge_cutoff_at > self.knowledge_cutoff_at:
                raise ValueError("signal metric uses a later knowledge cutoff")
            if any(item.subject_id not in allowed_subjects for item in metric.inputs):
                raise ValueError("signal metric contains an unapproved subject")
        roles = tuple(analysis.report.role for analysis in self.analyses)
        if len(set(roles)) != len(roles):
            raise ValueError("signal analyses must use unique analyst roles")
        evidence_by_id = {item.evidence_id: item for item in self.evidence}
        if len(evidence_by_id) != len(self.evidence):
            raise ValueError("signal evidence IDs must be unique")
        for item in self.evidence:
            if item.subject_id != self.research_subject_id:
                raise ValueError("signal evidence belongs to a different research subject")
            if (
                item.available_at > self.knowledge_cutoff_at
                or item.retrieved_at > self.knowledge_cutoff_at
            ):
                raise ValueError("signal evidence was unavailable or unretrieved at the cutoff")
        for analysis in self.analyses:
            if analysis.audit.knowledge_cutoff_at > self.knowledge_cutoff_at:
                raise ValueError("signal analysis uses a later knowledge cutoff")
            expected_hashes = tuple(
                evidence_by_id[evidence_id].content_sha256
                for evidence_id in analysis.audit.evidence_ids
                if evidence_id in evidence_by_id
            )
            if len(expected_hashes) != len(analysis.audit.evidence_ids):
                raise ValueError("signal analysis references missing evidence")
            if expected_hashes != analysis.audit.evidence_hashes:
                raise ValueError("signal analysis evidence hashes do not match")
            cited_ids = {
                citation.evidence_id
                for finding in analysis.report.findings
                for citation in finding.citations
            } | {
                citation.evidence_id
                for contradiction in analysis.report.contradictions
                for citation in contradiction.citations
            }
            if not cited_ids.issubset(set(analysis.audit.evidence_ids)):
                raise ValueError("signal analysis cites evidence outside its audit")
        return self


class SignalResult(ContractModel):
    signal_fingerprint: Sha256Hex
    ruleset_version: Literal["1.0.0"] = RULESET_VERSION
    research_subject_id: UUID
    as_of_date: date
    knowledge_cutoff_at: UtcDatetime
    horizon_days: int
    opportunity: HeuristicScore
    risk: HeuristicScore
    research_confidence: HeuristicScore
    label: SignalLabel
    risk_profile: RiskProfile
    traces: tuple[RuleTrace, ...]
    missing_inputs: tuple[MissingInput, ...]
    disclaimer: Literal[
        "Research-only ordinal signal; not a probability, return promise, or trade instruction."
    ] = RESEARCH_DISCLAIMER

    @model_validator(mode="after")
    def result_has_complete_separate_traces(self) -> Self:
        dimensions = {trace.dimension for trace in self.traces}
        if dimensions != set(ScoreDimension):
            raise ValueError("signal traces must cover all three score dimensions")
        if (
            self.label is SignalLabel.INSUFFICIENT_EVIDENCE
            and self.risk_profile is not RiskProfile.UNCLASSIFIED
        ):
            raise ValueError("insufficient evidence signals must have unclassified risk profile")
        if (
            self.label is not SignalLabel.INSUFFICIENT_EVIDENCE
            and self.risk_profile is RiskProfile.UNCLASSIFIED
        ):
            raise ValueError("classified signals require a classified risk profile")
        score_by_dimension = {
            ScoreDimension.OPPORTUNITY: self.opportunity.points,
            ScoreDimension.RISK: self.risk.points,
            ScoreDimension.RESEARCH_CONFIDENCE: self.research_confidence.points,
        }
        for dimension, expected in score_by_dimension.items():
            total = sum(trace.points for trace in self.traces if trace.dimension is dimension)
            if min(100, max(0, total)) != expected:
                raise ValueError(f"{dimension} score does not equal its trace total")
        prohibited = re.compile(
            r"\b(?:buy|sell|guaranteed?|probabilit(?:y|ies)|trade instruction)\b", re.I
        )
        if any(prohibited.search(trace.explanation) for trace in self.traces):
            raise ValueError("signal explanation contains prohibited recommendation language")
        return self
