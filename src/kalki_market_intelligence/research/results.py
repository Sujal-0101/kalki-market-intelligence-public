"""Bounded, private human-research result contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, StringConstraints, model_validator

from kalki_market_intelligence.analysis.attempts import AnalystAttemptReceipt
from kalki_market_intelligence.contracts.common import (
    ContractModel,
    Sha256Hex,
    ShortText,
    UtcDatetime,
)
from kalki_market_intelligence.forensics.detectors import ForensicSignal
from kalki_market_intelligence.forensics.tiers import TierDecision
from kalki_market_intelligence.quantitative.claim_verification import NumericVerification
from kalki_market_intelligence.research.intake import HumanResearchLead

type CanonicalCik = Annotated[str, StringConstraints(pattern=r"^\d{10}$")]
type AccessionNumber = Annotated[str, StringConstraints(pattern=r"^\d{10}-\d{2}-\d{6}$")]
type SecArchiveUrl = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=2_048,
        pattern=r"^https://www\.sec\.gov/Archives/edgar/data/",
    ),
]
type SecCompanyFactsUrl = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=2_048,
        pattern=r"^https://data\.sec\.gov/api/xbrl/companyfacts/",
    ),
]
type DiscordChannelId = Annotated[str, StringConstraints(pattern=r"^\d{17,20}$")]


class HumanResearchDisposition(StrEnum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    NOT_SUPPORTED = "not_supported"
    INCONCLUSIVE = "inconclusive"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    DUPLICATE = "duplicate"
    FAILED = "failed"


class HumanSourceStatus(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    RETRIEVAL_FAILED = "retrieval_failed"


class HumanAssessmentStatus(StrEnum):
    ASSESSED = "assessed"
    NOT_ASSESSED = "not_assessed"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class HumanSecSourceReceipt(ContractModel):
    """Authoritative filing identity, or an explicit absence/failure state."""

    status: HumanSourceStatus
    ticker: ShortText | None = None
    canonical_cik: CanonicalCik | None = None
    company_name: ShortText | None = None
    filing_form: ShortText | None = None
    accession_number: AccessionNumber | None = None
    authoritative_url: SecArchiveUrl | None = None
    source_document_sha256: Sha256Hex | None = None
    excerpt_sha256: Sha256Hex | None = None
    filed_at: UtcDatetime | None = None
    retrieved_at: UtcDatetime | None = None
    reason: ShortText

    @model_validator(mode="after")
    def resolved_source_is_complete(self) -> Self:
        values = (
            self.canonical_cik,
            self.company_name,
            self.filing_form,
            self.accession_number,
            self.authoritative_url,
            self.source_document_sha256,
            self.excerpt_sha256,
            self.filed_at,
            self.retrieved_at,
        )
        if self.status is HumanSourceStatus.RESOLVED and any(value is None for value in values):
            raise ValueError("resolved human SEC sources require complete immutable lineage")
        if self.status is not HumanSourceStatus.RESOLVED and any(
            value is not None for value in values
        ):
            raise ValueError("unresolved human SEC sources cannot claim filing lineage")
        if self.filed_at is not None and self.retrieved_at is not None:
            if self.retrieved_at < self.filed_at:
                raise ValueError("human SEC retrieval cannot precede filing")
        return self


class HumanXbrlReceipt(ContractModel):
    """Bounded CompanyFacts normalization receipt without retaining all facts."""

    status: HumanAssessmentStatus
    source_url: SecCompanyFactsUrl | None = None
    source_content_sha256: Sha256Hex | None = None
    retrieved_at: UtcDatetime | None = None
    normalized_fact_count: int | None = Field(default=None, ge=0)
    same_filing_fact_count: int | None = Field(default=None, ge=0)
    reason: ShortText

    @model_validator(mode="after")
    def assessed_xbrl_is_complete(self) -> Self:
        values = (
            self.source_url,
            self.source_content_sha256,
            self.retrieved_at,
            self.normalized_fact_count,
            self.same_filing_fact_count,
        )
        if self.status is HumanAssessmentStatus.ASSESSED and any(value is None for value in values):
            raise ValueError("assessed XBRL requires source lineage and bounded counts")
        if self.status is not HumanAssessmentStatus.ASSESSED and any(
            value is not None for value in values
        ):
            raise ValueError("unassessed XBRL cannot claim source lineage or counts")
        return self


class HumanFilingDiffReceipt(ContractModel):
    """Bounded filing-diff disposition; missing comparison inputs stay visible."""

    status: HumanAssessmentStatus
    calculation_version: Literal["1.0.0"] = "1.0.0"
    previous_accession_number: AccessionNumber | None = None
    current_accession_number: AccessionNumber | None = None
    previous_source_content_sha256: Sha256Hex | None = None
    current_source_content_sha256: Sha256Hex | None = None
    changed_sections: tuple[ShortText, ...] = Field(default=(), max_length=32)
    reason: ShortText


class HumanDeterministicVerificationReceipt(ContractModel):
    """Deterministic checks applied to accepted analyst claims."""

    status: HumanAssessmentStatus
    numeric_verifications: tuple[NumericVerification, ...] = Field(default=(), max_length=24)
    reason: ShortText


class HumanResearchResult(ContractModel):
    """Version-2 immutable result for future private human research."""

    result_id: UUID = Field(default_factory=uuid4)
    lead_id: UUID
    origin: Literal["human"] = "human"
    hypothesis: str = Field(min_length=1, max_length=2_000)
    source: HumanSecSourceReceipt
    evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=32)
    xbrl: HumanXbrlReceipt
    filing_diff: HumanFilingDiffReceipt
    forensic_receipts: tuple[ForensicSignal, ...] = Field(default=(), max_length=16)
    tier0_status: HumanAssessmentStatus
    tier0_decision: TierDecision | None = None
    analyst_status: HumanAssessmentStatus
    analyst_attempt_receipts: tuple[AnalystAttemptReceipt, ...] = Field(default=(), max_length=4)
    deterministic_verification: HumanDeterministicVerificationReceipt
    disposition: HumanResearchDisposition
    conclusion: str = Field(min_length=1, max_length=2_000)
    delivery_channel_id: DiscordChannelId
    created_at: UtcDatetime
    version: Literal["human-research-v2"] = "human-research-v2"

    @model_validator(mode="after")
    def lineage_is_consistent(self) -> Self:
        if (self.tier0_status is HumanAssessmentStatus.ASSESSED) != (
            self.tier0_decision is not None
        ):
            raise ValueError("Tier-0 assessment status must match its decision")
        if (self.analyst_status is HumanAssessmentStatus.ASSESSED) != bool(
            self.analyst_attempt_receipts
        ):
            raise ValueError("analyst assessment status must match its attempt receipts")
        if any(
            receipt.start.context.lead_id != self.lead_id
            or receipt.start.context.origin.value != "human"
            for receipt in self.analyst_attempt_receipts
        ):
            raise ValueError("human analyst receipts must belong to the result lead")
        attempt_ids = tuple(receipt.start.attempt_id for receipt in self.analyst_attempt_receipts)
        if len(set(attempt_ids)) != len(attempt_ids):
            raise ValueError("human analyst attempt receipts must be unique")
        if self.source.status is HumanSourceStatus.RESOLVED and not self.evidence_ids:
            raise ValueError("resolved human research requires evidence identity")
        return self

    @classmethod
    def from_lead(
        cls,
        lead: HumanResearchLead,
        *,
        source: HumanSecSourceReceipt,
        xbrl: HumanXbrlReceipt,
        filing_diff: HumanFilingDiffReceipt,
        forensic_receipts: tuple[ForensicSignal, ...],
        tier0_status: HumanAssessmentStatus,
        tier0_decision: TierDecision | None,
        analyst_status: HumanAssessmentStatus,
        analyst_attempt_receipts: tuple[AnalystAttemptReceipt, ...],
        deterministic_verification: HumanDeterministicVerificationReceipt,
        disposition: HumanResearchDisposition,
        conclusion: str,
        delivery_channel_id: str,
        evidence_ids: tuple[UUID, ...] = (),
        created_at: UtcDatetime,
    ) -> HumanResearchResult:
        return cls(
            lead_id=lead.lead_id,
            hypothesis=lead.hypothesis,
            source=source,
            evidence_ids=evidence_ids,
            xbrl=xbrl,
            filing_diff=filing_diff,
            forensic_receipts=forensic_receipts,
            tier0_status=tier0_status,
            tier0_decision=tier0_decision,
            analyst_status=analyst_status,
            analyst_attempt_receipts=analyst_attempt_receipts,
            deterministic_verification=deterministic_verification,
            disposition=disposition,
            conclusion=conclusion,
            delivery_channel_id=delivery_channel_id,
            created_at=created_at,
        )
