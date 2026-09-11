"""Private-safe provenance projection for analyst/verifier inspection."""

from __future__ import annotations

from typing import Any

from kalki_market_intelligence.verification.contracts import VerifierPackage


def dossier_provenance(package: VerifierPackage) -> dict[str, Any]:
    """Project lineage without prompts, raw traces, or hidden model reasoning."""

    return {
        "accession_number": package.facts.accession_number,
        "cik": package.facts.cik,
        "source_url": package.facts.source_url,
        "source_document_sha256": package.facts.source_document_sha256,
        "excerpt_sha256": package.facts.excerpt_sha256,
        "evidence": [item.model_dump(mode="json") for item in package.evidence],
        "numeric_verifications": [
            item.model_dump(mode="json") for item in package.candidate.numeric_verifications
        ],
        "forensic_signals": [
            item.model_dump(mode="json") for item in package.candidate.forensic_signals
        ],
        "filing_diff": (
            package.candidate.filing_diff.model_dump(mode="json")
            if package.candidate.filing_diff is not None
            else None
        ),
    }
