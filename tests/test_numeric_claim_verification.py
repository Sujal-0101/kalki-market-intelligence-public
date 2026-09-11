"""Focused deterministic numeric claim verification tests."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from kalki_market_intelligence.quantitative.claim_verification import (
    NumericClaim,
    NumericVerification,
    NumericVerificationStatus,
    verify_numeric_claim,
)


def test_numeric_claim_is_verified_within_explicit_tolerance() -> None:
    result = verify_numeric_claim(
        NumericClaim(
            claim_id="C01",
            evidence_id="E17",
            claimed_value=Decimal("10.001"),
            source_value=Decimal("10.00"),
            tolerance=Decimal("0.001"),
            unit="USD millions",
        )
    )
    assert result.status is NumericVerificationStatus.VERIFIED
    assert result.calculation_version == "1.0.0"


def test_numeric_conflict_is_explicit_and_not_silently_rounded() -> None:
    result = verify_numeric_claim(
        NumericClaim(
            claim_id="C02",
            evidence_id="E18",
            claimed_value=Decimal("11"),
            source_value=Decimal("10"),
            unit="USD millions",
        )
    )
    assert result.status is NumericVerificationStatus.CONFLICTING
    assert result.source_value == Decimal("10")


def test_missing_source_value_is_unverifiable() -> None:
    result = verify_numeric_claim(
        NumericClaim(
            claim_id="C03",
            evidence_id="E19",
            claimed_value=Decimal("5"),
            unit="shares",
        )
    )
    assert result.status is NumericVerificationStatus.UNVERIFIABLE


def test_verification_contract_rejects_inconsistent_verified_status() -> None:
    with pytest.raises(ValidationError, match="exceeds its tolerance"):
        NumericVerification(
            claim_id="C04",
            evidence_id="E20",
            claimed_value=Decimal("9"),
            source_value=Decimal("10"),
            tolerance=Decimal("0"),
            status=NumericVerificationStatus.VERIFIED,
            note="incorrect",
        )
