"""Explainable multi-channel convergence without opaque predictive scoring."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field

from kalki_market_intelligence.contracts.common import ContractModel, ShortText
from kalki_market_intelligence.contracts.evidence import SourceQuality


class ObservationDirection(StrEnum):
    SUPPORTIVE = "supportive"
    CONTRADICTORY = "contradictory"
    UNKNOWN = "unknown"


class ConvergenceObservation(ContractModel):
    channel: ShortText
    source_quality: SourceQuality
    direction: ObservationDirection
    evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=8)


class ConvergenceResult(ContractModel):
    supportive_channels: tuple[ShortText, ...]
    contradictory_channels: tuple[ShortText, ...]
    unknown_channels: tuple[ShortText, ...]
    conclusion: str
    primary_support_count: int = Field(ge=0)
    supporting_support_count: int = Field(ge=0)
    lower_confidence_support_count: int = Field(ge=0)
    primary_support_evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=32)


def assess_convergence(
    observations: tuple[ConvergenceObservation, ...],
) -> ConvergenceResult:
    """Count independent channels while keeping authority and unknowns visible."""

    supportive = tuple(
        dict.fromkeys(
            item.channel
            for item in observations
            if item.direction is ObservationDirection.SUPPORTIVE
        )
    )
    contradictory = tuple(
        dict.fromkeys(
            item.channel
            for item in observations
            if item.direction is ObservationDirection.CONTRADICTORY
        )
    )
    unknown = tuple(
        dict.fromkeys(
            item.channel for item in observations if item.direction is ObservationDirection.UNKNOWN
        )
    )
    supportive_observations = tuple(
        item for item in observations if item.direction is ObservationDirection.SUPPORTIVE
    )
    # A channel is one independent observation stream; repeated excerpts from
    # that stream must not inflate convergence counts.
    primary_channels = tuple(
        dict.fromkeys(
            item.channel
            for item in supportive_observations
            if item.source_quality is SourceQuality.PRIMARY
        )
    )
    supporting_channels = tuple(
        dict.fromkeys(
            item.channel
            for item in supportive_observations
            if item.source_quality is SourceQuality.SUPPORTING
        )
    )
    lower_channels = tuple(
        dict.fromkeys(
            item.channel
            for item in supportive_observations
            if item.source_quality is SourceQuality.LOWER_CONFIDENCE
        )
    )
    primary_support = len(primary_channels)
    primary_evidence_ids = tuple(
        dict.fromkeys(
            evidence_id
            for item in supportive_observations
            if item.source_quality is SourceQuality.PRIMARY
            for evidence_id in item.evidence_ids
        )
    )
    if not supportive:
        conclusion = "insufficient_evidence"
    elif contradictory:
        conclusion = "mixed_evidence"
    elif primary_support:
        conclusion = "primary_supported"
    else:
        conclusion = "supporting_only"
    return ConvergenceResult(
        supportive_channels=supportive,
        contradictory_channels=contradictory,
        unknown_channels=unknown,
        conclusion=conclusion,
        primary_support_count=primary_support,
        supporting_support_count=len(supporting_channels),
        lower_confidence_support_count=len(lower_channels),
        primary_support_evidence_ids=primary_evidence_ids,
    )
