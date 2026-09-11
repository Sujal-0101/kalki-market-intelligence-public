"""Focused, isolated qualification runner for the selective Gemma 4 verifier."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

from pydantic import BaseModel, ConfigDict

from kalki_market_intelligence.analysis.ollama import (
    ModelProviderError,
    OllamaModelProvider,
    OllamaPerformanceSample,
)
from kalki_market_intelligence.benchmarking.verifier_cases import (
    verifier_qualification_cases,
)
from kalki_market_intelligence.verification.contracts import (
    ArbitrationResult,
    VerifierReport,
    VerifierVerdict,
)
from kalki_market_intelligence.verification.pipeline import (
    VerificationRejected,
    VerifierPipeline,
    arbitrate_verifier_report,
)

DEFAULT_MODEL = "gemma4:12b-it-q4_K_M"
DEFAULT_DIGEST = "4eb23ef187e2c5462566d6a1d3bbbc2f1346d0b4327cbb66d58fffbcc9b2b05c"


class QualificationCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    source_kind: str
    invoked: bool
    non_invocation_reason: str | None
    passed: bool
    wall_seconds: float
    provider_calls: int
    performance: tuple[OllamaPerformanceSample, ...]
    report: VerifierReport | None
    arbitration: ArbitrationResult | None
    error: str | None


class QualificationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: str = "kalki-verifier-qualification-v1"
    generated_at: datetime
    model: str
    model_digest: str
    cases: tuple[QualificationCaseResult, ...]
    invoked_cases: int
    passed_cases: int
    valid_structured_output_rate: float
    total_wall_seconds: float
    passed: bool


def run_qualification(
    *,
    model: str,
    model_digest: str,
    base_url: str,
) -> QualificationReport:
    provider = OllamaModelProvider(
        model=model,
        expected_digest=model_digest,
        base_url=base_url,
        timeout_seconds=900,
        keep_alive="10m",
    )
    pipeline = VerifierPipeline(provider)
    results: list[QualificationCaseResult] = []
    started = monotonic()
    try:
        for case in verifier_qualification_cases():
            if case.package is None:
                results.append(
                    QualificationCaseResult(
                        name=case.name,
                        source_kind=case.source_kind,
                        invoked=False,
                        non_invocation_reason=case.non_invocation_reason,
                        passed=True,
                        wall_seconds=0,
                        provider_calls=0,
                        performance=(),
                        report=None,
                        arbitration=None,
                        error=None,
                    )
                )
                continue
            sample_start = len(provider.performance_samples)
            case_started = monotonic()
            try:
                audit = pipeline.verify(case.package, review_number=1)
                arbitration = arbitrate_verifier_report(case.package, audit.report)
                samples = provider.performance_samples[sample_start:]
                expected = audit.report.verdict in case.expected_verdicts and (
                    arbitration.approved == (audit.report.verdict is VerifierVerdict.APPROVE)
                )
                results.append(
                    QualificationCaseResult(
                        name=case.name,
                        source_kind=case.source_kind,
                        invoked=True,
                        non_invocation_reason=None,
                        passed=expected,
                        wall_seconds=monotonic() - case_started,
                        provider_calls=len(samples),
                        performance=samples,
                        report=audit.report,
                        arbitration=arbitration,
                        error=None,
                    )
                )
            except (ModelProviderError, VerificationRejected, RuntimeError, ValueError) as error:
                samples = provider.performance_samples[sample_start:]
                results.append(
                    QualificationCaseResult(
                        name=case.name,
                        source_kind=case.source_kind,
                        invoked=True,
                        non_invocation_reason=None,
                        passed=False,
                        wall_seconds=monotonic() - case_started,
                        provider_calls=len(samples),
                        performance=samples,
                        report=None,
                        arbitration=None,
                        error=type(error).__name__,
                    )
                )
            finally:
                # Match production's sequential residency and avoid accumulating
                # long-lived prompt/KV state across independent qualification cases.
                try:
                    provider.unload()
                except ModelProviderError:
                    pass
    finally:
        try:
            provider.unload()
        except ModelProviderError:
            pass
    invoked = sum(item.invoked for item in results)
    passed = sum(item.passed for item in results)
    return QualificationReport(
        generated_at=datetime.now(UTC),
        model=model,
        model_digest=model_digest,
        cases=tuple(results),
        invoked_cases=invoked,
        passed_cases=passed,
        valid_structured_output_rate=(
            sum(item.report is not None for item in results if item.invoked) / invoked
        ),
        total_wall_seconds=monotonic() - started,
        passed=passed == len(results),
    )


def _output_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("qualification output path must be absolute")
    parent = path.parent
    if not parent.is_dir():
        raise argparse.ArgumentTypeError("qualification output directory is absent")
    probe = parent / f".{path.name}.write-probe"
    try:
        probe.write_text("probe", encoding="utf-8")
        probe.unlink()
    except OSError as error:
        raise argparse.ArgumentTypeError(
            "qualification output directory is not writable"
        ) from error
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--model-digest", default=DEFAULT_DIGEST)
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--output", required=True, type=_output_path)
    args = parser.parse_args()
    report = run_qualification(
        model=args.model,
        model_digest=args.model_digest,
        base_url=args.base_url,
    )
    args.output.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
