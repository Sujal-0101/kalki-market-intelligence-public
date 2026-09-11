"""Closed contracts for untrusted evidence and qualitative model output."""

from __future__ import annotations

import json
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
from kalki_market_intelligence.contracts.evidence import (
    SourceClass,
    SourceQuality,
    quality_for_source_class,
)

PROMPT_VERSION: Literal["analyst-v2"] = "analyst-v2"
VALIDATION_VERSION: Literal["1.0.0"] = "1.0.0"

type EvidenceQuote = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000),
]
type ModelText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100_000),
]


class AnalystRole(StrEnum):
    DOCUMENT_INTERPRETER = "document_interpreter"
    CATALYST_ANALYST = "catalyst_analyst"
    PARTNERSHIP_ANALYST = "partnership_analyst"
    MANAGEMENT_COMMENTARY_ANALYST = "management_commentary_analyst"
    CONTRADICTION_ANALYST = "contradiction_analyst"
    BULL_BEAR_RISK_ANALYST = "bull_bear_risk_analyst"


class FindingKind(StrEnum):
    REPORTED_FACT = "reported_fact"
    ANALYST_INFERENCE = "analyst_inference"


class FindingCategory(StrEnum):
    DOCUMENT_FACT = "document_fact"
    CATALYST = "catalyst"
    PARTNERSHIP = "partnership"
    MANAGEMENT_COMMENTARY = "management_commentary"
    BULL_CASE = "bull_case"
    BEAR_CASE = "bear_case"
    RISK = "risk"


class FindingPolarity(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    MIXED = "mixed"


class Assessment(StrEnum):
    EVIDENCE_SUFFICIENT = "evidence_sufficient"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"


class ContradictionStatus(StrEnum):
    CONFIRMED = "confirmed"
    UNRESOLVED = "unresolved"
    RESOLVED_BY_LATER_CORRECTION = "resolved_by_later_correction"
    DIFFERENT_SCOPE = "different_scope"


class AnalystEvidence(ContractModel):
    """One retrieved excerpt passed to a model strictly as untrusted data."""

    evidence_id: UUID
    subject_id: UUID
    source_id: UUID
    source_class: SourceClass
    source_quality: SourceQuality = SourceQuality.LOWER_CONFIDENCE
    publisher: ShortText
    locator: ShortText
    text: NonEmptyText
    content_sha256: Sha256Hex
    published_at: UtcDatetime
    available_at: UtcDatetime
    retrieved_at: UtcDatetime

    @model_validator(mode="before")
    @classmethod
    def derive_quality_when_omitted(cls, value: object) -> object:
        if isinstance(value, dict) and "source_quality" not in value:
            source_class = value.get("source_class")
            if not isinstance(source_class, (str, SourceClass)):
                return value
            normalized = SourceClass(source_class)
            return {**value, "source_quality": quality_for_source_class(normalized)}
        return value

    @model_validator(mode="after")
    def timestamps_follow_information_flow(self) -> Self:
        if self.available_at < self.published_at:
            raise ValueError("evidence available_at must not precede published_at")
        if self.retrieved_at < self.available_at:
            raise ValueError("evidence retrieved_at must not precede available_at")
        if self.source_quality is not quality_for_source_class(self.source_class):
            raise ValueError("source_quality must match the source_class authority grade")
        return self


class EvidenceCitation(ContractModel):
    evidence_id: UUID
    quote: EvidenceQuote


class AnalystFinding(ContractModel):
    kind: FindingKind
    category: FindingCategory
    polarity: FindingPolarity
    statement: EvidenceQuote
    citations: tuple[EvidenceCitation, ...] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def citations_are_unique(self) -> Self:
        ids = tuple(item.evidence_id for item in self.citations)
        if len(set(ids)) != len(ids):
            raise ValueError("finding citations must use unique evidence IDs")
        return self


class AnalystContradiction(ContractModel):
    topic: ShortText
    status: ContradictionStatus
    citations: tuple[EvidenceCitation, ...] = Field(min_length=2, max_length=4)

    @model_validator(mode="after")
    def compares_distinct_evidence(self) -> Self:
        ids = tuple(item.evidence_id for item in self.citations)
        if len(set(ids)) < 2:
            raise ValueError("contradiction must compare at least two evidence records")
        return self


class AnalystReport(ContractModel):
    """Model-produced payload; still untrusted until pipeline validation passes."""

    prompt_version: Literal["analyst-v2"]
    role: AnalystRole
    assessment: Assessment
    findings: tuple[AnalystFinding, ...] = Field(max_length=12)
    contradictions: tuple[AnalystContradiction, ...] = Field(max_length=6)
    limitations: tuple[ShortText, ...] = Field(max_length=8)

    @model_validator(mode="after")
    def assessment_matches_report_shape(self) -> Self:
        if self.assessment is Assessment.INSUFFICIENT_EVIDENCE and self.findings:
            raise ValueError("insufficient evidence reports must not contain findings")
        if self.assessment is Assessment.CONFLICTING_EVIDENCE and not self.contradictions:
            raise ValueError("conflicting evidence reports require a contradiction")
        if self.contradictions and self.assessment is not Assessment.CONFLICTING_EVIDENCE:
            raise ValueError("reports with contradictions must use conflicting evidence assessment")
        if self.assessment is Assessment.EVIDENCE_SUFFICIENT and not self.findings:
            raise ValueError("sufficient evidence reports require at least one finding")
        return self


class ModelRequest(ContractModel):
    system_prompt: ModelText
    user_prompt: ModelText
    output_schema: dict[str, object]
    temperature: float = Field(default=0, ge=0, le=1)
    seed: int = 42
    context_tokens: int = Field(default=4_096, ge=1_024, le=32_768)
    maximum_output_tokens: int = Field(default=768, ge=128, le=4_096)


class ModelResponse(ContractModel):
    provider_name: ShortText
    model_name: ShortText
    model_digest: Sha256Hex | None
    content: ModelText
    prompt_tokens: int | None = Field(default=None, ge=0, le=1_000_000)
    generated_tokens: int | None = Field(default=None, ge=0, le=1_000_000)


class AnalystReconsideration(ContractModel):
    """Bounded, neutral context for the single semantic reconsideration."""

    original_candidate_json: NonEmptyText
    challenge_categories: tuple[ShortText, ...] = Field(min_length=1, max_length=8)
    relevant_evidence_ids: tuple[UUID, ...] = Field(min_length=1, max_length=8)
    relevant_claim_ids: tuple[ShortText, ...] = Field(max_length=12)

    @model_validator(mode="after")
    def references_are_unique_and_payload_is_json(self) -> Self:
        try:
            payload = json.loads(self.original_candidate_json)
        except json.JSONDecodeError as error:
            raise ValueError("reconsideration candidate must be valid JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("reconsideration candidate must be a JSON object")
        if len(set(self.challenge_categories)) != len(self.challenge_categories):
            raise ValueError("reconsideration challenge categories must be unique")
        if len(set(self.relevant_evidence_ids)) != len(self.relevant_evidence_ids):
            raise ValueError("reconsideration evidence IDs must be unique")
        if len(set(self.relevant_claim_ids)) != len(self.relevant_claim_ids):
            raise ValueError("reconsideration claim IDs must be unique")
        return self


class AnalysisAudit(ContractModel):
    provider_name: ShortText
    model_name: ShortText
    model_digest: Sha256Hex | None
    prompt_version: Literal["analyst-v2"]
    validation_version: Literal["1.0.0"]
    knowledge_cutoff_at: UtcDatetime
    completed_at: UtcDatetime
    attempts: int = Field(ge=1, le=2)
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)
    evidence_hashes: tuple[Sha256Hex, ...] = Field(min_length=1)
    normalizations: tuple[ShortText, ...] = ()

    @model_validator(mode="after")
    def temporal_and_evidence_keys_are_consistent(self) -> Self:
        if self.completed_at < self.knowledge_cutoff_at:
            raise ValueError("analysis completion must not precede the knowledge cutoff")
        if len(self.evidence_ids) != len(self.evidence_hashes):
            raise ValueError("analysis evidence IDs and hashes must have equal length")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("analysis audit evidence IDs must be unique")
        if len(set(self.normalizations)) != len(self.normalizations):
            raise ValueError("analysis audit normalizations must be unique")
        return self


class ValidatedAnalysis(ContractModel):
    """Only this post-validation wrapper may cross into downstream components."""

    report: AnalystReport
    audit: AnalysisAudit


def analyst_generation_schema() -> dict[str, object]:
    """Keep the schema grammar bounded for Ollama while post-validating full limits."""

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

    return cast(dict[str, object], simplify(AnalystReport.model_json_schema()))
