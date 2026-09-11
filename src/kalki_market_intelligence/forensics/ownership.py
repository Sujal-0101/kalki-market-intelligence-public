"""Conservative Tier-0 routing for primary-source SEC ownership receipts."""

from __future__ import annotations

from enum import StrEnum

from kalki_market_intelligence.contracts.common import ContractModel, Sha256Hex
from kalki_market_intelligence.forensics.tiers import (
    AnalysisTier,
    EscalationReason,
    TierDecision,
    TierOutcome,
    choose_tier,
)
from kalki_market_intelligence.providers.sec.contracts import AccessionNumber
from kalki_market_intelligence.providers.sec.ownership import (
    ActivistControlIntentStatus,
    OwnershipFilingReceipt,
    OwnershipForm,
    ScheduleTransition,
    classify_schedule_transition,
)


class OwnershipEventContext(StrEnum):
    INSIDER_OWNERSHIP_DISCLOSURE = "INSIDER_OWNERSHIP_DISCLOSURE"
    PLANNED_SALE_NOTICE = "PLANNED_SALE_NOTICE"
    BENEFICIAL_OWNERSHIP_DISCLOSURE = "BENEFICIAL_OWNERSHIP_DISCLOSURE"
    CONTROL_PURPOSE_TEXT = "CONTROL_PURPOSE_TEXT"
    SCHEDULE_TRANSITION = "SCHEDULE_TRANSITION"


class OwnershipTier0Receipt(ContractModel):
    accession_number: AccessionNumber
    source_content_sha256: Sha256Hex
    event_context: OwnershipEventContext
    schedule_transition: ScheduleTransition
    decision: TierDecision
    routing_version: str = "ownership-tier0-v1"


def choose_ownership_tier(
    receipt: OwnershipFilingReceipt,
    *,
    previous_schedule_form: OwnershipForm | None = None,
) -> OwnershipTier0Receipt:
    """Route ownership context without treating an insider sale as bearish evidence."""

    transition = classify_schedule_transition(previous_schedule_form, receipt.form)
    has_transition = transition in {
        ScheduleTransition.THIRTEEN_G_TO_THIRTEEN_D,
        ScheduleTransition.THIRTEEN_D_TO_THIRTEEN_G,
    }
    has_control_text = (
        receipt.activist_control_intent_status
        is ActivistControlIntentStatus.DISCLOSED_TEXT_REQUIRES_REVIEW
    )
    if has_transition:
        event_context = OwnershipEventContext.SCHEDULE_TRANSITION
    elif has_control_text:
        event_context = OwnershipEventContext.CONTROL_PURPOSE_TEXT
    elif receipt.form in {OwnershipForm.FORM_144, OwnershipForm.FORM_144_A}:
        event_context = OwnershipEventContext.PLANNED_SALE_NOTICE
    elif receipt.form.is_schedule_13d or receipt.form.is_schedule_13g:
        event_context = OwnershipEventContext.BENEFICIAL_OWNERSHIP_DISCLOSURE
    else:
        event_context = OwnershipEventContext.INSIDER_OWNERSHIP_DISCLOSURE

    if has_transition or has_control_text:
        decision = choose_tier(
            research_relevant=True,
            material_terms=True,
            context_chars=len(receipt.disclosed_transaction_purpose or ""),
        )
    else:
        decision = TierDecision(
            tier=AnalysisTier.TIER_0,
            outcome=TierOutcome.RETAIN,
            reason=EscalationReason.OWNERSHIP_CONTEXT,
            requires_model=False,
            explanation="Ownership context is retained without directional interpretation.",
            estimated_context_chars=0,
        )
    return OwnershipTier0Receipt(
        accession_number=receipt.accession_number,
        source_content_sha256=receipt.source_content_sha256,
        event_context=event_context,
        schedule_transition=transition,
        decision=decision,
    )
