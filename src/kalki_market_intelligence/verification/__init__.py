"""Selective independent semantic verification under deterministic authority."""

from kalki_market_intelligence.verification.provenance import dossier_provenance

__all__ = ["dossier_provenance"]

from kalki_market_intelligence.verification.contracts import (
    VerificationDisposition,
    VerifierReport,
    VerifierVerdict,
)

__all__ = ["VerificationDisposition", "VerifierReport", "VerifierVerdict"]
