"""Security, grounding, retry, and provider tests for structured analysis."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from urllib.request import Request

import pytest
from pydantic import Field, ValidationError

import kalki_market_intelligence.analysis.ollama as ollama_module
from kalki_market_intelligence.analysis.contracts import (
    PROMPT_VERSION,
    AnalysisAudit,
    AnalystEvidence,
    AnalystReport,
    AnalystRole,
    Assessment,
    ContradictionStatus,
    ModelRequest,
    ValidatedAnalysis,
)
from kalki_market_intelligence.analysis.evaluation import load_fixture, run_evaluation
from kalki_market_intelligence.analysis.ollama import OllamaModelProvider
from kalki_market_intelligence.analysis.pipeline import (
    AnalysisRejected,
    AnalystPipeline,
    UnsafeEvidenceError,
    detect_prompt_injection,
    normalize_raw_report,
    normalize_report,
    validate_report,
)
from kalki_market_intelligence.analysis.prompts import SYSTEM_PROMPT_V2, build_user_prompt
from kalki_market_intelligence.analysis.provider import SequenceModelProvider
from kalki_market_intelligence.contracts.common import ContractModel, UtcDatetime

FIXTURE_PATH = Path(__file__).parents[1] / "data/fixtures/analysis/representative-cases.json"


class AnalysisCase(ContractModel):
    name: str
    role: AnalystRole
    knowledge_cutoff_at: UtcDatetime
    evidence: tuple[AnalystEvidence, ...]
    valid_report: AnalystReport | None = None
    quarantine: bool = False
    expected_terms: tuple[str, ...] = ()
    expected_contradiction_statuses: tuple[ContradictionStatus, ...] = ()


class AnalysisCases(ContractModel):
    schema_version: str
    description: str
    cases: tuple[AnalysisCase, ...] = Field(min_length=1)


CASES = AnalysisCases.model_validate_json(FIXTURE_PATH.read_text(encoding="utf-8"))


def case(name: str) -> AnalysisCase:
    return next(item for item in CASES.cases if item.name == name)


def report_json(item: AnalysisCase) -> str:
    assert item.valid_report is not None
    return item.valid_report.model_dump_json()


def run_fixture(item: AnalysisCase, *responses: str) -> ValidatedAnalysis:
    return AnalystPipeline(SequenceModelProvider(responses)).analyze(
        role=item.role,
        evidence=item.evidence,
        knowledge_cutoff_at=item.knowledge_cutoff_at,
    )


def mutate_report(item: AnalysisCase, mutation: Callable[[dict[str, Any]], None]) -> str:
    assert item.valid_report is not None
    payload = item.valid_report.model_dump(mode="json")
    mutation(payload)
    return json.dumps(payload)


def test_representative_fixtures_are_synthetic_valid_and_content_addressed() -> None:
    assert CASES.schema_version == "1"
    assert "not market evidence" in CASES.description
    for item in CASES.cases:
        for evidence in item.evidence:
            assert hashlib.sha256(evidence.text.encode()).hexdigest() == evidence.content_sha256
        assert item.quarantine != (item.valid_report is not None)


@pytest.mark.parametrize(
    "name", ["contract_catalyst", "non_binding_partnership", "corrected_revenue"]
)
def test_valid_fixture_reports_cross_the_trust_boundary(name: str) -> None:
    item = case(name)
    result = run_fixture(item, report_json(item))

    assert result.report == item.valid_report
    assert result.audit.prompt_version == PROMPT_VERSION
    assert result.audit.validation_version == "1.0.0"
    assert result.audit.attempts == 1
    assert result.audit.evidence_ids == tuple(record.evidence_id for record in item.evidence)


def test_invalid_json_is_repaired_once_with_bounded_error_feedback() -> None:
    item = case("contract_catalyst")
    provider = SequenceModelProvider(("not-json", report_json(item)))

    result = AnalystPipeline(provider).analyze(
        role=item.role,
        evidence=item.evidence,
        knowledge_cutoff_at=item.knowledge_cutoff_at,
    )

    assert result.audit.attempts == 2
    assert len(provider.requests) == 2
    assert "malformed_json" in provider.requests[1].user_prompt
    assert "not-json" not in provider.requests[1].user_prompt


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        (
            lambda payload: cast(list[dict[str, Any]], payload["findings"])[0].update(
                statement="A fabricated CAD 99.0 million figure."
            ),
            "unsupported_numeric_token",
        ),
        (
            lambda payload: cast(
                list[dict[str, Any]],
                cast(list[dict[str, Any]], payload["findings"])[0]["citations"],
            )[0].update(quote="fabricated quotation"),
            "quote_not_verbatim",
        ),
        (
            lambda payload: cast(list[dict[str, Any]], payload["findings"])[0].update(
                statement="Northstar announced a contract."
            ),
            "reported_fact_not_verbatim",
        ),
        (
            lambda payload: cast(
                list[dict[str, Any]],
                cast(list[dict[str, Any]], payload["findings"])[0]["citations"],
            )[0].update(evidence_id="99999999-9999-4999-8999-999999999999"),
            "unknown_evidence_id",
        ),
        (
            lambda payload: payload.update(role="partnership_analyst"),
            "role_mismatch",
        ),
        (
            lambda payload: cast(list[dict[str, Any]], payload["findings"])[1].update(
                statement="The company faces bankruptcy and fraud."
            ),
            "inference_lexically_ungrounded",
        ),
    ],
)
def test_unsupported_or_misattributed_output_never_crosses_boundary(
    mutation: Callable[[dict[str, Any]], None], error_code: str
) -> None:
    item = case("contract_catalyst")
    invalid = mutate_report(item, mutation)

    with pytest.raises(AnalysisRejected) as captured:
        run_fixture(item, invalid, invalid)

    assert error_code in captured.value.error_codes
    assert captured.value.attempts == 2


def test_document_interpreter_cannot_return_inference_or_polarity() -> None:
    source = case("contract_catalyst")
    evidence = source.evidence
    report = {
        "prompt_version": PROMPT_VERSION,
        "role": "document_interpreter",
        "assessment": "evidence_sufficient",
        "findings": [
            {
                "kind": "analyst_inference",
                "category": "document_fact",
                "polarity": "bullish",
                "statement": "The contract may help the company.",
                "citations": [
                    {
                        "evidence_id": str(evidence[0].evidence_id),
                        "quote": (
                            "Northstar Sensors Inc. announced a CAD 12.5 million equipment "
                            "contract with City Transit Authority for a 36-month term."
                        ),
                    }
                ],
            }
        ],
        "contradictions": [],
        "limitations": [],
    }
    provider = SequenceModelProvider((json.dumps(report), json.dumps(report)))

    with pytest.raises(AnalysisRejected, match="document_interpreter"):
        AnalystPipeline(provider).analyze(
            role=AnalystRole.DOCUMENT_INTERPRETER,
            evidence=evidence,
            knowledge_cutoff_at=source.knowledge_cutoff_at,
        )


def test_insufficient_evidence_is_a_valid_honest_result() -> None:
    item = case("contract_catalyst")
    report = AnalystReport(
        prompt_version=PROMPT_VERSION,
        role=item.role,
        assessment=Assessment.INSUFFICIENT_EVIDENCE,
        findings=(),
        contradictions=(),
        limitations=("The excerpt does not support the requested analysis.",),
    )
    result = run_fixture(item, report.model_dump_json())
    assert result.report.findings == ()


def test_model_contract_failures_are_classified_for_diagnostics() -> None:
    item = case("contract_catalyst")
    with pytest.raises(AnalysisRejected) as malformed:
        run_fixture(item, "not-json", "still-not-json")
    assert malformed.value.error_codes == ("malformed_json",)

    missing = json.dumps({"prompt_version": PROMPT_VERSION, "role": item.role.value})
    with pytest.raises(AnalysisRejected) as schema:
        run_fixture(item, missing, missing)
    assert "missing_required_field" in schema.value.error_codes


def test_injection_like_evidence_is_quarantined_before_provider_call() -> None:
    item = case("prompt_injection_quarantine")
    provider = SequenceModelProvider(("{}",))

    with pytest.raises(UnsafeEvidenceError, match="quarantined"):
        AnalystPipeline(provider).analyze(
            role=item.role,
            evidence=item.evidence,
            knowledge_cutoff_at=item.knowledge_cutoff_at,
        )

    assert provider.requests == []
    assert detect_prompt_injection(item.evidence[0].text)


def test_future_or_unretrieved_evidence_is_rejected_before_model() -> None:
    item = case("contract_catalyst")
    provider = SequenceModelProvider((report_json(item),))

    with pytest.raises(ValueError, match="unavailable or unretrieved"):
        AnalystPipeline(provider).analyze(
            role=item.role,
            evidence=item.evidence,
            knowledge_cutoff_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    assert provider.requests == []


def test_future_knowledge_cutoff_is_rejected_before_model() -> None:
    item = case("contract_catalyst")
    provider = SequenceModelProvider((report_json(item),))

    with pytest.raises(ValueError, match="cutoff must not be in the future"):
        AnalystPipeline(provider).analyze(
            role=item.role,
            evidence=item.evidence,
            knowledge_cutoff_at=datetime.now(UTC) + timedelta(days=1),
        )
    assert provider.requests == []


def test_prompt_separates_trusted_rules_from_json_encoded_evidence() -> None:
    item = case("contract_catalyst")
    user_prompt = build_user_prompt(item.role, item.evidence)

    assert item.evidence[0].text not in SYSTEM_PROMPT_V2
    assert "BEGIN_UNTRUSTED_EVIDENCE_JSON" in user_prompt
    assert "END_UNTRUSTED_EVIDENCE_JSON" in user_prompt
    assert "OUTPUT_SCHEMA_JSON=" in user_prompt
    assert "additionalProperties" in user_prompt
    assert "no tools" in SYSTEM_PROMPT_V2.lower()


def test_report_validation_rejects_correction_without_later_explicit_language() -> None:
    item = case("corrected_revenue")
    assert item.valid_report is not None
    payload = item.valid_report.model_dump(mode="json")
    citations = cast(
        list[dict[str, Any]], cast(list[dict[str, Any]], payload["contradictions"])[0]["citations"]
    )
    citations[1]["quote"] = "Fiscal Q2 revenue was CAD 18.0 million."
    citations[1]["evidence_id"] = str(item.evidence[0].evidence_id)
    payload_contradictions = cast(list[dict[str, Any]], payload["contradictions"])
    payload_contradictions[0]["citations"] = [
        {
            "evidence_id": str(item.evidence[0].evidence_id),
            "quote": "Fiscal Q2 revenue was CAD 18.0 million.",
        },
        {
            "evidence_id": str(item.evidence[1].evidence_id),
            "quote": "fiscal Q2 revenue to CAD 21.0 million",
        },
    ]
    report = AnalystReport.model_validate(payload)

    assert "correction_not_explicit_or_later" in validate_report(
        report, role=item.role, evidence=item.evidence
    )


def test_explicit_later_correction_status_is_deterministically_normalized() -> None:
    item = case("corrected_revenue")
    assert item.valid_report is not None
    unresolved = item.valid_report.model_copy(
        update={
            "contradictions": tuple(
                contradiction.model_copy(update={"status": ContradictionStatus.UNRESOLVED})
                for contradiction in item.valid_report.contradictions
            )
        }
    )

    normalized, changes = normalize_report(unresolved, item.evidence)

    assert normalized.contradictions[0].status.value == "resolved_by_later_correction"
    assert changes == ("explicit_later_correction_status",)


def test_structurally_provable_raw_labels_are_normalized_and_auditable() -> None:
    item = case("corrected_revenue")
    assert item.valid_report is not None
    payload = item.valid_report.model_dump(mode="json")
    payload["assessment"] = "evidence_sufficient"
    cast(list[dict[str, Any]], payload["findings"])[0]["polarity"] = "bullish"

    normalized, changes = normalize_raw_report(payload)

    normalized_payload = cast(dict[str, Any], normalized)
    assert normalized_payload["assessment"] == "conflicting_evidence"
    assert cast(list[dict[str, Any]], normalized_payload["findings"])[0]["polarity"] == "neutral"
    assert changes == ("contradiction_assessment", "reported_fact_neutral_polarity")


def test_contradictions_require_conflicting_assessment() -> None:
    item = case("corrected_revenue")
    assert item.valid_report is not None
    payload = item.valid_report.model_dump(mode="json")
    payload["assessment"] = "evidence_sufficient"

    with pytest.raises(ValidationError, match="contradictions"):
        AnalystReport.model_validate(payload)


def test_closed_schemas_and_audit_wrapper_keep_output_typed() -> None:
    for model in (AnalystEvidence, AnalystReport, AnalysisAudit, ValidatedAnalysis):
        assert model.model_json_schema()["additionalProperties"] is False


@pytest.mark.parametrize(
    "base_url",
    [
        "https://127.0.0.1:11434",
        "http://example.com:11434",
        "http://user:secret@127.0.0.1:11434",
        "http://127.0.0.1:11434/path",
    ],
)
def test_ollama_adapter_rejects_non_loopback_or_credentialed_origins(base_url: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        OllamaModelProvider(base_url=base_url)


class FakeHttpResponse:
    def __init__(self, body: dict[str, object]) -> None:
        self._body = json.dumps(body).encode()
        self.headers: dict[str, str] = {"Content-Length": str(len(self._body))}

    def __enter__(self) -> FakeHttpResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, amount: int) -> bytes:
        return self._body[:amount]


def test_ollama_payload_has_schema_but_no_tools_or_remote_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = case("contract_catalyst")
    requests: list[Request] = []
    response_values: list[dict[str, object]] = [
        {
            "model": "qwen3:4b",
            "message": {"content": report_json(item)},
        },
        {
            "models": [
                {"name": "qwen3:4b", "digest": "a" * 64},
            ]
        },
    ]
    responses = iter(response_values)

    def fake_urlopen(request: Request, *, timeout: float) -> FakeHttpResponse:
        assert timeout == 240
        requests.append(request)
        return FakeHttpResponse(next(responses))

    monkeypatch.setattr(ollama_module, "urlopen", fake_urlopen)
    provider = OllamaModelProvider()
    response = provider.generate(
        ModelRequest(
            system_prompt=SYSTEM_PROMPT_V2,
            user_prompt=build_user_prompt(item.role, item.evidence),
            output_schema=AnalystReport.model_json_schema(),
        )
    )

    payload = cast(dict[str, Any], json.loads(cast(bytes, requests[0].data).decode()))
    assert requests[0].full_url == "http://127.0.0.1:11434/api/chat"
    assert "format" in payload
    assert "tools" not in payload
    assert "functions" not in payload
    assert response.model_digest == "a" * 64


def test_offline_evaluation_gate_scores_grounding_and_quarantine() -> None:
    responses = tuple(report_json(item) for item in CASES.cases if item.valid_report is not None)

    report = run_evaluation(SequenceModelProvider(responses), load_fixture(FIXTURE_PATH))
    summary = cast(dict[str, object], report["summary"])

    assert summary == {
        "analyzable_acceptance_rate": 1.0,
        "quarantine_rate": 1.0,
        "quality_check_rate": 1.0,
        "median_wall_seconds": summary["median_wall_seconds"],
        "errors": 0,
        "passed": True,
    }
