"""Bounded private orchestration for deterministic contradiction persistence."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, Self

from pydantic import Field, model_validator

from kalki_market_intelligence.contracts.common import ContractModel, UtcDatetime
from kalki_market_intelligence.forensics.contradictions import (
    ClaimUnderReview,
    ContradictionDisposition,
    ContradictionFact,
    ContradictionReceipt,
    check_deterministic_contradiction,
)


class ConvergenceInputStatus(StrEnum):
    VALIDATED = "VALIDATED"


class ConvergenceFactCompleteness(StrEnum):
    REQUIRED_FACTS_COMPLETE = "REQUIRED_FACTS_COMPLETE"
    PARTIAL_VALIDATED_FACTS = "PARTIAL_VALIDATED_FACTS"
    NOT_APPLICABLE_CONTEXT = "NOT_APPLICABLE_CONTEXT"


class ConvergenceValidationRequest(ContractModel):
    """Explicit eligibility wrapper around already-validated private inputs."""

    claim: ClaimUnderReview
    facts: tuple[ContradictionFact, ...] = Field(default=(), max_length=8)
    knowledge_cutoff_at: UtcDatetime
    claim_status: ConvergenceInputStatus = ConvergenceInputStatus.VALIDATED
    fact_status: ConvergenceInputStatus = ConvergenceInputStatus.VALIDATED
    fact_completeness: ConvergenceFactCompleteness

    @model_validator(mode="after")
    def eligibility_is_explicit(self) -> Self:
        if self.claim_status is not ConvergenceInputStatus.VALIDATED:
            raise ValueError("convergence claim must already be validated")
        if self.fact_status is not ConvergenceInputStatus.VALIDATED:
            raise ValueError("convergence facts must already be validated")
        return self


class ContradictionReceiptSink(Protocol):
    def append_receipt(self, receipt: ContradictionReceipt) -> ContradictionReceipt: ...


class ConvergenceValidationService:
    """Recompute one eligible request and append only a classification-consistent result."""

    def __init__(self, sink: ContradictionReceiptSink) -> None:
        self._sink = sink

    def evaluate_and_persist(
        self,
        request: ConvergenceValidationRequest,
    ) -> ContradictionReceipt:
        request = ConvergenceValidationRequest.model_validate(request.model_dump(mode="json"))
        receipt = check_deterministic_contradiction(
            request.claim,
            request.facts,
            knowledge_cutoff_at=request.knowledge_cutoff_at,
        )
        expected = {
            ConvergenceFactCompleteness.REQUIRED_FACTS_COMPLETE: {
                ContradictionDisposition.SUPPORTED,
                ContradictionDisposition.CONFLICTED,
            },
            ConvergenceFactCompleteness.PARTIAL_VALIDATED_FACTS: {
                ContradictionDisposition.INSUFFICIENT,
            },
            ConvergenceFactCompleteness.NOT_APPLICABLE_CONTEXT: {
                ContradictionDisposition.NOT_APPLICABLE,
            },
        }[request.fact_completeness]
        if receipt.disposition not in expected:
            raise ValueError(
                "convergence completeness classification disagrees with deterministic result"
            )
        return self._sink.append_receipt(receipt)
