"""Closed contracts for filing discovery, research briefs, and worker visibility."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from kalki_market_intelligence.contracts.common import (
    ContractModel,
    NonEmptyText,
    Sha256Hex,
    ShortText,
    UtcDatetime,
)
from kalki_market_intelligence.quantitative.claim_verification import (
    NumericVerification,
    NumericVerificationStatus,
)

RADAR_SCHEMA_VERSION: Literal["2.0.0"] = "2.0.0"
RADAR_SCORING_VERSION: Literal["filing-radar-v1"] = "filing-radar-v1"

type AccessionNumber = Annotated[str, StringConstraints(pattern=r"^\d{10}-\d{2}-\d{6}$")]
type CikText = Annotated[str, StringConstraints(pattern=r"^\d{1,10}$")]
type TickerText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Z0-9][A-Z0-9.\-]{0,14}$"),
]
type SourceUrl = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=2_048,
        pattern=r"^https://www\.sec\.gov/Archives/edgar/data/",
    ),
]


class RadarClassification(StrEnum):
    """Editorial classification of a filing, never an instruction to transact."""

    OPPORTUNITY = "opportunity"
    MIXED = "mixed"
    RISK = "risk"
    WATCH = "watch"


class WorkerState(StrEnum):
    """Small public-safe state vocabulary for the supervised worker."""

    STARTING = "starting"
    RUNNING = "running"
    IDLE = "idle"
    DEGRADED = "degraded"
    WAITING_FOR_CONFIGURATION = "waiting_for_configuration"


class RunState(StrEnum):
    COMPLETED = "completed"
    DEGRADED = "degraded"
    FAILED = "failed"


class FilingCandidate(ContractModel):
    """One authoritative SEC master-index row selected for deeper review."""

    accession_number: AccessionNumber
    cik: CikText
    company_name: ShortText
    ticker: TickerText | None
    exchange: ShortText | None
    filing_form: ShortText
    filed_at: UtcDatetime
    source_url: SourceUrl
    discovered_at: UtcDatetime

    @model_validator(mode="after")
    def discovery_follows_filing(self) -> Self:
        if self.discovered_at < self.filed_at:
            raise ValueError("filing discovery cannot precede the filing date")
        return self


class BriefEvidence(ContractModel):
    """Public quote-level support tied to the immutable SEC document hash."""

    evidence_id: UUID
    quote: NonEmptyText
    excerpt_sha256: Sha256Hex
    source_url: SourceUrl
    source_document_sha256: Sha256Hex
    available_at: UtcDatetime
    retrieved_at: UtcDatetime

    @model_validator(mode="after")
    def retrieval_follows_availability(self) -> Self:
        if self.retrieved_at < self.available_at:
            raise ValueError("brief evidence retrieval must follow availability")
        return self


class PublicVerificationReceipt(ContractModel):
    """Deliberately small public lineage for a successfully verified publication."""

    status: Literal["passed"] = "passed"
    verifier_model_name: ShortText
    verifier_model_digest: Sha256Hex
    verifier_prompt_version: Literal["verifier-v1"] = "verifier-v1"
    verifier_schema_version: Literal["1.0.0"] = "1.0.0"
    deterministic_validation_version: Literal["1.0.0"] = "1.0.0"
    reviewed_at: UtcDatetime
    analyst_retry_count: int = Field(ge=0, le=1)


class PublicationGateMode(StrEnum):
    """Truthful public description of the gate used for a new dossier."""

    DETERMINISTIC_ONLY = "deterministic_only"
    INDEPENDENT_VERIFIER = "independent_verifier"


class PublicPublicationGateReceipt(ContractModel):
    """Public-safe proof that deterministic publication checks passed."""

    status: Literal["passed"] = "passed"
    mode: PublicationGateMode
    deterministic_validation_version: Literal["1.0.0"] = "1.0.0"
    validated_at: UtcDatetime
    independent_verifier_status: Literal["disabled", "passed"]

    @model_validator(mode="after")
    def verifier_status_matches_mode(self) -> Self:
        if (self.mode is PublicationGateMode.INDEPENDENT_VERIFIER) != (
            self.independent_verifier_status == "passed"
        ):
            raise ValueError("publication gate mode must match verifier status")
        return self


class ResearchBrief(ContractModel):
    """Immutable filing-radar publication with validated AI lineage."""

    brief_id: UUID
    schema_version: Literal["1.0.0", "2.0.0", "3.0.0"] = "1.0.0"
    accession_number: AccessionNumber
    cik: CikText
    company_name: ShortText
    ticker: TickerText | None
    exchange: ShortText | None
    filing_form: ShortText
    filed_at: UtcDatetime
    retrieved_at: UtcDatetime
    published_at: UtcDatetime
    source_url: SourceUrl
    source_document_sha256: Sha256Hex
    classification: RadarClassification
    attention_points: int = Field(ge=0, le=100)
    risk_points: int = Field(ge=0, le=100)
    evidence_strength_points: int = Field(ge=0, le=100)
    score_interpretation: Literal["heuristic_research_priority_not_probability"] = (
        "heuristic_research_priority_not_probability"
    )
    headline: ShortText
    summary: NonEmptyText
    why_it_matters: NonEmptyText
    evidence: tuple[BriefEvidence, ...] = Field(min_length=1, max_length=12)
    numeric_verifications: tuple[NumericVerification, ...] = Field(default=(), max_length=24)
    model_name: ShortText
    model_digest: Sha256Hex
    prompt_version: Literal["analyst-v1", "analyst-v2"]
    scoring_version: Literal["filing-radar-v1"] = RADAR_SCORING_VERSION
    verification: PublicVerificationReceipt | None = None
    publication_gate: PublicPublicationGateReceipt | None = None
    limitations: tuple[ShortText, ...] = Field(min_length=1, max_length=8)
    disclaimer: Literal[
        "Research radar only; not advice, a return promise, probability, or trade instruction."
    ] = "Research radar only; not advice, a return promise, probability, or trade instruction."

    @model_validator(mode="after")
    def publication_is_temporally_and_evidentially_consistent(self) -> Self:
        if self.retrieved_at < self.filed_at:
            raise ValueError("brief retrieval cannot precede filing")
        if self.published_at < self.retrieved_at:
            raise ValueError("brief publication cannot precede retrieval")
        identifiers = tuple(item.evidence_id for item in self.evidence)
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("brief evidence IDs must be unique")
        if any(
            item.source_url != self.source_url
            or item.source_document_sha256 != self.source_document_sha256
            or item.retrieved_at > self.published_at
            for item in self.evidence
        ):
            raise ValueError("brief evidence lineage does not match its source publication")
        if any(
            item.status is NumericVerificationStatus.CONFLICTING
            for item in self.numeric_verifications
        ):
            raise ValueError("conflicting numeric claims cannot reach publication")
        if self.schema_version == RADAR_SCHEMA_VERSION and self.verification is None:
            raise ValueError("version 2 radar briefs require an independent verification receipt")
        if self.schema_version in {"1.0.0", "2.0.0"} and self.publication_gate is not None:
            raise ValueError("historical radar briefs cannot claim a version 3 publication gate")
        if self.schema_version == "1.0.0" and self.verification is not None:
            raise ValueError("historical version 1 radar briefs cannot claim independent review")
        if self.schema_version == "3.0.0":
            if self.publication_gate is None:
                raise ValueError("version 3 radar briefs require a publication gate receipt")
            independently_verified = (
                self.publication_gate.mode is PublicationGateMode.INDEPENDENT_VERIFIER
            )
            if independently_verified != (self.verification is not None):
                raise ValueError("version 3 verifier lineage must match its publication gate")
        if self.verification is not None and self.verification.reviewed_at > self.published_at:
            raise ValueError("independent review must complete before publication")
        if (
            self.publication_gate is not None
            and self.publication_gate.validated_at > self.published_at
        ):
            raise ValueError("deterministic publication validation must precede publication")
        return self


class WorkerSnapshot(ContractModel):
    """Public-safe operational state; errors are bounded codes, never raw messages."""

    worker_name: Literal["filing-radar"] = "filing-radar"
    state: WorkerState
    heartbeat_at: UtcDatetime
    last_success_at: UtcDatetime | None
    next_run_at: UtcDatetime | None
    last_error_code: ShortText | None
    discovered_count: int = Field(ge=0)
    pending_count: int = Field(ge=0)
    published_count: int = Field(ge=0)
    discord_enabled: bool
    model_name: ShortText
    source_name: Literal["SEC EDGAR daily master index"] = "SEC EDGAR daily master index"
    verifier_enabled: bool = False
    verifier_model_name: ShortText | None = None
    verifier_reviews: int = Field(default=0, ge=0)
    verifier_approvals: int = Field(default=0, ge=0)
    verifier_challenges: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def verifier_identity_matches_state(self) -> Self:
        if self.verifier_enabled != (self.verifier_model_name is not None):
            raise ValueError("enabled verifier status requires a bounded model identity")
        if self.verifier_approvals + self.verifier_challenges > self.verifier_reviews:
            raise ValueError("verifier outcomes cannot exceed completed reviews")
        return self


class RadarRun(ContractModel):
    run_id: UUID
    started_at: UtcDatetime
    completed_at: UtcDatetime
    state: RunState
    discovered_count: int = Field(ge=0)
    analyzed_count: int = Field(ge=0)
    published_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    error_code: ShortText | None

    @model_validator(mode="after")
    def completion_follows_start(self) -> Self:
        if self.completed_at < self.started_at:
            raise ValueError("radar run completion cannot precede its start")
        return self
