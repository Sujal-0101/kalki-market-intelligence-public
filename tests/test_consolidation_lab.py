"""Content-free one-call consolidation benchmark tests."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from kalki_market_intelligence.analysis.consolidated import (
    CONSOLIDATED_PROMPT_VERSION,
    ConsolidatedAnalystReport,
)
from kalki_market_intelligence.analysis.contracts import (
    AnalystFinding,
    AnalystReport,
    AnalystRole,
    Assessment,
    EvidenceCitation,
    FindingCategory,
    FindingKind,
    FindingPolarity,
    ModelRequest,
    ModelResponse,
)
from kalki_market_intelligence.analysis.ollama import OllamaPerformanceSample
from kalki_market_intelligence.benchmarking.consolidation_lab import (
    ConsolidationDecision,
    compare_case,
    execute_accepted_multi_role,
    execute_consolidated_shadow,
    summarize_comparisons,
)
from kalki_market_intelligence.benchmarking.serving_lab import (
    PACKAGE_SCHEMA_VERSION,
    ServingEvidencePackage,
)

TEXT = "The issuer reported a signed agreement with a value of $10 million."
NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


class InstrumentedSequenceProvider:
    def __init__(self, responses: tuple[str, ...]) -> None:
        self._responses = iter(responses)
        self.requests: list[ModelRequest] = []

    @property
    def performance_samples(self) -> tuple[OllamaPerformanceSample, ...]:
        return ()

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(
            provider_name="deterministic-sequence",
            model_name="fixture-model",
            model_digest="a" * 64,
            content=next(self._responses),
        )


def package() -> ServingEvidencePackage:
    evidence_hash = sha256(TEXT.encode()).hexdigest()
    package_id = uuid5(
        NAMESPACE_URL,
        ":".join(
            (
                "kalki-serving-package",
                PACKAGE_SCHEMA_VERSION,
                "0000000001-26-000001",
                "form_aware",
                AnalystRole.CATALYST_ANALYST.value,
                evidence_hash,
            )
        ),
    )
    return ServingEvidencePackage(
        package_id=package_id,
        case="synthetic-consolidation-contract",
        strategy="form_aware",
        accession="0000000001-26-000001",
        cik="1",
        company="SYNTHETIC CONTRACT ISSUER",
        form="8-K",
        source_url="https://www.sec.gov/Archives/edgar/data/1/test.txt",
        source_sha256="b" * 64,
        source_filed_at=NOW,
        source_retrieved_at=NOW,
        role=AnalystRole.CATALYST_ANALYST,
        evidence_text=TEXT,
        evidence_sha256=evidence_hash,
        required_fragments=("signed agreement", "$10 million"),
    )


def role_report(role: AnalystRole, findings: tuple[AnalystFinding, ...] = ()) -> str:
    return AnalystReport(
        prompt_version="analyst-v2",
        role=role,
        assessment=(
            Assessment.EVIDENCE_SUFFICIENT if findings else Assessment.INSUFFICIENT_EVIDENCE
        ),
        findings=findings,
        contradictions=(),
        limitations=(),
    ).model_dump_json()


def consolidated_report(findings: tuple[AnalystFinding, ...] = ()) -> str:
    return ConsolidatedAnalystReport(
        prompt_version=CONSOLIDATED_PROMPT_VERSION,
        assessment=(
            Assessment.EVIDENCE_SUFFICIENT if findings else Assessment.INSUFFICIENT_EVIDENCE
        ),
        material_facts=(),
        catalysts=findings,
        positive_factors=(),
        negative_factors=(),
        risks=(),
        contradictions=(),
        limitations=(),
    ).model_dump_json()


def catalyst_finding() -> AnalystFinding:
    evidence_id = uuid5(NAMESPACE_URL, f"consolidation-lab-evidence:{package().package_id}")
    return AnalystFinding(
        kind=FindingKind.REPORTED_FACT,
        category=FindingCategory.CATALYST,
        polarity=FindingPolarity.NEUTRAL,
        statement=TEXT,
        citations=(EvidenceCitation(evidence_id=evidence_id, quote=TEXT),),
    )


def test_identical_package_replays_two_current_calls_and_one_shadow_call() -> None:
    current_provider = InstrumentedSequenceProvider(
        (
            role_report(AnalystRole.CATALYST_ANALYST),
            role_report(AnalystRole.BULL_BEAR_RISK_ANALYST),
        )
    )
    consolidated_provider = InstrumentedSequenceProvider((consolidated_report(),))

    current = execute_accepted_multi_role(current_provider, package())
    consolidated = execute_consolidated_shadow(consolidated_provider, package())
    comparison = compare_case(current, consolidated)

    assert len(current_provider.requests) == 2
    assert len(consolidated_provider.requests) == 1
    assert current.all_required_contracts_accepted
    assert consolidated.all_required_contracts_accepted
    assert comparison.substantive_reference_available is False
    assert (
        summarize_comparisons((comparison,))["decision"]
        == ConsolidationDecision.INSUFFICIENT_SUBSTANTIVE_COMPARISON.value
    )


def test_substantive_count_non_regression_and_throughput_gate_are_explicit() -> None:
    finding = catalyst_finding()
    current = execute_accepted_multi_role(
        InstrumentedSequenceProvider(
            (
                role_report(AnalystRole.CATALYST_ANALYST, (finding,)),
                role_report(AnalystRole.BULL_BEAR_RISK_ANALYST),
            )
        ),
        package(),
    ).model_copy(update={"wall_seconds": 100.0})
    consolidated = execute_consolidated_shadow(
        InstrumentedSequenceProvider((consolidated_report((finding,)),)),
        package(),
    ).model_copy(update={"wall_seconds": 50.0})

    comparison = compare_case(current, consolidated)
    summary = summarize_comparisons((comparison,))

    assert comparison.output_count_non_regression
    assert comparison.citation_count_non_regression
    assert comparison.numeric_count_non_regression
    assert comparison.significant_latency_improvement
    assert summary["quality_non_regression_gate"] is True
    assert summary["throughput_gate"] is True
    assert summary["decision"] == ConsolidationDecision.ELIGIBLE_FOR_GUARDED_REVIEW.value


def test_benchmark_records_exclude_prompts_evidence_and_model_content() -> None:
    record = execute_consolidated_shadow(
        InstrumentedSequenceProvider((consolidated_report(),)), package()
    )
    serialized = record.model_dump_json().casefold()

    assert TEXT.casefold() not in serialized
    for prohibited in (
        "system_prompt",
        "user_prompt",
        "response",
        "reasoning",
        "excerpt",
        "hypothesis",
    ):
        assert prohibited not in serialized
