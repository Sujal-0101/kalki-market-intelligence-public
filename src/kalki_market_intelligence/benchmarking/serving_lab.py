"""Prepare and replay identical genuine SEC packages across private model runtimes."""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal, Protocol, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kalki_market_intelligence.analysis.contracts import (
    AnalystEvidence,
    AnalystRole,
    ModelRequest,
    ModelResponse,
)
from kalki_market_intelligence.analysis.llama_cpp import LlamaCppModelProvider
from kalki_market_intelligence.analysis.ollama import (
    OllamaModelProvider,
    OllamaPerformanceSample,
)
from kalki_market_intelligence.analysis.pipeline import AnalysisRejected, AnalystPipeline
from kalki_market_intelligence.benchmarking.serving_cases import SERVING_BENCHMARK_CASES
from kalki_market_intelligence.config import Settings
from kalki_market_intelligence.contracts.evidence import SourceClass
from kalki_market_intelligence.radar.extraction import (
    extract_form_aware_research_excerpt,
    extract_research_excerpt,
)
from kalki_market_intelligence.radar.sec_source import SecRadarClient

PACKAGE_SCHEMA_VERSION = "1.0.0"
REPORT_SCHEMA_VERSION = "1.0.0"
Strategy = Literal["accepted_baseline", "form_aware"]
Placement = Literal["cpu", "vulkan", "cuda"]


class InstrumentedProvider(Protocol):
    @property
    def performance_samples(self) -> tuple[OllamaPerformanceSample, ...]: ...

    def generate(self, request: ModelRequest) -> ModelResponse: ...


class ServingEvidencePackage(BaseModel):
    """One frozen, bounded model input with authoritative source lineage."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    package_id: UUID
    case: str = Field(min_length=1, max_length=100)
    strategy: Strategy
    accession: str = Field(pattern=r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
    cik: str = Field(pattern=r"^[0-9]{1,10}$")
    company: str = Field(min_length=1, max_length=255)
    form: str = Field(min_length=1, max_length=20)
    source_url: str = Field(min_length=1, max_length=2_048)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_filed_at: datetime
    source_retrieved_at: datetime
    role: AnalystRole
    evidence_text: str = Field(min_length=1, max_length=3_600)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    required_fragments: tuple[str, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def provenance_and_content_reconcile(self) -> ServingEvidencePackage:
        if self.source_filed_at.tzinfo is None or self.source_filed_at.utcoffset() is None:
            raise ValueError("source filed time must be timezone-aware")
        if self.source_retrieved_at.tzinfo is None or self.source_retrieved_at.utcoffset() is None:
            raise ValueError("source retrieval time must be timezone-aware")
        if self.source_retrieved_at < self.source_filed_at:
            raise ValueError("source retrieval cannot precede filing")
        if sha256(self.evidence_text.encode("utf-8")).hexdigest() != self.evidence_sha256:
            raise ValueError("serving package evidence hash does not reconcile")
        expected_id = uuid5(
            NAMESPACE_URL,
            ":".join(
                (
                    "kalki-serving-package",
                    PACKAGE_SCHEMA_VERSION,
                    self.accession,
                    self.strategy,
                    self.role.value,
                    self.evidence_sha256,
                )
            ),
        )
        if self.package_id != expected_id:
            raise ValueError("serving package identity does not reconcile")
        return self


class ServingPackageSet(BaseModel):
    """Frozen package collection prepared once and replayed unchanged."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0.0"] = "1.0.0"
    prepared_at: datetime
    packages: tuple[ServingEvidencePackage, ...] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def packages_are_unique(self) -> ServingPackageSet:
        if self.prepared_at.tzinfo is None or self.prepared_at.utcoffset() is None:
            raise ValueError("package-set preparation time must be timezone-aware")
        identities = [item.package_id for item in self.packages]
        if len(set(identities)) != len(identities):
            raise ValueError("serving package identities must be unique")
        return self


class ServingRunRecord(BaseModel):
    """Content-free quality and performance result for one frozen package."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    package_id: UUID
    case: str
    strategy: Strategy
    accession: str
    form: str
    role: AnalystRole
    source_sha256: str
    evidence_sha256: str
    evidence_characters: int
    actual_prompt_tokens: int | None
    generated_tokens: int | None
    prompt_tokens_per_second: float | None
    generated_tokens_per_second: float | None
    provider_seconds: float | None
    wall_seconds: float
    contract_accepted: bool
    assessment: str | None
    finding_count: int
    inspected_fragment_fidelity_passed: bool
    required_fragment_sha256s: tuple[str, ...]
    bounded_failure: str | None


def _filed_at(body: bytes) -> datetime:
    match = re.search(rb"(?m)^FILED AS OF DATE:\s*([0-9]{8})\s*$", body)
    if match is None:
        raise ValueError("SEC complete submission omitted FILED AS OF DATE")
    return datetime.strptime(match.group(1).decode("ascii"), "%Y%m%d").replace(tzinfo=UTC)


def prepare_packages(settings: Settings) -> ServingPackageSet:
    """Fetch each source once and freeze both deterministic evidence strategies."""

    if settings.sec_user_agent is None:
        raise ValueError("KALKI_SEC_USER_AGENT is required for genuine SEC package preparation")
    client = SecRadarClient(
        user_agent=settings.sec_user_agent,
        requests_per_second=settings.sec_requests_per_second,
        timeout_seconds=settings.sec_timeout_seconds,
        maximum_response_bytes=settings.sec_maximum_response_bytes,
    )
    packages: list[ServingEvidencePackage] = []
    for case in SERVING_BENCHMARK_CASES:
        document = client.filing(case["url"])
        if document.content_sha256 != case["source_sha256"]:
            raise ValueError(f"immutable SEC source hash changed for {case['accession']}")
        filed_at = _filed_at(document.body)
        baseline = extract_research_excerpt(document.body)
        form_aware = extract_form_aware_research_excerpt(
            document.body,
            filing_form=case["form"],
        )
        strategies: tuple[tuple[Strategy, str], ...] = (
            ("accepted_baseline", baseline.text),
            ("form_aware", form_aware.text),
        )
        for strategy, text in strategies:
            evidence_sha256 = sha256(text.encode("utf-8")).hexdigest()
            package_id = uuid5(
                NAMESPACE_URL,
                ":".join(
                    (
                        "kalki-serving-package",
                        PACKAGE_SCHEMA_VERSION,
                        case["accession"],
                        strategy,
                        case["role"].value,
                        evidence_sha256,
                    )
                ),
            )
            packages.append(
                ServingEvidencePackage(
                    package_id=package_id,
                    case=case["name"],
                    strategy=strategy,
                    accession=case["accession"],
                    cik=case["cik"],
                    company=case["company"],
                    form=case["form"],
                    source_url=case["url"],
                    source_sha256=document.content_sha256,
                    source_filed_at=filed_at,
                    source_retrieved_at=document.retrieved_at,
                    role=case["role"],
                    evidence_text=text,
                    evidence_sha256=evidence_sha256,
                    required_fragments=case["required_fragments"],
                )
            )
    return ServingPackageSet(prepared_at=datetime.now(UTC), packages=tuple(packages))


def _evidence(package: ServingEvidencePackage) -> AnalystEvidence:
    return AnalystEvidence(
        evidence_id=uuid5(NAMESPACE_URL, f"serving-lab-evidence:{package.package_id}"),
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


def execute_package(
    provider: InstrumentedProvider,
    package: ServingEvidencePackage,
) -> ServingRunRecord:
    """Execute one attempt and retain no prompt, evidence, output, or hidden reasoning."""

    pipeline = AnalystPipeline(provider, maximum_attempts=1)
    sample_count = len(provider.performance_samples)
    started = time.monotonic()
    accepted = False
    assessment: str | None = None
    finding_count = 0
    failure: str | None = None
    try:
        analysis = pipeline.analyze(
            role=package.role,
            evidence=(_evidence(package),),
            knowledge_cutoff_at=package.source_retrieved_at,
        )
        accepted = True
        assessment = analysis.report.assessment.value
        finding_count = len(analysis.report.findings)
    except AnalysisRejected as error:
        failure = ",".join(error.error_codes)
    except Exception as error:
        failure = type(error.__cause__).__name__ if error.__cause__ else type(error).__name__
    wall_seconds = time.monotonic() - started
    sample = (
        provider.performance_samples[-1]
        if len(provider.performance_samples) > sample_count
        else None
    )
    return ServingRunRecord(
        package_id=package.package_id,
        case=package.case,
        strategy=package.strategy,
        accession=package.accession,
        form=package.form,
        role=package.role,
        source_sha256=package.source_sha256,
        evidence_sha256=package.evidence_sha256,
        evidence_characters=len(package.evidence_text),
        actual_prompt_tokens=sample.prompt_tokens if sample else None,
        generated_tokens=sample.generated_tokens if sample else None,
        prompt_tokens_per_second=sample.prompt_tokens_per_second if sample else None,
        generated_tokens_per_second=sample.generated_tokens_per_second if sample else None,
        provider_seconds=sample.total_seconds if sample else None,
        wall_seconds=round(wall_seconds, 3),
        contract_accepted=accepted,
        assessment=assessment,
        finding_count=finding_count,
        inspected_fragment_fidelity_passed=all(
            fragment in package.evidence_text for fragment in package.required_fragments
        ),
        required_fragment_sha256s=tuple(
            sha256(fragment.encode("utf-8")).hexdigest() for fragment in package.required_fragments
        ),
        bounded_failure=failure,
    )


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * fraction)


def summarize_records(records: tuple[ServingRunRecord, ...]) -> dict[str, object]:
    if not records:
        raise ValueError("at least one serving-lab record is required")
    latencies = [item.wall_seconds for item in records]
    return {
        "runs": len(records),
        "sample_label": "small_n" if len(records) < 30 else "sufficient_n",
        "contract_accepted": sum(item.contract_accepted for item in records),
        "contract_acceptance_rate": sum(item.contract_accepted for item in records) / len(records),
        "timeouts": sum(item.bounded_failure == "TimeoutError" for item in records),
        "inspected_fragment_fidelity_rate": sum(
            item.inspected_fragment_fidelity_passed for item in records
        )
        / len(records),
        "latency_seconds": {
            "minimum": min(latencies),
            "p50": statistics.median(latencies),
            "p90": _percentile(latencies, 0.90),
            "p95": _percentile(latencies, 0.95),
            "maximum": max(latencies),
        },
    }


def _load_packages(path: Path) -> ServingPackageSet:
    return ServingPackageSet.model_validate_json(path.read_text(encoding="utf-8"))


def _provider(arguments: argparse.Namespace) -> InstrumentedProvider:
    if arguments.provider == "ollama":
        return OllamaModelProvider(
            model=arguments.model,
            base_url=arguments.base_url,
            timeout_seconds=arguments.timeout,
            expected_digest=arguments.expected_digest,
            keep_alive="10m",
        )
    if arguments.system_fingerprint is None or arguments.server_model is None:
        raise ValueError("llama.cpp runs require server model and system fingerprint")
    return LlamaCppModelProvider(
        logical_model=arguments.model,
        server_model=arguments.server_model,
        model_blob_sha256=arguments.expected_digest,
        expected_system_fingerprint=arguments.system_fingerprint,
        base_url=arguments.base_url,
        timeout_seconds=arguments.timeout,
    )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as target:
        json.dump(value, target, indent=2)
        target.write("\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--output", type=Path, required=True)

    run = subparsers.add_parser("run")
    run.add_argument("--packages", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--provider", choices=("ollama", "llama.cpp"), required=True)
    run.add_argument("--base-url", required=True)
    run.add_argument("--model", default="qwen3:4b")
    run.add_argument("--expected-digest", required=True)
    run.add_argument("--server-model")
    run.add_argument("--system-fingerprint")
    run.add_argument("--runtime-image-digest", required=True)
    run.add_argument("--placement", choices=("cpu", "vulkan", "cuda"), required=True)
    run.add_argument("--threads", type=int, choices=range(1, 9), required=True)
    run.add_argument(
        "--strategy",
        choices=("accepted_baseline", "form_aware"),
        default="form_aware",
    )
    run.add_argument("--case", action="append", default=[])
    run.add_argument("--timeout", type=float, default=300)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "prepare":
            packages = prepare_packages(Settings())
            _write_json(arguments.output, packages.model_dump(mode="json"))
            print(f"prepared {len(packages.packages)} frozen packages")
            return 0
        package_set = _load_packages(arguments.packages)
        selected = tuple(
            package
            for package in package_set.packages
            if package.strategy == arguments.strategy
            and (not arguments.case or package.case in arguments.case)
        )
        if not selected:
            raise ValueError("serving-lab selection contains no packages")
        provider = _provider(arguments)
        records = tuple(execute_package(provider, package) for package in selected)
        if isinstance(provider, OllamaModelProvider):
            provider.unload()
        report = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "generated_at": datetime.now(UTC).isoformat(),
            "package_schema_version": package_set.schema_version,
            "package_prepared_at": package_set.prepared_at.isoformat(),
            "provider": arguments.provider,
            "model": arguments.model,
            "model_or_blob_digest": arguments.expected_digest,
            "runtime_image_digest": arguments.runtime_image_digest,
            "system_fingerprint": arguments.system_fingerprint,
            "placement": cast(Placement, arguments.placement),
            "threads": arguments.threads,
            "context_tokens": 4_096,
            "maximum_output_tokens": 768,
            "concurrent_inference": False,
            "gemma_enabled": False,
            "summary": summarize_records(records),
            "records": [item.model_dump(mode="json") for item in records],
            "limitations": [
                "This is a small engineering sample, not market or model-accuracy evidence.",
                "Package text remains only in the ignored input file; reports retain hashes "
                "and metrics.",
                "The llama.cpp adapter discards reasoning content and fails closed unless "
                "final content "
                "passes the unchanged analyst schema, evidence, numeric and provenance validators.",
                "Resource and public-service observations are collected separately by the isolated "
                "runtime harness and must not be inferred from provider timing fields.",
            ],
        }
        _write_json(arguments.output, report)
        print(json.dumps(report["summary"], indent=2))
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print(f"model-serving lab failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
