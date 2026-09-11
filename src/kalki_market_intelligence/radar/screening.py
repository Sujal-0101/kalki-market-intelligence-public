"""Closed terminal provenance for autonomous SEC filing screening."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from kalki_market_intelligence.contracts.common import (
    ContractModel,
    Sha256Hex,
    UtcDatetime,
)
from kalki_market_intelligence.radar.contracts import AccessionNumber

SCREENING_DECISION_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"


class ScreeningDisposition(StrEnum):
    """Mutually exclusive terminal result of one autonomous filing evaluation."""

    QUALIFIED = "QUALIFIED"
    SCREENED_OUT = "SCREENED_OUT"
    ANALYSIS_INCOMPLETE = "ANALYSIS_INCOMPLETE"


class ScreeningReason(StrEnum):
    """Bounded reasons that may be selected only by the executing runtime path."""

    VALIDATED_PUBLICATION = "VALIDATED_PUBLICATION"
    DETERMINISTIC_QUALIFICATION_NOT_MET = "DETERMINISTIC_QUALIFICATION_NOT_MET"
    NO_VALIDATED_FINDINGS = "NO_VALIDATED_FINDINGS"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    VERIFICATION_DISAGREEMENT = "VERIFICATION_DISAGREEMENT"
    ANALYST_TIMEOUT = "ANALYST_TIMEOUT"
    ANALYST_PROVIDER_FAILURE = "ANALYST_PROVIDER_FAILURE"
    ANALYST_CONTRACT_REJECTED = "ANALYST_CONTRACT_REJECTED"
    EVIDENCE_VALIDATION_REJECTED = "EVIDENCE_VALIDATION_REJECTED"
    NUMERIC_CONFLICT = "NUMERIC_CONFLICT"
    PROVENANCE_FAILURE = "PROVENANCE_FAILURE"
    VERIFIER_UNAVAILABLE = "VERIFIER_UNAVAILABLE"
    VERIFIER_FAILURE = "VERIFIER_FAILURE"
    SOURCE_RETRIEVAL_FAILURE = "SOURCE_RETRIEVAL_FAILURE"
    FILING_PARSE_FAILURE = "FILING_PARSE_FAILURE"
    COMPANYFACTS_NORMALIZATION_FAILURE = "COMPANYFACTS_NORMALIZATION_FAILURE"
    DETERMINISTIC_PROCESSING_FAILURE = "DETERMINISTIC_PROCESSING_FAILURE"
    PERSISTENCE_FAILURE = "PERSISTENCE_FAILURE"
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"
    OTHER_BOUNDED_FAILURE = "OTHER_BOUNDED_FAILURE"
    LEGACY_REASON_UNAVAILABLE = "LEGACY_REASON_UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


_QUALIFIED_REASONS = {ScreeningReason.VALIDATED_PUBLICATION}
_SCREENED_OUT_REASONS = {
    ScreeningReason.DETERMINISTIC_QUALIFICATION_NOT_MET,
    ScreeningReason.NO_VALIDATED_FINDINGS,
    ScreeningReason.INSUFFICIENT_EVIDENCE,
    ScreeningReason.VERIFICATION_DISAGREEMENT,
}
_INCOMPLETE_REASONS = (
    set(ScreeningReason)
    - _QUALIFIED_REASONS
    - _SCREENED_OUT_REASONS
    - {ScreeningReason.LEGACY_REASON_UNAVAILABLE, ScreeningReason.UNKNOWN}
)


class AutonomousScreeningDecision(ContractModel):
    """Append-only terminal decision with content-free analyst attempt lineage."""

    decision_id: UUID
    accession_number: AccessionNumber
    decided_at: UtcDatetime
    disposition: ScreeningDisposition
    reason: ScreeningReason
    work_attempt: int = Field(ge=1, le=6)
    run_id: UUID
    analyst_attempt_ids: tuple[UUID, ...] = Field(default=(), max_length=24)
    source_document_sha256: Sha256Hex | None = None
    schema_version: Literal["1.0.0"] = SCREENING_DECISION_SCHEMA_VERSION

    @model_validator(mode="after")
    def disposition_has_only_a_proven_reason(self) -> Self:
        allowed = {
            ScreeningDisposition.QUALIFIED: _QUALIFIED_REASONS,
            ScreeningDisposition.SCREENED_OUT: _SCREENED_OUT_REASONS,
            ScreeningDisposition.ANALYSIS_INCOMPLETE: _INCOMPLETE_REASONS,
        }[self.disposition]
        if self.reason not in allowed:
            raise ValueError("screening reason does not match its terminal disposition")
        if len(set(self.analyst_attempt_ids)) != len(self.analyst_attempt_ids):
            raise ValueError("screening analyst attempt IDs must be unique")
        if self.disposition is ScreeningDisposition.QUALIFIED:
            if not self.analyst_attempt_ids or self.source_document_sha256 is None:
                raise ValueError("qualified screening requires analyst and source lineage")
        if self.reason is ScreeningReason.NO_VALIDATED_FINDINGS and not self.analyst_attempt_ids:
            raise ValueError("no-findings screening requires completed analyst lineage")
        return self
