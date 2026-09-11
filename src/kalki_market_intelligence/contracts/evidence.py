"""Initial provenance and evidence contracts."""

from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import HttpUrl, model_validator

from kalki_market_intelligence.contracts.common import (
    ContractModel,
    NonEmptyText,
    Sha256Hex,
    ShortText,
    UtcDatetime,
)


class SourceClass(StrEnum):
    """Source categories ordered conceptually from authoritative to discovery-only."""

    SEC = "sec"
    SEDAR_PLUS = "sedar_plus"
    COMPANY_IR = "company_ir"
    OFFICIAL_RELEASE = "official_release"
    GOVERNMENT_REGULATORY = "government_regulatory"
    REPUTABLE_NEWS = "reputable_news"
    DISCOVERY_ONLY = "discovery_only"


class SourceQuality(StrEnum):
    """Deterministic authority grade; this is not an analyst confidence score."""

    PRIMARY = "primary"
    SUPPORTING = "supporting"
    LOWER_CONFIDENCE = "lower_confidence"


def quality_for_source_class(source_class: SourceClass) -> SourceQuality:
    """Map the closed source taxonomy to an explicit authority grade."""

    if source_class in {
        SourceClass.SEC,
        SourceClass.SEDAR_PLUS,
        SourceClass.COMPANY_IR,
        SourceClass.OFFICIAL_RELEASE,
        SourceClass.GOVERNMENT_REGULATORY,
    }:
        return SourceQuality.PRIMARY
    if source_class is SourceClass.REPUTABLE_NEWS:
        return SourceQuality.SUPPORTING
    return SourceQuality.LOWER_CONFIDENCE


class EvidenceKind(StrEnum):
    """Whether a claim is reported, quoted, or explicitly inferred."""

    REPORTED_FACT = "reported_fact"
    DIRECT_QUOTE = "direct_quote"
    ANALYST_INFERENCE = "analyst_inference"


class SourceDocument(ContractModel):
    """A retrieved document with enough provenance for temporal auditing."""

    source_id: UUID
    source_class: SourceClass
    source_quality: SourceQuality = SourceQuality.LOWER_CONFIDENCE
    publisher: ShortText
    title: ShortText
    canonical_url: HttpUrl
    media_type: ShortText
    content_sha256: Sha256Hex
    published_at: UtcDatetime
    available_at: UtcDatetime
    retrieved_at: UtcDatetime

    @model_validator(mode="before")
    @classmethod
    def derive_quality_when_omitted(cls, value: object) -> object:
        """Keep existing callers safe while making quality explicit in the model."""

        if isinstance(value, dict) and "source_quality" not in value:
            source_class = value.get("source_class")
            if not isinstance(source_class, (str, SourceClass)):
                return value
            normalized = SourceClass(source_class)
            return {**value, "source_quality": quality_for_source_class(normalized)}
        return value

    @model_validator(mode="after")
    def timestamps_must_follow_information_flow(self) -> Self:
        """Prevent future knowledge from entering an earlier research snapshot."""

        if self.available_at < self.published_at:
            raise ValueError("available_at must be on or after published_at")
        if self.retrieved_at < self.available_at:
            raise ValueError("retrieved_at must be on or after available_at")
        if self.source_quality is not quality_for_source_class(self.source_class):
            raise ValueError("source_quality must match the source_class authority grade")
        return self


class EvidenceClaim(ContractModel):
    """A bounded claim linked to one retrieved source document."""

    claim_id: UUID
    source_id: UUID
    source_quality: SourceQuality = SourceQuality.LOWER_CONFIDENCE
    kind: EvidenceKind
    statement: NonEmptyText
    locator: ShortText
    recorded_at: UtcDatetime
    verbatim_text: NonEmptyText | None = None

    @model_validator(mode="before")
    @classmethod
    def derive_quality_from_source_claim(cls, value: object) -> object:
        """Evidence claims may be constructed before their source projection exists."""

        if isinstance(value, dict) and "source_quality" not in value:
            # Claims historically carried only source_id, so unknown quality is
            # represented conservatively until a source projection is available.
            return {**value, "source_quality": SourceQuality.LOWER_CONFIDENCE}
        return value

    @model_validator(mode="after")
    def direct_quote_requires_verbatim_text(self) -> Self:
        """Keep direct quotations distinguishable from summaries and inference."""

        if self.kind is EvidenceKind.DIRECT_QUOTE and self.verbatim_text is None:
            raise ValueError("direct_quote evidence requires verbatim_text")
        return self
