"""Closed contracts for the independent publication-stage verifier."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal, Self, cast
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from kalki_market_intelligence.contracts.common import (
    ContractModel,
    NonEmptyText,
    Sha256Hex,
    ShortText,
    UtcDatetime,
)
from kalki_market_intelligence.forensics.detectors import ForensicSignal
from kalki_market_intelligence.forensics.filing_diff import FilingDiff
from kalki_market_intelligence.quantitative.claim_verification import NumericVerification

VERIFIER_PACKAGE_VERSION: Literal["1.0.0"] = "1.0.0"
VERIFIER_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
VERIFIER_PROMPT_VERSION: Literal["verifier-v1"] = "verifier-v1"
VERIFIER_VALIDATION_VERSION: Literal["1.0.0"] = "1.0.0"

type ClaimId = Annotated[str, StringConstraints(pattern=r"^C[0-9]{2}$")]
type ReviewNote = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]
type NumericToken = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
]


class VerifierVerdict(StrEnum):
    APPROVE = "approve"
    CHALLENGE = "challenge"


class ClassificationSupport(StrEnum):
    SUPPORTED = "supported"
    TOO_BULLISH = "too_bullish"
    TOO_BEARISH = "too_bearish"
    INSUFFICIENT = "insufficient"


class ChallengeCategory(StrEnum):
    MISSING_MATERIAL_RISK = "missing_material_risk"
    MISSING_MATERIAL_CATALYST = "missing_material_catalyst"
    UNSUPPORTED_INTERPRETATION = "unsupported_interpretation"
    CLASSIFICATION_TOO_BULLISH = "classification_too_bullish"
    CLASSIFICATION_TOO_BEARISH = "classification_too_bearish"
    UNCERTAINTY_OVERSTATED = "uncertainty_overstated"
    IDENTITY_CONCERN = "identity_concern"
    NUMERIC_CONCERN = "numeric_concern"
    MISSING_COUNTEREVIDENCE = "missing_counterevidence"


class VerificationDisposition(StrEnum):
    APPROVED = "approved"
    VERIFICATION_DISAGREEMENT = "verification_disagreement"
    ANALYST_RETRY_REJECTED = "analyst_retry_rejected"


class DeterministicFilingFacts(ContractModel):
    accession_number: ShortText
    cik: ShortText
    company_name: ShortText
    ticker: ShortText | None
    exchange: ShortText | None
    filing_form: ShortText
    source_url: ShortText
    source_document_sha256: Sha256Hex
    excerpt_sha256: Sha256Hex
    filed_at: UtcDatetime
    retrieved_at: UtcDatetime
    opportunity_terms: tuple[ShortText, ...] = Field(max_length=32)
    risk_terms: tuple[ShortText, ...] = Field(max_length=32)
    identity_authority: Literal["sec_daily_index_and_official_ticker_mapping"] = (
        "sec_daily_index_and_official_ticker_mapping"
    )


class VerifierEvidence(ContractModel):
    evidence_id: UUID
    text: NonEmptyText
    content_sha256: Sha256Hex
    source_url: ShortText


class CandidateClaim(ContractModel):
    claim_id: ClaimId
    kind: ShortText
    category: ShortText
    polarity: ShortText
    statement: NonEmptyText
    evidence_ids: tuple[UUID, ...] = Field(min_length=1, max_length=4)


class CandidateDossier(ContractModel):
    candidate_id: UUID
    classification: Literal["opportunity", "mixed", "risk", "watch"]
    attention_points: int = Field(ge=0, le=100)
    risk_points: int = Field(ge=0, le=100)
    evidence_strength_points: int = Field(ge=0, le=100)
    summary: NonEmptyText
    why_it_matters: NonEmptyText
    claims: tuple[CandidateClaim, ...] = Field(min_length=1, max_length=24)
    numeric_verifications: tuple[NumericVerification, ...] = Field(default=(), max_length=24)
    forensic_signals: tuple[ForensicSignal, ...] = Field(default=(), max_length=16)
    filing_diff: FilingDiff | None = None
    analyst_model_name: ShortText
    analyst_model_digest: Sha256Hex
    analyst_prompt_version: ShortText


class VerifierPackage(ContractModel):
    package_version: Literal["1.0.0"] = VERIFIER_PACKAGE_VERSION
    facts: DeterministicFilingFacts
    evidence: tuple[VerifierEvidence, ...] = Field(min_length=1, max_length=8)
    classification_definitions: dict[str, str]
    candidate: CandidateDossier

    @model_validator(mode="after")
    def references_stay_inside_the_bounded_package(self) -> Self:
        evidence_ids = tuple(item.evidence_id for item in self.evidence)
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("verifier evidence IDs must be unique")
        claim_ids = tuple(item.claim_id for item in self.candidate.claims)
        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError("verifier claim IDs must be unique")
        allowed = set(evidence_ids)
        if any(not set(claim.evidence_ids).issubset(allowed) for claim in self.candidate.claims):
            raise ValueError("candidate claims must reference supplied verifier evidence")
        allowed_claim_ids = set(claim_ids)
        if any(
            item.claim_id not in allowed_claim_ids for item in self.candidate.numeric_verifications
        ):
            raise ValueError("numeric verifications must reference supplied candidate claims")
        if any(
            item.evidence_id and item.evidence_id not in {str(value) for value in allowed}
            for item in self.candidate.numeric_verifications
        ):
            raise ValueError("numeric verifications must reference supplied verifier evidence")
        if (
            self.candidate.filing_diff is not None
            and self.candidate.filing_diff.current_accession_number != self.facts.accession_number
        ):
            raise ValueError("filing diff must describe the candidate accession")
        required_definitions = {"opportunity", "mixed", "risk", "watch"}
        if set(self.classification_definitions) != required_definitions:
            raise ValueError("verifier package must define every publication classification")
        return self


class NumericConcern(ContractModel):
    claim_id: ClaimId
    evidence_id: UUID
    numeric_token: NumericToken
    concern: ReviewNote


class VerifierReport(ContractModel):
    schema_version: Literal["1.0.0"] = VERIFIER_SCHEMA_VERSION
    verdict: VerifierVerdict
    classification_support: ClassificationSupport
    identity_concern: bool
    numeric_concerns: tuple[NumericConcern, ...] = Field(max_length=8)
    unsupported_claim_ids: tuple[ClaimId, ...] = Field(max_length=12)
    missing_material_risk_evidence_ids: tuple[UUID, ...] = Field(max_length=8)
    missing_material_catalyst_evidence_ids: tuple[UUID, ...] = Field(max_length=8)
    material_omissions: tuple[ReviewNote, ...] = Field(max_length=8)
    uncertainty_concern: bool
    challenge_categories: tuple[ChallengeCategory, ...] = Field(max_length=9)
    brief_review_note: ReviewNote

    @model_validator(mode="after")
    def verdict_matches_bounded_findings(self) -> Self:
        collections = (
            self.numeric_concerns,
            self.unsupported_claim_ids,
            self.missing_material_risk_evidence_ids,
            self.missing_material_catalyst_evidence_ids,
            self.material_omissions,
            self.challenge_categories,
        )
        has_concern = self.identity_concern or self.uncertainty_concern or any(collections)
        if self.classification_support is not ClassificationSupport.SUPPORTED:
            has_concern = True
        if self.verdict is VerifierVerdict.APPROVE and has_concern:
            raise ValueError("verifier approval cannot contain a material concern")
        if self.verdict is VerifierVerdict.CHALLENGE and not has_concern:
            raise ValueError("verifier challenge must identify a bounded concern")
        for values, label in (
            (self.unsupported_claim_ids, "unsupported claim IDs"),
            (self.missing_material_risk_evidence_ids, "missing-risk evidence IDs"),
            (self.missing_material_catalyst_evidence_ids, "missing-catalyst evidence IDs"),
            (self.challenge_categories, "challenge categories"),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"verifier {label} must be unique")
        return self


class VerifierAudit(ContractModel):
    review_id: UUID
    candidate_id: UUID
    review_number: int = Field(ge=1, le=2)
    provider_name: ShortText
    model_name: ShortText
    model_digest: Sha256Hex
    prompt_version: Literal["verifier-v1"] = VERIFIER_PROMPT_VERSION
    schema_version: Literal["1.0.0"] = VERIFIER_SCHEMA_VERSION
    validation_version: Literal["1.0.0"] = VERIFIER_VALIDATION_VERSION
    completed_at: UtcDatetime
    attempts: int = Field(ge=1, le=2)
    evidence_ids: tuple[UUID, ...] = Field(min_length=1, max_length=8)
    report: VerifierReport
    deterministic_refutations: tuple[ShortText, ...] = Field(max_length=8)


class ArbitrationResult(ContractModel):
    approved: bool
    material_challenges: tuple[ChallengeCategory, ...]
    relevant_evidence_ids: tuple[UUID, ...]
    relevant_claim_ids: tuple[ClaimId, ...]
    deterministic_refutations: tuple[ShortText, ...]

    @model_validator(mode="after")
    def approval_has_no_material_challenge(self) -> Self:
        if self.approved and self.material_challenges:
            raise ValueError("approved arbitration cannot retain material challenges")
        if not self.approved and not self.material_challenges:
            raise ValueError("rejected arbitration requires a material challenge")
        return self


class VerificationOutcome(ContractModel):
    disposition_id: UUID
    candidate_id: UUID
    accession_number: ShortText
    disposition: VerificationDisposition
    retry_count: int = Field(ge=0, le=1)
    decided_at: UtcDatetime
    analyst_model_name: ShortText
    analyst_model_digest: Sha256Hex
    verifier_model_name: ShortText
    verifier_model_digest: Sha256Hex
    audits: tuple[VerifierAudit, ...] = Field(min_length=1, max_length=2)
    final_challenge_categories: tuple[ChallengeCategory, ...] = Field(max_length=9)
    final_evidence_ids: tuple[UUID, ...] = Field(max_length=8)

    @model_validator(mode="after")
    def disposition_matches_reviews(self) -> Self:
        expected_reviews = (
            1
            if self.disposition is VerificationDisposition.ANALYST_RETRY_REJECTED
            else self.retry_count + 1
        )
        if len(self.audits) != expected_reviews:
            raise ValueError("verification reviews must match the semantic retry count")
        if self.disposition is VerificationDisposition.APPROVED:
            if self.final_challenge_categories:
                raise ValueError("approved verification cannot retain challenges")
        elif not self.final_challenge_categories:
            raise ValueError("non-public verification requires a challenge category")
        return self


def verifier_generation_schema() -> dict[str, object]:
    """Keep Ollama's grammar bounded while full Pydantic validation remains final."""

    def simplify(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: simplify(item)
                for key, item in value.items()
                if key not in {"default", "description", "maxItems", "maxLength", "title"}
            }
        if isinstance(value, list):
            return [simplify(item) for item in value]
        return value

    return cast(dict[str, object], simplify(VerifierReport.model_json_schema()))
