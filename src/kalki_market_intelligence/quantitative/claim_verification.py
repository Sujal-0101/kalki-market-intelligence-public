"""Deterministic verification results for numeric analyst claims."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints, model_validator

from kalki_market_intelligence.contracts.common import ContractModel, NonEmptyText, Sha256Hex

CLAIM_VERIFICATION_VERSION = "1.0.0"
type ClaimIdentifier = Annotated[str, StringConstraints(min_length=1, max_length=128)]


class NumericVerificationStatus(StrEnum):
    """Outcome of an independent deterministic numeric comparison."""

    VERIFIED = "verified"
    PARTIALLY_VERIFIED = "partially_verified"
    CONFLICTING = "conflicting"
    UNVERIFIABLE = "unverifiable"


class NumericClaim(ContractModel):
    """A numeric assertion tied to the exact evidence and calculation version."""

    claim_id: ClaimIdentifier
    evidence_id: ClaimIdentifier
    claimed_value: Decimal
    unit: NonEmptyText
    source_value: Decimal | None = None
    tolerance: Decimal = Field(default=Decimal("0"), ge=0)
    source_content_sha256: Sha256Hex | None = None
    xbrl_tag: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    form: str | None = None


class NumericVerification(ContractModel):
    """Immutable result suitable for audit and publication gating."""

    claim_id: ClaimIdentifier
    evidence_id: ClaimIdentifier
    claimed_value: Decimal
    source_value: Decimal | None
    tolerance: Decimal = Field(ge=0)
    status: NumericVerificationStatus
    calculation_version: str = CLAIM_VERIFICATION_VERSION
    source_content_sha256: Sha256Hex | None = None
    note: NonEmptyText

    @model_validator(mode="after")
    def status_matches_values(self) -> NumericVerification:
        if self.source_value is None and self.status is not NumericVerificationStatus.UNVERIFIABLE:
            raise ValueError("missing source value must be marked unverifiable")
        if self.source_value is not None and self.status is NumericVerificationStatus.UNVERIFIABLE:
            raise ValueError("present source value cannot be marked unverifiable")
        if (
            self.source_value is not None
            and self.status is NumericVerificationStatus.VERIFIED
            and abs(self.claimed_value - self.source_value) > self.tolerance
        ):
            raise ValueError("verified numeric result exceeds its tolerance")
        return self


def verify_numeric_claim(claim: NumericClaim) -> NumericVerification:
    """Compare a claimed value to an independently extracted source value."""

    if claim.source_value is None:
        return NumericVerification(
            claim_id=claim.claim_id,
            evidence_id=claim.evidence_id,
            claimed_value=claim.claimed_value,
            source_value=None,
            tolerance=claim.tolerance,
            status=NumericVerificationStatus.UNVERIFIABLE,
            source_content_sha256=claim.source_content_sha256,
            note="No independently extracted source value was available.",
        )
    delta = abs(claim.claimed_value - claim.source_value)
    if delta <= claim.tolerance:
        return NumericVerification(
            claim_id=claim.claim_id,
            evidence_id=claim.evidence_id,
            claimed_value=claim.claimed_value,
            source_value=claim.source_value,
            tolerance=claim.tolerance,
            status=NumericVerificationStatus.VERIFIED,
            source_content_sha256=claim.source_content_sha256,
            note="Claimed value matches the independently extracted value within tolerance.",
        )
    return NumericVerification(
        claim_id=claim.claim_id,
        evidence_id=claim.evidence_id,
        claimed_value=claim.claimed_value,
        source_value=claim.source_value,
        tolerance=claim.tolerance,
        status=NumericVerificationStatus.CONFLICTING,
        source_content_sha256=claim.source_content_sha256,
        note="Claimed value conflicts with the independently extracted value.",
    )
