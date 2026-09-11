"""Deterministic matching of analyst quantities to normalized SEC XBRL facts."""

from __future__ import annotations

from collections.abc import Sequence

from kalki_market_intelligence.providers.sec.contracts import SecFactRecord
from kalki_market_intelligence.quantitative.claim_verification import (
    NumericClaim,
    NumericVerification,
    NumericVerificationStatus,
    verify_numeric_claim,
)


def verify_numeric_claim_against_xbrl(
    claim: NumericClaim,
    facts: Sequence[SecFactRecord],
    *,
    accession_number: str,
) -> NumericVerification:
    """Use only same-filing facts and report ambiguity instead of guessing context."""

    if claim.xbrl_tag is None or claim.period_end is None or claim.form is None:
        return verify_numeric_claim(claim)
    candidates = tuple(
        fact
        for fact in facts
        if fact.accession_number == accession_number
        and fact.tag == claim.xbrl_tag
        and fact.period_end == claim.period_end
        and (claim.period_start is None or fact.period_start == claim.period_start)
        and fact.form == claim.form
        and fact.unit == claim.unit
    )
    values = tuple(dict.fromkeys(fact.value for fact in candidates))
    if not values:
        return verify_numeric_claim(claim)
    if len(values) == 1:
        value = values[0]
        if claim.unit == "reported_value" and abs(claim.claimed_value - value) > claim.tolerance:
            return verify_numeric_claim(claim)
        return verify_numeric_claim(claim.model_copy(update={"source_value": value}))
    matching = next(
        (value for value in values if abs(claim.claimed_value - value) <= claim.tolerance),
        None,
    )
    if matching is None:
        # Multiple unrelated contexts cannot establish a deterministic conflict.
        return verify_numeric_claim(claim)
    return NumericVerification(
        claim_id=claim.claim_id,
        evidence_id=claim.evidence_id,
        claimed_value=claim.claimed_value,
        source_value=matching,
        tolerance=claim.tolerance,
        status=NumericVerificationStatus.PARTIALLY_VERIFIED,
        source_content_sha256=claim.source_content_sha256,
        note="Claim matches one same-filing XBRL value, but multiple contexts remain.",
    )
