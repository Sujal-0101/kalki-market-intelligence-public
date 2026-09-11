"""Compare local models on Kalki's evidence-bound SEC-analysis workload."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from kalki_market_intelligence.analysis.contracts import (
    AnalystReport,
    ModelRequest,
    analyst_generation_schema,
)
from kalki_market_intelligence.analysis.ollama import (
    ModelProviderError,
    OllamaModelProvider,
    OllamaPerformanceSample,
)
from kalki_market_intelligence.analysis.pipeline import normalize_raw_report, normalize_report
from kalki_market_intelligence.analysis.pipeline import validate_report as validate_analyst_report
from kalki_market_intelligence.analysis.prompts import SYSTEM_PROMPT_V2, build_user_prompt
from kalki_market_intelligence.benchmarking.sec_cases import SEC_MODEL_CASES, SecModelCase

GROUNDING_ERROR_CODES = frozenset(
    {
        "inference_lexically_ungrounded",
        "quote_not_verbatim",
        "reported_fact_not_verbatim",
        "unknown_evidence_id",
        "unsupported_numeric_token",
        "unsupported_url",
    }
)


class SecModelRecord(BaseModel):
    """One raw, single-attempt model execution scored by deterministic code."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    case: str
    source_kind: str
    capability: str
    repeat: int
    schema_valid: bool
    post_validation_accepted: bool
    assessment_correct: bool
    required_terms_found: int
    required_terms_total: int
    forbidden_terms_absent: bool
    exact_quotes: int
    citations_total: int
    unsupported_claim_detected: bool
    numeric_fidelity: bool | None
    identity_correct: bool | None
    instruction_followed: bool
    normalized_output: dict[str, Any] | None
    validation_error_codes: tuple[str, ...]
    wall_seconds: float
    performance: OllamaPerformanceSample | None
    model_name: str | None
    model_digest: str | None
    error: str | None


class SecModelSummary(BaseModel):
    """Workload-specific reliability, quality, repeatability, and speed metrics."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    runs: int
    schema_valid_rate: float
    post_validation_acceptance_rate: float
    exact_quotation_fidelity_rate: float
    unsupported_claim_run_rate: float
    numeric_fidelity_rate: float
    identity_correctness_rate: float
    catalyst_quality_rate: float
    risk_quality_rate: float
    uncertainty_calibration_rate: float
    instruction_following_rate: float
    deterministic_case_rate: float
    median_wall_seconds: float
    median_generated_tokens_per_second: float
    timeout_or_failure_rate: float
    gate_passed: bool


def _supported_text(report: AnalystReport) -> str:
    return "\n".join(
        [item.statement for item in report.findings]
        + [citation.quote for item in report.findings for citation in item.citations]
        + [item.topic for item in report.contradictions]
        + [citation.quote for item in report.contradictions for citation in item.citations]
    )


def _citation_fidelity(report: AnalystReport, case: SecModelCase) -> tuple[int, int]:
    evidence = {item.evidence_id: item.text for item in case.evidence}
    citations = [citation for finding in report.findings for citation in finding.citations] + [
        citation for contradiction in report.contradictions for citation in contradiction.citations
    ]
    exact = sum(
        citation.evidence_id in evidence and citation.quote in evidence[citation.evidence_id]
        for citation in citations
    )
    return exact, len(citations)


def _record_failure(
    case: SecModelCase,
    *,
    repeat: int,
    wall_seconds: float,
    error: Exception,
    schema_valid: bool = False,
) -> SecModelRecord:
    return SecModelRecord(
        case=case.name,
        source_kind=case.source_kind,
        capability=case.capability,
        repeat=repeat,
        schema_valid=schema_valid,
        post_validation_accepted=False,
        assessment_correct=False,
        required_terms_found=0,
        required_terms_total=len(case.required_terms),
        forbidden_terms_absent=False,
        exact_quotes=0,
        citations_total=0,
        unsupported_claim_detected=False,
        numeric_fidelity=None if not case.numeric_terms else False,
        identity_correct=None if not case.identity_terms else False,
        instruction_followed=False,
        normalized_output=None,
        validation_error_codes=("schema_validation",),
        wall_seconds=wall_seconds,
        performance=None,
        model_name=None,
        model_digest=None,
        error=f"{type(error).__name__}: {error}",
    )


def execute_case(
    provider: OllamaModelProvider,
    case: SecModelCase,
    *,
    repeat: int,
) -> SecModelRecord:
    """Execute one production-shaped request without hiding a first-attempt failure."""

    started = time.perf_counter()
    sample_count = len(provider.performance_samples)
    try:
        response = provider.generate(
            ModelRequest(
                system_prompt=SYSTEM_PROMPT_V2,
                user_prompt=build_user_prompt(case.role, case.evidence),
                output_schema=analyst_generation_schema(),
            )
        )
    except (ModelProviderError, RuntimeError, ValueError) as error:
        return _record_failure(
            case, repeat=repeat, wall_seconds=time.perf_counter() - started, error=error
        )
    try:
        decoded: object = json.loads(response.content)
        decoded, _ = normalize_raw_report(decoded)
        report = AnalystReport.model_validate(decoded)
    except (json.JSONDecodeError, ValidationError, ValueError) as error:
        return _record_failure(
            case,
            repeat=repeat,
            wall_seconds=time.perf_counter() - started,
            error=error,
        )
    report, _ = normalize_report(report, case.evidence)
    validation_errors = validate_analyst_report(report, role=case.role, evidence=case.evidence)
    supported = _supported_text(report)
    lowered = supported.casefold()
    found = sum(term.casefold() in lowered for term in case.required_terms)
    forbidden_absent = all(term.casefold() not in lowered for term in case.forbidden_terms)
    exact_quotes, citations_total = _citation_fidelity(report, case)
    numeric_fidelity = (
        None
        if not case.numeric_terms
        else all(term.casefold() in lowered for term in case.numeric_terms)
    )
    identity_correct = (
        None
        if not case.identity_terms
        else all(term.casefold() in lowered for term in case.identity_terms)
    )
    instruction_errors = {
        "category_not_allowed_for_role",
        "document_interpreter_must_report_neutral_facts",
        "prompt_version_mismatch",
        "role_mismatch",
    }
    performance = (
        provider.performance_samples[-1]
        if len(provider.performance_samples) > sample_count
        else None
    )
    return SecModelRecord(
        case=case.name,
        source_kind=case.source_kind,
        capability=case.capability,
        repeat=repeat,
        schema_valid=True,
        post_validation_accepted=not validation_errors,
        assessment_correct=report.assessment is case.expected_assessment,
        required_terms_found=found,
        required_terms_total=len(case.required_terms),
        forbidden_terms_absent=forbidden_absent,
        exact_quotes=exact_quotes,
        citations_total=citations_total,
        unsupported_claim_detected=bool(GROUNDING_ERROR_CODES.intersection(validation_errors)),
        numeric_fidelity=numeric_fidelity,
        identity_correct=identity_correct,
        instruction_followed=(
            forbidden_absent and not instruction_errors.intersection(validation_errors)
        ),
        normalized_output=report.model_dump(mode="json"),
        validation_error_codes=validation_errors,
        wall_seconds=time.perf_counter() - started,
        performance=performance,
        model_name=response.model_name,
        model_digest=response.model_digest,
        error=None,
    )


def _capability_rate(records: Sequence[SecModelRecord], capability: str) -> float:
    selected = [record for record in records if record.capability == capability]
    if not selected:
        return 0.0
    return sum(
        record.post_validation_accepted
        and record.assessment_correct
        and record.required_terms_found == record.required_terms_total
        for record in selected
    ) / len(selected)


def summarize(records: Sequence[SecModelRecord]) -> SecModelSummary:
    if not records:
        raise ValueError("at least one SEC model record is required")
    citations = sum(record.citations_total for record in records)
    exact_quotes = sum(record.exact_quotes for record in records)
    numeric = [record.numeric_fidelity for record in records if record.numeric_fidelity is not None]
    identity = [
        record.identity_correct for record in records if record.identity_correct is not None
    ]
    rates = [
        record.performance.generated_tokens_per_second
        for record in records
        if record.performance is not None
        and record.performance.generated_tokens_per_second is not None
    ]
    grouped: dict[str, list[SecModelRecord]] = {}
    for record in records:
        grouped.setdefault(record.case, []).append(record)
    deterministic = 0
    for case_records in grouped.values():
        outputs = {
            json.dumps(record.normalized_output, sort_keys=True)
            for record in case_records
            if record.normalized_output is not None
        }
        if len(case_records) >= 2 and len(outputs) == 1:
            deterministic += 1
    runs = len(records)
    schema_rate = sum(record.schema_valid for record in records) / runs
    validation_rate = sum(record.post_validation_accepted for record in records) / runs
    quote_rate = exact_quotes / citations if citations else 0.0
    unsupported_rate = sum(record.unsupported_claim_detected for record in records) / runs
    numeric_rate = sum(bool(value) for value in numeric) / len(numeric) if numeric else 0.0
    identity_rate = sum(bool(value) for value in identity) / len(identity) if identity else 0.0
    catalyst_rate = _capability_rate(records, "catalyst")
    risk_rate = _capability_rate(records, "risk")
    uncertainty_rate = _capability_rate(records, "uncertainty")
    instruction_rate = sum(record.instruction_followed for record in records) / runs
    deterministic_rate = deterministic / len(grouped)
    failure_rate = sum(record.error is not None for record in records) / runs
    gate_passed = (
        schema_rate == 1.0
        and validation_rate >= 0.90
        and quote_rate == 1.0
        and unsupported_rate == 0.0
        and numeric_rate == 1.0
        and identity_rate == 1.0
        and catalyst_rate == 1.0
        and risk_rate == 1.0
        and uncertainty_rate == 1.0
        and instruction_rate == 1.0
        and deterministic_rate == 1.0
        and failure_rate == 0.0
    )
    return SecModelSummary(
        runs=runs,
        schema_valid_rate=schema_rate,
        post_validation_acceptance_rate=validation_rate,
        exact_quotation_fidelity_rate=quote_rate,
        unsupported_claim_run_rate=unsupported_rate,
        numeric_fidelity_rate=numeric_rate,
        identity_correctness_rate=identity_rate,
        catalyst_quality_rate=catalyst_rate,
        risk_quality_rate=risk_rate,
        uncertainty_calibration_rate=uncertainty_rate,
        instruction_following_rate=instruction_rate,
        deterministic_case_rate=deterministic_rate,
        median_wall_seconds=statistics.median(record.wall_seconds for record in records),
        median_generated_tokens_per_second=statistics.median(rates) if rates else 0.0,
        timeout_or_failure_rate=failure_rate,
        gate_passed=gate_passed,
    )


def run_benchmark(
    *, model: str, base_url: str, repeats: int, timeout_seconds: float
) -> dict[str, object]:
    if repeats < 2:
        raise ValueError("SEC model comparison requires at least two repeats")
    provider = OllamaModelProvider(model=model, base_url=base_url, timeout_seconds=timeout_seconds)
    records = [
        execute_case(provider, case, repeat=repeat)
        for repeat in range(1, repeats + 1)
        for case in SEC_MODEL_CASES
    ]
    summary = summarize(records)
    digest = next((record.model_digest for record in records if record.model_digest), None)
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "model": model,
        "model_digest": digest,
        "benchmark": "kalki-sec-analysis-v1",
        "repeats": repeats,
        "context_tokens": 4096,
        "maximum_output_tokens": 768,
        "temperature": 0,
        "seed": 42,
        "thinking": False,
        "corpus": {
            "cases": len(SEC_MODEL_CASES),
            "real_public_sec_excerpts": sum(
                case.source_kind == "real_public_sec_excerpt" for case in SEC_MODEL_CASES
            ),
            "synthetic_sec_style_tests": sum(
                case.source_kind == "synthetic_sec_style_test" for case in SEC_MODEL_CASES
            ),
        },
        "summary": summary.model_dump(mode="json"),
        "records": [record.model_dump(mode="json") for record in records],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def ensure_output_writable(output: Path) -> None:
    """Fail before inference when the destination cannot store the final report."""

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8"):
        pass


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        ensure_output_writable(arguments.output)
        report = run_benchmark(
            model=arguments.model,
            base_url=arguments.base_url,
            repeats=arguments.repeats,
            timeout_seconds=arguments.timeout,
        )
        arguments.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except (OSError, RuntimeError, ValueError) as error:
        print(f"SEC model benchmark failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
