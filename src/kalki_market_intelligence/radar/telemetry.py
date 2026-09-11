"""Content-free, bounded lifecycle telemetry for private operations."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from kalki_market_intelligence.contracts.common import ContractModel, UtcDatetime
from kalki_market_intelligence.forensics.detectors import ForensicStatus


class PipelineStage(StrEnum):
    SEC_POLL_ATTEMPTED = "sec_poll_attempted"
    CANDIDATE_PROCESSING = "candidate_processing"
    CANDIDATE_RETRIEVED = "candidate_retrieved"
    CANDIDATE_PARSED = "candidate_parsed"
    COMPANYFACTS_NORMALIZED = "companyfacts_normalized"
    CANDIDATE_RETRY_WAIT = "candidate_retry_wait"
    CANDIDATE_SKIPPED = "candidate_skipped"
    CANDIDATE_FAILED = "candidate_failed"
    TIER_RETAINED = "tier_retained"
    TIER_ESCALATED = "tier_escalated"
    STALE_RECOVERED = "stale_recovered"
    HUMAN_DUPLICATE = "human_duplicate"


type PipelineFailureCategory = Literal[
    "sec_retrieval",
    "filing_parse",
    "companyfacts_normalization",
    "deterministic_processing",
    "analyst",
    "verifier",
    "persistence",
    "other",
]

type DetectorName = Literal[
    "share_growth",
    "liquidity",
    "going_concern",
    "reverse_split",
    "filing_diff",
    "xbrl_numeric",
    "source_authority",
    "convergence",
]


class PipelineEvent(ContractModel):
    """Aggregate-safe stage event; no source, model, or human content is retained."""

    event_id: UUID
    occurred_at: UtcDatetime
    stage: PipelineStage
    run_id: UUID | None = None
    accession_number: str | None = Field(default=None, pattern=r"^\d{10}-\d{2}-\d{6}$")
    count: int = Field(default=1, ge=1, le=10_000)
    failure_category: PipelineFailureCategory | None = None
    schema_version: Literal["1.0.0"] = "1.0.0"

    @model_validator(mode="after")
    def context_matches_stage(self) -> PipelineEvent:
        candidate_stage = self.stage in {
            PipelineStage.CANDIDATE_PROCESSING,
            PipelineStage.CANDIDATE_RETRIEVED,
            PipelineStage.CANDIDATE_PARSED,
            PipelineStage.COMPANYFACTS_NORMALIZED,
            PipelineStage.CANDIDATE_RETRY_WAIT,
            PipelineStage.CANDIDATE_SKIPPED,
            PipelineStage.CANDIDATE_FAILED,
            PipelineStage.TIER_RETAINED,
            PipelineStage.TIER_ESCALATED,
        }
        if candidate_stage != (self.accession_number is not None):
            raise ValueError("candidate stage telemetry requires only an accession identity")
        failure_stage = self.stage in {
            PipelineStage.CANDIDATE_RETRY_WAIT,
            PipelineStage.CANDIDATE_FAILED,
        }
        if failure_stage != (self.failure_category is not None):
            raise ValueError("retry and failure telemetry require a bounded category")
        if self.stage is PipelineStage.SEC_POLL_ATTEMPTED and self.run_id is None:
            raise ValueError("SEC poll telemetry requires its run identity")
        return self


class DetectorReceipt(ContractModel):
    """One deterministic detector observation without filing or hypothesis content."""

    receipt_id: UUID
    accession_number: str = Field(pattern=r"^\d{10}-\d{2}-\d{6}$")
    observed_at: UtcDatetime
    detector_name: DetectorName
    invoked: bool
    status: ForensicStatus
    contributed_to_escalation: bool
    schema_version: Literal["1.0.0"] = "1.0.0"

    @model_validator(mode="after")
    def invocation_matches_status(self) -> DetectorReceipt:
        if not self.invoked and self.status is not ForensicStatus.NOT_ASSESSED:
            raise ValueError("a detector that was not invoked must remain not assessed")
        if self.contributed_to_escalation and (
            not self.invoked or self.status is not ForensicStatus.POSITIVE
        ):
            raise ValueError("only an invoked positive detector may contribute to escalation")
        return self
