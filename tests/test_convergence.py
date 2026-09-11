"""Convergence stays explainable and never treats unknown as support."""

from uuid import UUID

from kalki_market_intelligence.contracts.evidence import SourceQuality
from kalki_market_intelligence.signals.convergence import (
    ConvergenceObservation,
    ObservationDirection,
    assess_convergence,
)


def test_primary_support_and_unknown_are_separate() -> None:
    result = assess_convergence(
        (
            ConvergenceObservation(
                channel="sec_filing",
                source_quality=SourceQuality.PRIMARY,
                direction=ObservationDirection.SUPPORTIVE,
                evidence_ids=(UUID("43000000-0000-4000-8000-000000000001"),),
            ),
            ConvergenceObservation(
                channel="price",
                source_quality=SourceQuality.SUPPORTING,
                direction=ObservationDirection.UNKNOWN,
            ),
        )
    )
    assert result.conclusion == "primary_supported"
    assert result.primary_support_count == 1
    assert result.supporting_support_count == 0
    assert result.unknown_channels == ("price",)


def test_convergence_counts_independent_channels_and_preserves_primary_evidence() -> None:
    evidence_id = UUID("43000000-0000-4000-8000-000000000002")
    result = assess_convergence(
        (
            ConvergenceObservation(
                channel="sec_filing",
                source_quality=SourceQuality.PRIMARY,
                direction=ObservationDirection.SUPPORTIVE,
                evidence_ids=(evidence_id,),
            ),
            ConvergenceObservation(
                channel="sec_filing",
                source_quality=SourceQuality.PRIMARY,
                direction=ObservationDirection.SUPPORTIVE,
                evidence_ids=(evidence_id,),
            ),
            ConvergenceObservation(
                channel="news",
                source_quality=SourceQuality.SUPPORTING,
                direction=ObservationDirection.SUPPORTIVE,
            ),
            ConvergenceObservation(
                channel="social",
                source_quality=SourceQuality.LOWER_CONFIDENCE,
                direction=ObservationDirection.SUPPORTIVE,
            ),
        )
    )

    assert result.primary_support_count == 1
    assert result.supporting_support_count == 1
    assert result.lower_confidence_support_count == 1
    assert result.primary_support_evidence_ids == (evidence_id,)
