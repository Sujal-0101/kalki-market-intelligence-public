"""Tier routing must stop obvious noise before local-model inference."""

from kalki_market_intelligence.forensics import (
    AnalysisTier,
    EscalationReason,
    TierOutcome,
    choose_tier,
)


def test_irrelevant_filing_stops_at_tier_zero() -> None:
    decision = choose_tier(research_relevant=False, material_terms=False)
    assert decision.tier is AnalysisTier.TIER_0
    assert decision.reason is EscalationReason.NO_RESEARCH_SIGNAL
    assert not decision.requires_model
    assert decision.outcome is TierOutcome.SKIP


def test_publication_candidate_escalates_to_independent_review() -> None:
    decision = choose_tier(
        research_relevant=True,
        material_terms=True,
        publication_candidate=True,
    )
    assert decision.tier is AnalysisTier.TIER_3
    assert decision.reason is EscalationReason.PUBLICATION_REVIEW
    assert decision.requires_model
    assert decision.outcome is TierOutcome.ESCALATE


def test_uncertain_forensics_retain_without_model_escalation() -> None:
    decision = choose_tier(
        research_relevant=True,
        material_terms=False,
        forensic_uncertain=True,
    )
    assert decision.tier is AnalysisTier.TIER_0
    assert decision.outcome is TierOutcome.RETAIN
    assert not decision.requires_model
