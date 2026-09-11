"""Repeatable quality gate for the Phase 7 local analyst pipeline."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from kalki_market_intelligence.analysis.contracts import (
    AnalystEvidence,
    AnalystReport,
    AnalystRole,
    ContradictionStatus,
)
from kalki_market_intelligence.analysis.ollama import OllamaModelProvider
from kalki_market_intelligence.analysis.pipeline import (
    AnalysisRejected,
    AnalystPipeline,
    UnsafeEvidenceError,
)
from kalki_market_intelligence.analysis.provider import ModelProvider
from kalki_market_intelligence.contracts.common import UtcDatetime

DEFAULT_FIXTURE = Path("data/fixtures/analysis/representative-cases.json")


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    role: AnalystRole
    knowledge_cutoff_at: UtcDatetime
    evidence: tuple[AnalystEvidence, ...]
    valid_report: AnalystReport | None = None
    quarantine: bool = False
    expected_terms: tuple[str, ...] = ()
    expected_contradiction_statuses: tuple[ContradictionStatus, ...] = ()


class EvaluationFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: str
    description: str
    cases: tuple[EvaluationCase, ...] = Field(min_length=1)


class EvaluationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    case: str
    accepted: bool
    quarantine_passed: bool
    checks_passed: int
    checks_total: int
    attempts: int | None
    wall_seconds: float
    report: dict[str, Any] | None
    error: str | None


class EvaluationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    analyzable_acceptance_rate: float
    quarantine_rate: float
    quality_check_rate: float
    median_wall_seconds: float
    errors: int
    passed: bool


def load_fixture(path: Path = DEFAULT_FIXTURE) -> EvaluationFixture:
    return EvaluationFixture.model_validate_json(path.read_text(encoding="utf-8"))


def run_evaluation(
    provider: ModelProvider,
    fixture: EvaluationFixture,
    *,
    maximum_median_seconds: float = 120,
    minimum_quality_check_rate: float = 0.80,
) -> dict[str, object]:
    if maximum_median_seconds <= 0:
        raise ValueError("evaluation latency gate must be positive")
    if not 0 <= minimum_quality_check_rate <= 1:
        raise ValueError("evaluation quality-check gate must be between zero and one")
    records: list[EvaluationRecord] = []
    pipeline = AnalystPipeline(provider)
    for evaluation_case in fixture.cases:
        started = time.perf_counter()
        if evaluation_case.quarantine:
            try:
                pipeline.analyze(
                    role=evaluation_case.role,
                    evidence=evaluation_case.evidence,
                    knowledge_cutoff_at=evaluation_case.knowledge_cutoff_at,
                )
            except UnsafeEvidenceError:
                records.append(
                    EvaluationRecord(
                        case=evaluation_case.name,
                        accepted=False,
                        quarantine_passed=True,
                        checks_passed=1,
                        checks_total=1,
                        attempts=None,
                        wall_seconds=time.perf_counter() - started,
                        report=None,
                        error=None,
                    )
                )
            else:
                records.append(
                    EvaluationRecord(
                        case=evaluation_case.name,
                        accepted=False,
                        quarantine_passed=False,
                        checks_passed=0,
                        checks_total=1,
                        attempts=None,
                        wall_seconds=time.perf_counter() - started,
                        report=None,
                        error="unsafe evidence was not quarantined",
                    )
                )
            continue
        try:
            result = pipeline.analyze(
                role=evaluation_case.role,
                evidence=evaluation_case.evidence,
                knowledge_cutoff_at=evaluation_case.knowledge_cutoff_at,
            )
            passed, total = score_report(result.report, evaluation_case)
            records.append(
                EvaluationRecord(
                    case=evaluation_case.name,
                    accepted=True,
                    quarantine_passed=False,
                    checks_passed=passed,
                    checks_total=total,
                    attempts=result.audit.attempts,
                    wall_seconds=time.perf_counter() - started,
                    report=result.report.model_dump(mode="json"),
                    error=None,
                )
            )
        except (AnalysisRejected, RuntimeError, ValueError) as error:
            expected_checks = _expected_check_count(evaluation_case)
            records.append(
                EvaluationRecord(
                    case=evaluation_case.name,
                    accepted=False,
                    quarantine_passed=False,
                    checks_passed=0,
                    checks_total=expected_checks,
                    attempts=getattr(error, "attempts", None),
                    wall_seconds=time.perf_counter() - started,
                    report=None,
                    error=f"{type(error).__name__}: {error}",
                )
            )
    summary = summarize_evaluation(
        records,
        maximum_median_seconds=maximum_median_seconds,
        minimum_quality_check_rate=minimum_quality_check_rate,
    )
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "fixture_schema_version": fixture.schema_version,
        "gates": {
            "analyzable_acceptance_rate": 1.0,
            "quarantine_rate": 1.0,
            "minimum_quality_check_rate": minimum_quality_check_rate,
            "maximum_median_seconds": maximum_median_seconds,
        },
        "records": [record.model_dump(mode="json") for record in records],
        "summary": summary.model_dump(mode="json"),
    }


def score_report(actual: AnalystReport, evaluation_case: EvaluationCase) -> tuple[int, int]:
    expected = evaluation_case.valid_report
    if expected is None:
        raise ValueError("analyzable evaluation case requires an expected report")
    checks = [actual.assessment is expected.assessment]
    supported_text = "\n".join(
        [item.statement for item in actual.findings]
        + [citation.quote for item in actual.findings for citation in item.citations]
        + [item.topic for item in actual.contradictions]
        + [citation.quote for item in actual.contradictions for citation in item.citations]
    ).casefold()
    checks.extend(term.casefold() in supported_text for term in evaluation_case.expected_terms)
    actual_statuses = {item.status for item in actual.contradictions}
    checks.extend(
        status in actual_statuses for status in evaluation_case.expected_contradiction_statuses
    )
    return sum(checks), len(checks)


def summarize_evaluation(
    records: list[EvaluationRecord],
    *,
    maximum_median_seconds: float,
    minimum_quality_check_rate: float,
) -> EvaluationSummary:
    analyzable = [
        record for record in records if not record.quarantine_passed and record.checks_total > 1
    ]
    quarantine = [record for record in records if record.checks_total == 1]
    if not analyzable or not quarantine:
        raise ValueError("evaluation requires analyzable and quarantine cases")
    accepted_rate = sum(record.accepted for record in analyzable) / len(analyzable)
    quarantine_rate = sum(record.quarantine_passed for record in quarantine) / len(quarantine)
    quality_rate = sum(record.checks_passed for record in analyzable) / sum(
        record.checks_total for record in analyzable
    )
    median_seconds = statistics.median(record.wall_seconds for record in analyzable)
    errors = sum(record.error is not None for record in records)
    passed = (
        accepted_rate == 1.0
        and quarantine_rate == 1.0
        and quality_rate >= minimum_quality_check_rate
        and median_seconds <= maximum_median_seconds
        and errors == 0
    )
    return EvaluationSummary(
        analyzable_acceptance_rate=accepted_rate,
        quarantine_rate=quarantine_rate,
        quality_check_rate=quality_rate,
        median_wall_seconds=median_seconds,
        errors=errors,
        passed=passed,
    )


def _expected_check_count(evaluation_case: EvaluationCase) -> int:
    return (
        1
        + len(evaluation_case.expected_terms)
        + len(evaluation_case.expected_contradiction_statuses)
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="qwen3:4b")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument(
        "--output", type=Path, default=Path("data/evaluations/phase7-qwen3-4b.json")
    )
    parser.add_argument("--timeout", type=float, default=240)
    parser.add_argument("--maximum-median-seconds", type=float, default=120)
    parser.add_argument("--minimum-quality-check-rate", type=float, default=0.80)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        report = run_evaluation(
            OllamaModelProvider(
                model=arguments.model,
                base_url=arguments.base_url,
                timeout_seconds=arguments.timeout,
            ),
            load_fixture(arguments.fixture),
            maximum_median_seconds=arguments.maximum_median_seconds,
            minimum_quality_check_rate=arguments.minimum_quality_check_rate,
        )
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except (OSError, RuntimeError, ValueError) as error:
        print(f"evaluation failed: {error}", file=sys.stderr)
        return 2
    summary = report["summary"]
    print(json.dumps(summary, indent=2))
    return 0 if isinstance(summary, dict) and summary.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
