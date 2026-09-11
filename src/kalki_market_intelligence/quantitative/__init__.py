"""Deterministic, lineage-preserving quantitative calculations."""

from kalki_market_intelligence.quantitative.claim_verification import (
    CLAIM_VERIFICATION_VERSION,
    NumericClaim,
    NumericVerification,
    NumericVerificationStatus,
    verify_numeric_claim,
)
from kalki_market_intelligence.quantitative.engine import QuantitativeEngine
from kalki_market_intelligence.quantitative.xbrl_claims import verify_numeric_claim_against_xbrl

__all__ = [
    "CLAIM_VERIFICATION_VERSION",
    "NumericClaim",
    "NumericVerification",
    "NumericVerificationStatus",
    "QuantitativeEngine",
    "verify_numeric_claim",
    "verify_numeric_claim_against_xbrl",
]
