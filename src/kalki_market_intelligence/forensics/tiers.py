"""Deterministic resource-aware analysis tier decisions."""

from __future__ import annotations

from enum import IntEnum, StrEnum
from uuid import UUID

from pydantic import Field

from kalki_market_intelligence.contracts.common import ContractModel, ShortText
from kalki_market_intelligence.forensics.detectors import ForensicSignal


class AnalysisTier(IntEnum):
    TIER_0 = 0
    TIER_1 = 1
    TIER_2 = 2
    TIER_3 = 3
    TIER_4 = 4


class EscalationReason(StrEnum):
    NO_RESEARCH_SIGNAL = "no_research_signal"
    OWNERSHIP_CONTEXT = "ownership_context"
    FINANCING_CONTEXT = "financing_context"
    ACCOUNTING_COMPLIANCE_CONTEXT = "accounting_compliance_context"
    MATERIAL_EVENT = "material_event"
    AMBIGUOUS_EVIDENCE = "ambiguous_evidence"
    DETERMINISTIC_CONTRADICTION = "deterministic_contradiction"
    PUBLICATION_REVIEW = "publication_review"


class TierOutcome(StrEnum):
    SKIP = "skip"
    RETAIN = "retain"
    ESCALATE = "escalate"


class TierDecision(ContractModel):
    tier: AnalysisTier
    outcome: TierOutcome
    reason: EscalationReason
    requires_model: bool
    explanation: ShortText
    estimated_context_chars: int = Field(ge=0, le=20_000)
    evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=16)
    forensic_signals: tuple[ForensicSignal, ...] = Field(default=(), max_length=16)


def choose_tier(
    *,
    research_relevant: bool,
    material_terms: bool,
    ambiguous: bool = False,
    deterministic_contradiction: bool = False,
    publication_candidate: bool = False,
    context_chars: int = 0,
    evidence_ids: tuple[UUID, ...] = (),
    forensic_uncertain: bool = False,
    forensic_signals: tuple[ForensicSignal, ...] = (),
) -> TierDecision:
    """Choose the least expensive tier justified by deterministic observations."""

    if not research_relevant:
        return TierDecision(
            tier=AnalysisTier.TIER_0,
            outcome=TierOutcome.SKIP,
            reason=EscalationReason.NO_RESEARCH_SIGNAL,
            requires_model=False,
            explanation="No bounded research signal requires model interpretation.",
            estimated_context_chars=context_chars,
            evidence_ids=evidence_ids,
            forensic_signals=forensic_signals,
        )
    if forensic_uncertain and not material_terms:
        return TierDecision(
            tier=AnalysisTier.TIER_0,
            outcome=TierOutcome.RETAIN,
            reason=EscalationReason.AMBIGUOUS_EVIDENCE,
            requires_model=False,
            explanation="Uncertain forensic inputs are retained without increasing confidence.",
            estimated_context_chars=context_chars,
            evidence_ids=evidence_ids,
            forensic_signals=forensic_signals,
        )
    if deterministic_contradiction:
        tier = AnalysisTier.TIER_3
        reason = EscalationReason.DETERMINISTIC_CONTRADICTION
    elif publication_candidate:
        tier = AnalysisTier.TIER_3
        reason = EscalationReason.PUBLICATION_REVIEW
    elif ambiguous:
        tier = AnalysisTier.TIER_1
        reason = EscalationReason.AMBIGUOUS_EVIDENCE
    elif material_terms:
        tier = AnalysisTier.TIER_2
        reason = EscalationReason.MATERIAL_EVENT
    else:
        tier = AnalysisTier.TIER_0
        reason = EscalationReason.NO_RESEARCH_SIGNAL
    outcome = TierOutcome.ESCALATE if tier is not AnalysisTier.TIER_0 else TierOutcome.RETAIN
    return TierDecision(
        tier=tier,
        outcome=outcome,
        reason=reason,
        requires_model=tier is not AnalysisTier.TIER_0,
        explanation=f"Deterministic routing selected tier {tier.value} for {reason.value}.",
        estimated_context_chars=context_chars,
        evidence_ids=evidence_ids,
        forensic_signals=forensic_signals,
    )
