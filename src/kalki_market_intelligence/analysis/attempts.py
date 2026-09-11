"""Bounded, content-free receipts for every local analyst model attempt."""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum
from typing import Literal, Protocol, Self
from uuid import UUID

from pydantic import Field, model_validator

from kalki_market_intelligence.analysis.contracts import (
    PROMPT_VERSION,
    VALIDATION_VERSION,
    AnalystRole,
)
from kalki_market_intelligence.contracts.common import (
    ContractModel,
    Sha256Hex,
    ShortText,
    UtcDatetime,
)

ANALYST_ATTEMPT_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
ANALYST_OUTPUT_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
POSTGRES_BIGINT_MAX = 9_223_372_036_854_775_807


class AnalystAttemptOrigin(StrEnum):
    CANDIDATE = "candidate"
    HUMAN = "human"


class AnalystFailureLayer(StrEnum):
    NONE = "none"
    FORMAT = "format"
    CONTENT_EVIDENCE = "content_evidence"
    RUNTIME = "runtime"


class AnalystFailureCategory(StrEnum):
    MALFORMED_JSON = "malformed_json"
    EXTRA_PROSE = "extra_prose"
    MISSING_REQUIRED_FIELD = "missing_required_field"
    INVALID_TYPE = "invalid_type"
    INVALID_ENUM = "invalid_enum"
    INVALID_EVIDENCE_ID = "invalid_evidence_id"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    NUMERIC_CONFLICT = "numeric_conflict"
    PROVENANCE_FAILURE = "provenance_failure"
    TIMEOUT = "timeout"
    REFUSAL = "refusal"
    PROVIDER_ERROR = "provider_error"
    OTHER = "other"


class AttemptCheckStatus(StrEnum):
    NOT_CHECKED = "not_checked"
    PASSED = "passed"
    FAILED = "failed"


class AnalystAttemptOutcome(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    RUNTIME_ERROR = "runtime_error"


class AnalystRetryScope(StrEnum):
    NONE = "none"
    PIPELINE = "pipeline"
    WORK_ITEM = "work_item"


class AnalystTerminalDisposition(StrEnum):
    ACCEPTED = "accepted"
    RETRY_PENDING = "retry_pending"
    REJECTED = "rejected"
    PROVIDER_ERROR = "provider_error"
    REFUSAL = "refusal"


class AnalystWorkContext(ContractModel):
    """Business identity supplied by the autonomous or private-human worker path."""

    origin: AnalystAttemptOrigin
    candidate_accession_number: str | None = Field(default=None, pattern=r"^\d{10}-\d{2}-\d{6}$")
    lead_id: UUID | None = None
    ticker: str | None = Field(default=None, pattern=r"^[A-Z0-9][A-Z0-9.\-]{0,14}$")
    cik: str = Field(pattern=r"^\d{1,10}$")
    accession_number: str = Field(pattern=r"^\d{10}-\d{2}-\d{6}$")
    filing_form: ShortText
    work_attempt: int = Field(ge=1, le=6)
    semantic_retry: bool = False
    runtime_retry_eligible: bool = False

    @model_validator(mode="after")
    def identity_matches_origin(self) -> Self:
        if self.origin is AnalystAttemptOrigin.CANDIDATE:
            if self.lead_id is not None:
                raise ValueError("candidate analyst context cannot carry a human lead")
            if self.candidate_accession_number != self.accession_number:
                raise ValueError("candidate analyst context must reference its accession")
        elif self.lead_id is None or self.candidate_accession_number is not None:
            raise ValueError("human analyst context requires only a human lead identity")
        return self


class AnalystAttemptStart(ContractModel):
    """Durable pre-provider record; it deliberately excludes prompt content."""

    attempt_id: UUID
    invocation_id: UUID
    context: AnalystWorkContext
    provider_name: ShortText
    model_name: ShortText
    model_digest: Sha256Hex
    prompt_version: Literal["analyst-v2"] = PROMPT_VERSION
    output_schema_version: Literal["1.0.0"] = ANALYST_OUTPUT_SCHEMA_VERSION
    validation_version: Literal["1.0.0"] = VALIDATION_VERSION
    role: AnalystRole
    attempt_number: int = Field(ge=1, le=2)
    started_at: UtcDatetime
    input_evidence_count: int = Field(ge=1, le=8)
    input_evidence_characters: int = Field(ge=1, le=32_000)
    system_prompt_characters: int = Field(ge=1, le=100_000)
    user_prompt_characters: int = Field(ge=1, le=100_000)
    context_tokens: int = Field(ge=1_024, le=32_768)
    maximum_output_tokens: int = Field(ge=128, le=4_096)
    schema_version: Literal["1.0.0"] = ANALYST_ATTEMPT_SCHEMA_VERSION


class AnalystAttemptReceipt(ContractModel):
    """Completed attempt metadata with hashes and sizes, never response content."""

    start: AnalystAttemptStart
    completed_at: UtcDatetime
    latency_ms: int = Field(ge=0, le=POSTGRES_BIGINT_MAX)
    response_sha256: Sha256Hex | None = None
    response_characters: int | None = Field(default=None, ge=0, le=2_000_000)
    response_bytes: int | None = Field(default=None, ge=0, le=10_000_000)
    prompt_tokens: int | None = Field(default=None, ge=0, le=1_000_000)
    generated_tokens: int | None = Field(default=None, ge=0, le=1_000_000)
    parse_status: AttemptCheckStatus
    schema_status: AttemptCheckStatus
    evidence_status: AttemptCheckStatus
    failure_layer: AnalystFailureLayer
    failure_category: AnalystFailureCategory | None = None
    failure_path: ShortText | None = None
    retry_eligible: bool
    retry_scope: AnalystRetryScope
    outcome: AnalystAttemptOutcome
    terminal_disposition: AnalystTerminalDisposition

    @model_validator(mode="after")
    def completion_is_consistent(self) -> Self:
        if self.completed_at < self.start.started_at:
            raise ValueError("analyst attempt completion cannot precede its start")
        has_response = self.response_sha256 is not None
        if has_response != (
            self.response_characters is not None and self.response_bytes is not None
        ):
            raise ValueError("response hash and bounded sizes must be present together")
        if self.retry_eligible != (self.retry_scope is not AnalystRetryScope.NONE):
            raise ValueError("retry eligibility must match a declared retry scope")
        if self.retry_eligible != (
            self.terminal_disposition is AnalystTerminalDisposition.RETRY_PENDING
        ):
            raise ValueError("retry eligibility must match the terminal disposition")
        if self.outcome is AnalystAttemptOutcome.ACCEPTED:
            if (
                not has_response
                or self.parse_status is not AttemptCheckStatus.PASSED
                or self.schema_status is not AttemptCheckStatus.PASSED
                or self.evidence_status is not AttemptCheckStatus.PASSED
                or self.failure_layer is not AnalystFailureLayer.NONE
                or self.failure_category is not None
                or self.failure_path is not None
                or self.terminal_disposition is not AnalystTerminalDisposition.ACCEPTED
            ):
                raise ValueError("accepted analyst attempts require all deterministic gates")
        elif self.outcome is AnalystAttemptOutcome.RUNTIME_ERROR:
            if (
                self.failure_layer is not AnalystFailureLayer.RUNTIME
                or self.failure_category is None
                or self.parse_status is not AttemptCheckStatus.NOT_CHECKED
                or self.schema_status is not AttemptCheckStatus.NOT_CHECKED
                or self.evidence_status is not AttemptCheckStatus.NOT_CHECKED
            ):
                raise ValueError("runtime analyst failures cannot claim validation checks")
        elif (
            self.failure_layer
            not in {
                AnalystFailureLayer.FORMAT,
                AnalystFailureLayer.CONTENT_EVIDENCE,
            }
            or self.failure_category is None
        ):
            raise ValueError("rejected analyst attempts require a bounded failure")
        return self


def interrupted_analyst_attempt_receipt(
    start: AnalystAttemptStart,
    *,
    recovered_at: UtcDatetime,
    retry_eligible: bool,
) -> AnalystAttemptReceipt:
    """Close a lease-expired invocation without claiming model output or checks."""

    elapsed = recovered_at - start.started_at
    latency_ms = elapsed // timedelta(milliseconds=1)
    return AnalystAttemptReceipt(
        start=start,
        completed_at=recovered_at,
        latency_ms=latency_ms,
        parse_status=AttemptCheckStatus.NOT_CHECKED,
        schema_status=AttemptCheckStatus.NOT_CHECKED,
        evidence_status=AttemptCheckStatus.NOT_CHECKED,
        failure_layer=AnalystFailureLayer.RUNTIME,
        failure_category=AnalystFailureCategory.PROVIDER_ERROR,
        failure_path="worker.processing_lease_expired",
        retry_eligible=retry_eligible,
        retry_scope=(AnalystRetryScope.WORK_ITEM if retry_eligible else AnalystRetryScope.NONE),
        outcome=AnalystAttemptOutcome.RUNTIME_ERROR,
        terminal_disposition=(
            AnalystTerminalDisposition.RETRY_PENDING
            if retry_eligible
            else AnalystTerminalDisposition.PROVIDER_ERROR
        ),
    )


class AnalystAttemptSink(Protocol):
    """Persistence boundary whose failure prevents model output from being used."""

    def start_analyst_attempt(self, attempt: AnalystAttemptStart) -> None: ...

    def finish_analyst_attempt(self, receipt: AnalystAttemptReceipt) -> None: ...
