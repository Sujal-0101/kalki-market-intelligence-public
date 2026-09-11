"""Closed public and administrative web contracts."""

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from kalki_market_intelligence.contracts.common import (
    ContractModel,
    NonEmptyText,
    Sha256Hex,
    ShortText,
    UtcDatetime,
)
from kalki_market_intelligence.predictions.contracts import PredictionRecord
from kalki_market_intelligence.radar.contracts import (
    RadarClassification,
    ResearchBrief,
    SourceUrl,
)
from kalki_market_intelligence.signals.contracts import RiskProfile, SignalLabel

PUBLIC_RESEARCH_DISCLAIMER: Literal[
    "Research only; not financial advice, a return promise, probability, or trade instruction."
] = "Research only; not financial advice, a return promise, probability, or trade instruction."


class PublicScores(ContractModel):
    """Separate heuristic dimensions exposed without probability language."""

    opportunity_points: int = Field(ge=0, le=100)
    risk_points: int = Field(ge=0, le=100)
    research_confidence_points: int = Field(ge=0, le=100)
    interpretation: Literal["heuristic_points_not_probability"] = "heuristic_points_not_probability"


class PublicEvidenceReference(ContractModel):
    """Public evidence lineage without raw source content or operational paths."""

    evidence_id: UUID
    content_sha256: Sha256Hex
    available_at: UtcDatetime
    retrieved_at: UtcDatetime


class PublicResearchSummary(ContractModel):
    """Bounded list representation for a published immutable prediction."""

    prediction_id: UUID
    research_subject_id: UUID
    published_at: UtcDatetime
    evaluation_due_on: date
    horizon_days: int = Field(ge=30, le=180)
    label: SignalLabel
    risk_profile: RiskProfile
    scores: PublicScores
    evidence_count: int = Field(ge=1)
    disclaimer: Literal[
        "Research only; not financial advice, a return promise, probability, or trade instruction."
    ] = PUBLIC_RESEARCH_DISCLAIMER


class PublicResearchDetail(PublicResearchSummary):
    """Evidence-backed detail representation for one publication."""

    thesis: NonEmptyText
    signal_fingerprint: Sha256Hex
    signal_ruleset_version: ShortText
    evidence: tuple[PublicEvidenceReference, ...] = Field(min_length=1)
    calculation_versions: tuple[ShortText, ...] = Field(min_length=1)
    analysis_prompt_versions: tuple[ShortText, ...] = Field(min_length=1)
    analysis_model_versions: tuple[ShortText, ...] = Field(min_length=1)


class PublicDossierSummary(ContractModel):
    """One evidence-backed filing dossier in the combined public library."""

    record_type: Literal["dossier"] = "dossier"
    brief_id: UUID
    canonical_url: ShortText
    published_at: UtcDatetime
    company_name: ShortText
    ticker: ShortText | None
    filing_form: ShortText
    classification: RadarClassification
    attention_points: int = Field(ge=0, le=100)
    risk_points: int = Field(ge=0, le=100)
    evidence_strength_points: int = Field(ge=0, le=100)
    evidence_count: int = Field(ge=1)


class PublicForecastSummary(PublicResearchSummary):
    """One explicit forecast record in the combined public library."""

    record_type: Literal["forecast"] = "forecast"
    canonical_url: ShortText


PublicResearchIndexItem = Annotated[
    PublicDossierSummary | PublicForecastSummary,
    Field(discriminator="record_type"),
]


class PublicScreeningReason(StrEnum):
    """Public-safe reasons for completed non-qualifying autonomous evaluation."""

    DETERMINISTIC_CRITERIA_NOT_MET = "deterministic_criteria_not_met"
    NO_VALIDATED_FINDINGS = "no_validated_findings"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    VERIFICATION_DISAGREEMENT = "verification_disagreement"


class PublicScreenedFiling(ContractModel):
    """Closed projection that cannot carry private or operational content."""

    ticker: ShortText | None
    company_name: ShortText
    filing_form: ShortText
    filed_at: UtcDatetime
    screened_at: UtcDatetime
    terminal_result: Literal["SCREENED_OUT"] = "SCREENED_OUT"
    reason: PublicScreeningReason
    source_url: SourceUrl


class PublicScreeningWindow(ContractModel):
    """Truthful prospective decision counts for one fixed UTC window."""

    hours: Literal[24, 168]
    telemetry_complete: bool
    processed: int = Field(ge=0)
    completed_deep_analysis: int = Field(ge=0)
    screened_out: int = Field(ge=0)
    qualified: int = Field(ge=0)
    analysis_incomplete: int = Field(ge=0)


class PublicScreeningActivity(ContractModel):
    """Prospective public screening summary with an explicit telemetry epoch."""

    observed_at: UtcDatetime
    telemetry_started_at: UtcDatetime
    windows: tuple[PublicScreeningWindow, PublicScreeningWindow]


class AuditEventType(StrEnum):
    """Bounded administration events suitable for later persistence."""

    LOGIN_SUCCEEDED = "login_succeeded"
    LOGIN_FAILED = "login_failed"
    LOGIN_RATE_LIMITED = "login_rate_limited"
    REQUEST_RATE_LIMITED = "request_rate_limited"
    SESSION_REJECTED = "session_rejected"
    ADMIN_VIEWED = "admin_viewed"
    LOGOUT_SUCCEEDED = "logout_succeeded"
    CSRF_REJECTED = "csrf_rejected"


class SecurityAuditEvent(ContractModel):
    """Secret-free append-only administration audit event."""

    event_id: UUID
    occurred_at: UtcDatetime
    event_type: AuditEventType
    actor: ShortText | None
    client_sha256: Sha256Hex
    detail: ShortText


def public_summary(prediction: PredictionRecord) -> PublicResearchSummary:
    """Project an immutable prediction into its intentionally public fields."""

    return PublicResearchSummary(
        prediction_id=prediction.prediction_id,
        research_subject_id=prediction.research_subject_id,
        published_at=prediction.published_at,
        evaluation_due_on=prediction.evaluation_due_on,
        horizon_days=prediction.horizon_days,
        label=prediction.label,
        risk_profile=prediction.risk_profile,
        scores=PublicScores(
            opportunity_points=prediction.scores.opportunity_points,
            risk_points=prediction.scores.risk_points,
            research_confidence_points=prediction.scores.research_confidence_points,
        ),
        evidence_count=len(prediction.evidence),
    )


def public_detail(prediction: PredictionRecord) -> PublicResearchDetail:
    """Project public evidence lineage while retaining the publication snapshot."""

    summary = public_summary(prediction)
    return PublicResearchDetail(
        **summary.model_dump(),
        thesis=prediction.thesis,
        signal_fingerprint=prediction.versions.signal_fingerprint,
        signal_ruleset_version=prediction.versions.signal_ruleset_version,
        evidence=tuple(
            PublicEvidenceReference(
                evidence_id=item.evidence_id,
                content_sha256=item.content_sha256,
                available_at=item.available_at,
                retrieved_at=item.retrieved_at,
            )
            for item in prediction.evidence
        ),
        calculation_versions=prediction.versions.calculation_versions,
        analysis_prompt_versions=prediction.versions.analysis_prompt_versions,
        analysis_model_versions=prediction.versions.analysis_model_versions,
    )


def public_index_item(
    publication: ResearchBrief | PredictionRecord,
) -> PublicDossierSummary | PublicForecastSummary:
    """Project a public table row with an explicit, non-interchangeable type."""

    if isinstance(publication, ResearchBrief):
        return PublicDossierSummary(
            brief_id=publication.brief_id,
            canonical_url=f"/radar/{publication.brief_id}",
            published_at=publication.published_at,
            company_name=publication.company_name,
            ticker=publication.ticker,
            filing_form=publication.filing_form,
            classification=publication.classification,
            attention_points=publication.attention_points,
            risk_points=publication.risk_points,
            evidence_strength_points=publication.evidence_strength_points,
            evidence_count=len(publication.evidence),
        )
    summary = public_summary(publication)
    return PublicForecastSummary(
        **summary.model_dump(),
        canonical_url=f"/research/{publication.prediction_id}",
    )
