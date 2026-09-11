"""Shadow comparison of the accepted two-role path with one consolidated Qwen call."""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Literal, Protocol
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kalki_market_intelligence.analysis.consolidated import (
    ConsolidatedShadowPipeline,
    finding_category_counts,
)
from kalki_market_intelligence.analysis.contracts import (
    AnalystEvidence,
    AnalystFinding,
    AnalystRole,
    ModelRequest,
    ModelResponse,
)
from kalki_market_intelligence.analysis.ollama import (
    OllamaModelProvider,
    OllamaPerformanceSample,
)
from kalki_market_intelligence.analysis.pipeline import AnalysisRejected, AnalystPipeline
from kalki_market_intelligence.benchmarking.serving_lab import (
    ServingEvidencePackage,
    ServingPackageSet,
)
from kalki_market_intelligence.contracts.evidence import SourceClass

CONSOLIDATION_REPORT_VERSION: Literal["1.0.0"] = "1.0.0"
CURRENT_ROLES = (AnalystRole.CATALYST_ANALYST, AnalystRole.BULL_BEAR_RISK_ANALYST)
_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d[\d,]*(?:\.\d+)?%?")


class ConsolidationMode(StrEnum):
    ACCEPTED_MULTI_ROLE = "accepted_multi_role"
    CONSOLIDATED_SHADOW = "consolidated_shadow"


class ConsolidationDecision(StrEnum):
    RETAIN_MULTI_ROLE = "retain_multi_role"
    INSUFFICIENT_SUBSTANTIVE_COMPARISON = "insufficient_substantive_comparison"
    ELIGIBLE_FOR_GUARDED_REVIEW = "eligible_for_guarded_review"


class InstrumentedProvider(Protocol):
    @property
    def performance_samples(self) -> tuple[OllamaPerformanceSample, ...]: ...

    def generate(self, request: ModelRequest) -> ModelResponse: ...


class ConsolidationRunRecord(BaseModel):
    """Content-free quality and timing result for one mode and frozen package."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    package_id: str
    case: str
    accession: str
    form: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_characters: int = Field(gt=0, le=3_600)
    mode: ConsolidationMode
    requested_call_count: int = Field(ge=1, le=2)
    completed_call_count: int = Field(ge=0, le=2)
    accepted_contract_count: int = Field(ge=0, le=2)
    all_required_contracts_accepted: bool
    bounded_failures: tuple[str, ...] = Field(max_length=2)
    wall_seconds: float = Field(ge=0)
    provider_seconds: float | None = Field(default=None, ge=0)
    actual_prompt_tokens: int | None = Field(default=None, ge=0)
    generated_tokens: int | None = Field(default=None, ge=0)
    finding_count: int = Field(ge=0, le=12)
    citation_count: int = Field(ge=0, le=48)
    numeric_token_count: int = Field(ge=0, le=96)
    document_fact_count: int = Field(ge=0, le=12)
    catalyst_count: int = Field(ge=0, le=12)
    bull_case_count: int = Field(ge=0, le=12)
    bear_case_count: int = Field(ge=0, le=12)
    risk_count: int = Field(ge=0, le=12)
    inspected_fragment_fidelity_passed: bool
    required_fragment_sha256s: tuple[str, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def counts_reconcile(self) -> ConsolidationRunRecord:
        if self.completed_call_count < self.accepted_contract_count:
            raise ValueError("accepted consolidation calls cannot exceed completed calls")
        expected_required = 2 if self.mode is ConsolidationMode.ACCEPTED_MULTI_ROLE else 1
        if self.requested_call_count != expected_required:
            raise ValueError("consolidation mode call count does not reconcile")
        if self.all_required_contracts_accepted != (
            self.accepted_contract_count == self.requested_call_count
        ):
            raise ValueError("consolidation acceptance summary does not reconcile")
        if self.finding_count != sum(
            (
                self.document_fact_count,
                self.catalyst_count,
                self.bull_case_count,
                self.bear_case_count,
                self.risk_count,
            )
        ):
            raise ValueError("consolidation finding categories do not reconcile")
        if bool(self.bounded_failures) == self.all_required_contracts_accepted:
            raise ValueError("consolidation failures and acceptance are inconsistent")
        return self


class ConsolidationComparison(BaseModel):
    """Deterministic decision inputs for one identical package."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    case: str
    accession: str
    accepted_multi_role: ConsolidationRunRecord
    consolidated_shadow: ConsolidationRunRecord
    output_count_non_regression: bool
    citation_count_non_regression: bool
    numeric_count_non_regression: bool
    significant_latency_improvement: bool
    substantive_reference_available: bool


def _evidence(package: ServingEvidencePackage) -> AnalystEvidence:
    return AnalystEvidence(
        evidence_id=uuid5(NAMESPACE_URL, f"consolidation-lab-evidence:{package.package_id}"),
        subject_id=uuid5(NAMESPACE_URL, f"sec-cik:{package.cik}"),
        source_id=uuid5(NAMESPACE_URL, package.source_url),
        source_class=SourceClass.SEC,
        publisher="U.S. Securities and Exchange Commission",
        locator=package.source_url,
        text=package.evidence_text,
        content_sha256=package.evidence_sha256,
        published_at=package.source_filed_at,
        available_at=package.source_retrieved_at,
        retrieved_at=package.source_retrieved_at,
    )


def _bounded_failure(error: Exception) -> str:
    if isinstance(error, AnalysisRejected):
        return ",".join(error.error_codes)[:255]
    cause = error.__cause__
    return (type(cause).__name__ if cause is not None else type(error).__name__)[:255]


def _sample_totals(
    samples: Sequence[OllamaPerformanceSample],
) -> tuple[float | None, int | None, int | None]:
    if not samples:
        return None, None, None
    seconds = sum(item.total_seconds for item in samples)
    prompt = (
        sum(item.prompt_tokens for item in samples)
        if all(item.prompt_tokens is not None for item in samples)
        else None
    )
    generated = (
        sum(item.generated_tokens for item in samples)
        if all(item.generated_tokens is not None for item in samples)
        else None
    )
    return seconds, prompt, generated


def _run_record(
    *,
    package: ServingEvidencePackage,
    mode: ConsolidationMode,
    requested_calls: int,
    completed_calls: int,
    accepted_calls: int,
    failures: Sequence[str],
    wall_seconds: float,
    samples: Sequence[OllamaPerformanceSample],
    findings: Sequence[AnalystFinding],
) -> ConsolidationRunRecord:
    counts = finding_category_counts(findings)
    provider_seconds, prompt_tokens, generated_tokens = _sample_totals(samples)
    return ConsolidationRunRecord(
        package_id=str(package.package_id),
        case=package.case,
        accession=package.accession,
        form=package.form,
        source_sha256=package.source_sha256,
        evidence_sha256=package.evidence_sha256,
        evidence_characters=len(package.evidence_text),
        mode=mode,
        requested_call_count=requested_calls,
        completed_call_count=completed_calls,
        accepted_contract_count=accepted_calls,
        all_required_contracts_accepted=accepted_calls == requested_calls,
        bounded_failures=tuple(failures),
        wall_seconds=round(wall_seconds, 3),
        provider_seconds=provider_seconds,
        actual_prompt_tokens=prompt_tokens,
        generated_tokens=generated_tokens,
        finding_count=len(findings),
        citation_count=sum(len(item.citations) for item in findings),
        numeric_token_count=sum(len(_NUMBER_PATTERN.findall(item.statement)) for item in findings),
        document_fact_count=counts["document_fact"],
        catalyst_count=counts["catalyst"],
        bull_case_count=counts["bull_case"],
        bear_case_count=counts["bear_case"],
        risk_count=counts["risk"],
        inspected_fragment_fidelity_passed=all(
            fragment in package.evidence_text for fragment in package.required_fragments
        ),
        required_fragment_sha256s=tuple(
            sha256(fragment.encode("utf-8")).hexdigest() for fragment in package.required_fragments
        ),
    )


def execute_accepted_multi_role(
    provider: InstrumentedProvider,
    package: ServingEvidencePackage,
) -> ConsolidationRunRecord:
    """Replay the exact two-role production analysis order with one attempt per role."""

    evidence = _evidence(package)
    pipeline = AnalystPipeline(provider, maximum_attempts=1)
    sample_start = len(provider.performance_samples)
    started = time.monotonic()
    findings: list[AnalystFinding] = []
    failures: list[str] = []
    accepted = 0
    completed = 0
    for role in CURRENT_ROLES:
        try:
            analysis = pipeline.analyze(
                role=role,
                evidence=(evidence,),
                knowledge_cutoff_at=package.source_retrieved_at,
            )
        except Exception as error:
            failures.append(_bounded_failure(error))
            break
        completed += 1
        accepted += 1
        findings.extend(analysis.report.findings)
    samples = provider.performance_samples[sample_start:]
    completed = max(completed, len(samples))
    return _run_record(
        package=package,
        mode=ConsolidationMode.ACCEPTED_MULTI_ROLE,
        requested_calls=2,
        completed_calls=completed,
        accepted_calls=accepted,
        failures=failures,
        wall_seconds=time.monotonic() - started,
        samples=samples,
        findings=findings,
    )


def execute_consolidated_shadow(
    provider: InstrumentedProvider,
    package: ServingEvidencePackage,
) -> ConsolidationRunRecord:
    """Replay one consolidated attempt without exposing it to a production consumer."""

    sample_start = len(provider.performance_samples)
    started = time.monotonic()
    findings: tuple[AnalystFinding, ...] = ()
    failures: list[str] = []
    accepted = 0
    try:
        analysis = ConsolidatedShadowPipeline(provider).analyze(
            evidence=(_evidence(package),),
            knowledge_cutoff_at=package.source_retrieved_at,
        )
    except Exception as error:
        failures.append(_bounded_failure(error))
    else:
        accepted = 1
        findings = analysis.report.findings
    samples = provider.performance_samples[sample_start:]
    return _run_record(
        package=package,
        mode=ConsolidationMode.CONSOLIDATED_SHADOW,
        requested_calls=1,
        completed_calls=1 if accepted else min(1, len(samples)),
        accepted_calls=accepted,
        failures=failures,
        wall_seconds=time.monotonic() - started,
        samples=samples,
        findings=findings,
    )


def compare_case(
    current: ConsolidationRunRecord,
    consolidated: ConsolidationRunRecord,
) -> ConsolidationComparison:
    if current.package_id != consolidated.package_id:
        raise ValueError("consolidation comparison requires one identical package")
    compared_counts = (
        "catalyst_count",
        "bull_case_count",
        "bear_case_count",
        "risk_count",
    )
    output_non_regression = all(
        getattr(consolidated, field) >= getattr(current, field) for field in compared_counts
    )
    return ConsolidationComparison(
        case=current.case,
        accession=current.accession,
        accepted_multi_role=current,
        consolidated_shadow=consolidated,
        output_count_non_regression=output_non_regression,
        citation_count_non_regression=consolidated.citation_count >= current.citation_count,
        numeric_count_non_regression=(
            consolidated.numeric_token_count >= current.numeric_token_count
        ),
        significant_latency_improvement=(consolidated.wall_seconds <= current.wall_seconds * 0.67),
        substantive_reference_available=current.finding_count > 0,
    )


def summarize_comparisons(
    comparisons: Sequence[ConsolidationComparison],
) -> dict[str, object]:
    rows = tuple(comparisons)
    if not rows:
        raise ValueError("consolidation summary requires at least one comparison")
    current_seconds = sum(item.accepted_multi_role.wall_seconds for item in rows)
    consolidated_seconds = sum(item.consolidated_shadow.wall_seconds for item in rows)
    quality_gate = all(
        item.accepted_multi_role.all_required_contracts_accepted
        and item.consolidated_shadow.all_required_contracts_accepted
        and item.output_count_non_regression
        and item.citation_count_non_regression
        and item.numeric_count_non_regression
        and item.accepted_multi_role.inspected_fragment_fidelity_passed
        and item.consolidated_shadow.inspected_fragment_fidelity_passed
        for item in rows
    )
    substantive = any(item.substantive_reference_available for item in rows)
    latency_ratio = consolidated_seconds / current_seconds if current_seconds else None
    throughput_gate = latency_ratio is not None and latency_ratio <= 0.67
    if quality_gate and substantive and throughput_gate:
        decision = ConsolidationDecision.ELIGIBLE_FOR_GUARDED_REVIEW
    elif not substantive:
        decision = ConsolidationDecision.INSUFFICIENT_SUBSTANTIVE_COMPARISON
    else:
        decision = ConsolidationDecision.RETAIN_MULTI_ROLE
    current_values = [item.accepted_multi_role.wall_seconds for item in rows]
    consolidated_values = [item.consolidated_shadow.wall_seconds for item in rows]
    return {
        "sample_count": len(rows),
        "sample_label": "small_n" if len(rows) < 30 else "observed",
        "quality_non_regression_gate": quality_gate,
        "substantive_reference_available": substantive,
        "throughput_gate": throughput_gate,
        "decision": decision.value,
        "current_total_calls": sum(item.accepted_multi_role.completed_call_count for item in rows),
        "consolidated_total_calls": sum(
            item.consolidated_shadow.completed_call_count for item in rows
        ),
        "current_total_seconds": round(current_seconds, 3),
        "consolidated_total_seconds": round(consolidated_seconds, 3),
        "consolidated_to_current_latency_ratio": (
            round(latency_ratio, 4) if latency_ratio is not None else None
        ),
        "current_median_seconds": round(statistics.median(current_values), 3),
        "consolidated_median_seconds": round(statistics.median(consolidated_values), 3),
    }


def _load_packages(path: Path) -> ServingPackageSet:
    return ServingPackageSet.model_validate_json(path.read_text(encoding="utf-8"))


def _write_json_exclusive(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2)
        handle.write("\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packages", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", default="qwen3:4b")
    parser.add_argument("--expected-digest", required=True)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--case", action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        package_set = _load_packages(arguments.packages)
        selected = tuple(
            package
            for package in package_set.packages
            if package.strategy == "form_aware"
            and (not arguments.case or package.case in arguments.case)
        )
        if not selected:
            raise ValueError("consolidation benchmark selection contains no packages")
        provider = OllamaModelProvider(
            model=arguments.model,
            base_url=arguments.base_url,
            timeout_seconds=arguments.timeout,
            expected_digest=arguments.expected_digest,
        )
        comparisons: list[ConsolidationComparison] = []
        for index, package in enumerate(selected):
            if index % 2 == 0:
                current = execute_accepted_multi_role(provider, package)
                consolidated = execute_consolidated_shadow(provider, package)
            else:
                consolidated = execute_consolidated_shadow(provider, package)
                current = execute_accepted_multi_role(provider, package)
            comparisons.append(compare_case(current, consolidated))
        provider.unload()
        summary = summarize_comparisons(comparisons)
        report = {
            "schema_version": CONSOLIDATION_REPORT_VERSION,
            "generated_at": datetime.now(UTC).isoformat(),
            "package_set_sha256": sha256(arguments.packages.read_bytes()).hexdigest(),
            "package_schema_version": package_set.schema_version,
            "model": arguments.model,
            "model_digest": arguments.expected_digest,
            "provider": "ollama",
            "context_tokens": 4_096,
            "maximum_output_tokens": 768,
            "maximum_attempts_per_call": 1,
            "concurrent_inference": False,
            "gemma_enabled": False,
            "execution_order": "alternating_current_first_by_case",
            "summary": summary,
            "comparisons": [item.model_dump(mode="json") for item in comparisons],
            "limitations": [
                "This is a three-filing engineering sample, not market or general model evidence.",
                "Only validated category/citation/numeric counts are retained; prompts, evidence, "
                "responses, findings and hidden reasoning are absent from the report.",
                "Count non-regression does not prove semantic equivalence; adoption requires a "
                "substantive reference and all deterministic gates.",
                "Execution order alternates by case but cannot remove thermal, cache or "
                "small-sample bias.",
                "The benchmark cannot deploy or configure a model, worker, publication or "
                "delivery.",
            ],
        }
        _write_json_exclusive(arguments.output, report)
        print(json.dumps(summary, indent=2))
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print(f"consolidation lab failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
