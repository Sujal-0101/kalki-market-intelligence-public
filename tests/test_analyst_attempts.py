"""Durable analyst-attempt metadata stays bounded and fail-closed."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from kalki_market_intelligence.analysis.attempts import (
    AnalystAttemptOrigin,
    AnalystAttemptReceipt,
    AnalystAttemptStart,
    AnalystFailureCategory,
    AnalystFailureLayer,
    AnalystRetryScope,
    AnalystTerminalDisposition,
    AnalystWorkContext,
    AttemptCheckStatus,
    interrupted_analyst_attempt_receipt,
)
from kalki_market_intelligence.analysis.contracts import (
    AnalystEvidence,
    AnalystReport,
    ModelRequest,
    ModelResponse,
)
from kalki_market_intelligence.analysis.ollama import ModelProviderError
from kalki_market_intelligence.analysis.pipeline import AnalysisRejected, AnalystPipeline
from kalki_market_intelligence.analysis.provider import ModelProvider, SequenceModelProvider

FIXTURE = Path(__file__).parents[1] / "data/fixtures/analysis/representative-cases.json"
NOW = datetime(2026, 8, 27, 12, tzinfo=UTC)
DIGEST = "a" * 64


class MemoryAttemptSink:
    def __init__(self) -> None:
        self.starts: list[AnalystAttemptStart] = []
        self.receipts: list[AnalystAttemptReceipt] = []

    def start_analyst_attempt(self, attempt: AnalystAttemptStart) -> None:
        self.starts.append(attempt)

    def finish_analyst_attempt(self, receipt: AnalystAttemptReceipt) -> None:
        self.receipts.append(receipt)


class TimeoutProvider:
    def generate(self, request: ModelRequest) -> ModelResponse:
        raise ModelProviderError("local Ollama request failed: TimeoutError") from TimeoutError()


def fixture_case() -> tuple[dict[str, object], tuple[AnalystEvidence, ...], AnalystReport]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    selected = payload["cases"][0]
    evidence = tuple(AnalystEvidence.model_validate(item) for item in selected["evidence"])
    report = AnalystReport.model_validate(selected["valid_report"])
    return selected, evidence, report


def work_context(*, runtime_retry_eligible: bool = True) -> AnalystWorkContext:
    return AnalystWorkContext(
        origin=AnalystAttemptOrigin.CANDIDATE,
        candidate_accession_number="0000320193-26-000001",
        ticker="TEST",
        cik="320193",
        accession_number="0000320193-26-000001",
        filing_form="8-K",
        work_attempt=1,
        runtime_retry_eligible=runtime_retry_eligible,
    )


def durable_pipeline(
    provider: ModelProvider,
    sink: MemoryAttemptSink,
    *,
    maximum_attempts: int = 2,
) -> AnalystPipeline:
    return AnalystPipeline(
        provider,
        maximum_attempts=maximum_attempts,
        attempt_sink=sink,
        configured_provider_name="ollama-loopback",
        configured_model_name="qwen3:4b",
        configured_model_digest=DIGEST,
        now=lambda: NOW,
    )


def test_each_repair_attempt_is_started_then_completed_without_content() -> None:
    selected, evidence, report = fixture_case()
    sink = MemoryAttemptSink()
    provider = SequenceModelProvider(("not-json", report.model_dump_json()))

    result = durable_pipeline(provider, sink).analyze(
        role=report.role,
        evidence=evidence,
        knowledge_cutoff_at=datetime.fromisoformat(str(selected["knowledge_cutoff_at"])),
        work_context=work_context(),
    )

    assert result.audit.attempts == 2
    assert len(sink.starts) == len(sink.receipts) == 2
    assert {item.invocation_id for item in sink.starts} == {sink.starts[0].invocation_id}
    first, second = sink.receipts
    assert first.failure_layer is AnalystFailureLayer.FORMAT
    assert first.failure_category is AnalystFailureCategory.MALFORMED_JSON
    assert first.parse_status is AttemptCheckStatus.FAILED
    assert first.retry_scope is AnalystRetryScope.PIPELINE
    assert first.terminal_disposition is AnalystTerminalDisposition.RETRY_PENDING
    assert second.failure_layer is AnalystFailureLayer.NONE
    assert second.terminal_disposition is AnalystTerminalDisposition.ACCEPTED
    serialized = " ".join(item.model_dump_json() for item in sink.receipts)
    assert "not-json" not in serialized
    assert evidence[0].text not in serialized
    assert provider.requests[0].user_prompt not in serialized


def test_surrounding_prose_is_classified_but_never_repaired_or_accepted() -> None:
    selected, evidence, report = fixture_case()
    sink = MemoryAttemptSink()
    response = f"Here is the requested JSON: {report.model_dump_json()}"

    with pytest.raises(AnalysisRejected) as captured:
        durable_pipeline(SequenceModelProvider((response,)), sink, maximum_attempts=1).analyze(
            role=report.role,
            evidence=evidence,
            knowledge_cutoff_at=datetime.fromisoformat(str(selected["knowledge_cutoff_at"])),
            work_context=work_context(),
        )

    assert captured.value.error_codes == ("extra_prose",)
    assert sink.receipts[0].failure_category is AnalystFailureCategory.EXTRA_PROSE
    assert sink.receipts[0].response_sha256 is not None
    assert response not in sink.receipts[0].model_dump_json()


def test_provider_timeout_is_durable_and_work_item_retryable() -> None:
    selected, evidence, report = fixture_case()
    sink = MemoryAttemptSink()

    with pytest.raises(ModelProviderError):
        durable_pipeline(TimeoutProvider(), sink).analyze(
            role=report.role,
            evidence=evidence,
            knowledge_cutoff_at=datetime.fromisoformat(str(selected["knowledge_cutoff_at"])),
            work_context=work_context(runtime_retry_eligible=True),
        )

    assert len(sink.starts) == len(sink.receipts) == 1
    receipt = sink.receipts[0]
    assert receipt.failure_category is AnalystFailureCategory.TIMEOUT
    assert receipt.failure_layer is AnalystFailureLayer.RUNTIME
    assert receipt.parse_status is AttemptCheckStatus.NOT_CHECKED
    assert receipt.retry_scope is AnalystRetryScope.WORK_ITEM
    assert receipt.terminal_disposition is AnalystTerminalDisposition.RETRY_PENDING
    assert receipt.response_sha256 is None


def test_durable_pipeline_refuses_an_unidentified_work_item() -> None:
    selected, evidence, report = fixture_case()
    sink = MemoryAttemptSink()
    pipeline = durable_pipeline(SequenceModelProvider((report.model_dump_json(),)), sink)

    with pytest.raises(ValueError, match="work context"):
        pipeline.analyze(
            role=report.role,
            evidence=evidence,
            knowledge_cutoff_at=datetime.fromisoformat(str(selected["knowledge_cutoff_at"])),
        )

    assert sink.starts == []


def test_human_and_candidate_contexts_cannot_be_conflated() -> None:
    with pytest.raises(ValueError, match="human lead"):
        AnalystWorkContext(
            origin=AnalystAttemptOrigin.CANDIDATE,
            candidate_accession_number="0000320193-26-000001",
            lead_id=UUID("10000000-0000-4000-8000-000000000001"),
            cik="320193",
            accession_number="0000320193-26-000001",
            filing_form="8-K",
            work_attempt=1,
        )


def test_interrupted_attempt_recovery_records_only_observed_runtime_failure() -> None:
    selected, evidence, report = fixture_case()
    sink = MemoryAttemptSink()

    with pytest.raises(ModelProviderError):
        durable_pipeline(TimeoutProvider(), sink).analyze(
            role=report.role,
            evidence=evidence,
            knowledge_cutoff_at=datetime.fromisoformat(str(selected["knowledge_cutoff_at"])),
            work_context=work_context(runtime_retry_eligible=True),
        )

    recovered_at = NOW + timedelta(days=5)
    receipt = interrupted_analyst_attempt_receipt(
        sink.starts[0], recovered_at=recovered_at, retry_eligible=False
    )

    assert receipt.completed_at == recovered_at
    assert receipt.latency_ms == 5 * 24 * 60 * 60 * 1_000
    assert receipt.response_sha256 is None
    assert receipt.parse_status is AttemptCheckStatus.NOT_CHECKED
    assert receipt.schema_status is AttemptCheckStatus.NOT_CHECKED
    assert receipt.evidence_status is AttemptCheckStatus.NOT_CHECKED
    assert receipt.failure_layer is AnalystFailureLayer.RUNTIME
    assert receipt.failure_category is AnalystFailureCategory.PROVIDER_ERROR
    assert receipt.failure_path == "worker.processing_lease_expired"
    assert receipt.retry_eligible is False
    assert receipt.retry_scope is AnalystRetryScope.NONE
    assert receipt.terminal_disposition is AnalystTerminalDisposition.PROVIDER_ERROR
