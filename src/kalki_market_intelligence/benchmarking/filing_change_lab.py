"""Shadow-only resource and fidelity comparison for Phase 42 change evidence."""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
from kalki_market_intelligence.config import Settings
from kalki_market_intelligence.contracts.common import UtcDatetime
from kalki_market_intelligence.contracts.evidence import SourceClass
from kalki_market_intelligence.forensics.filing_change import (
    FilingChangeForm,
    FilingChangeRelationship,
    FilingChangeSelectionReceipt,
    FilingChangeSnapshot,
    compare_and_select_filing_changes,
)
from kalki_market_intelligence.providers.sec.client import SecClient
from kalki_market_intelligence.providers.sec.filing_change import (
    build_snapshot_from_filing_change_extraction,
    extract_filing_change_sections,
)
from kalki_market_intelligence.radar.analysis_cache import QWEN3_4B_DIGEST
from kalki_market_intelligence.radar.contracts import SourceUrl
from kalki_market_intelligence.radar.extraction import extract_research_excerpt

FILING_CHANGE_LAB_VERSION: Literal["1.0.0"] = "1.0.0"
CURRENT_ROLES = (AnalystRole.CATALYST_ANALYST, AnalystRole.BULL_BEAR_RISK_ANALYST)
_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d[\d,]*(?:\.\d+)?%?")


@dataclass(frozen=True, slots=True)
class _GenuineBenchmarkCase:
    case: str
    cik: str
    previous_accession: str
    previous_form: FilingChangeForm
    previous_document: str
    previous_accepted_at: datetime
    previous_source_sha256: str
    current_accession: str
    current_form: FilingChangeForm
    current_document: str
    current_accepted_at: datetime
    current_source_sha256: str
    baseline_required_fragments: tuple[str, ...]
    delta_required_fragments: tuple[str, ...]


_GENUINE_BENCHMARK_CASES = (
    _GenuineBenchmarkCase(
        case="kazia-prospectus-expansion",
        cik="1075880",
        previous_accession="0001213900-26-094600",
        previous_form=FilingChangeForm.FORM_424_B_5,
        previous_document="ea0303789-424b5_kazia.htm",
        previous_accepted_at=datetime(2026, 8, 28, 10, 8, 23, tzinfo=UTC),
        previous_source_sha256=("8b76cae442d93e1b36fe6132065e588a9a55d2e78bbc9560832e0f50e8e5bc93"),
        current_accession="0001213900-26-095303",
        current_form=FilingChangeForm.FORM_424_B_5,
        current_document="ea0303882-424b5_kazia.htm",
        current_accepted_at=datetime(2026, 8, 31, 10, 9, 18, tzinfo=UTC),
        current_source_sha256=("798912e5b1bcab82503c85b752bc8d8196b03660f3395541b931fc9bc2d70032"),
        baseline_required_fragments=("2,064,000 Subject to the terms",),
        delta_required_fragments=("$37 million", "$40 million"),
    ),
)


class FilingChangeLabStrategy(StrEnum):
    ACCEPTED_BASELINE = "accepted_baseline"
    FILING_CHANGE_DELTA = "filing_change_delta"


class FilingChangeLabDecision(StrEnum):
    RETAIN_DETERMINISTIC_ONLY = "retain_deterministic_only"
    INSUFFICIENT_SUBSTANTIVE_COMPARISON = "insufficient_substantive_comparison"
    ELIGIBLE_FOR_GUARDED_REVIEW = "eligible_for_guarded_review"


class InstrumentedProvider(Protocol):
    @property
    def performance_samples(self) -> tuple[OllamaPerformanceSample, ...]: ...

    def generate(self, request: ModelRequest) -> ModelResponse: ...


class FilingChangeLabEvidence(BaseModel):
    """One source-bound evidence record retained only in the ignored input package."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence_id: UUID
    accession_number: str = Field(pattern=r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
    source_url: SourceUrl
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    filed_at: UtcDatetime
    available_at: UtcDatetime
    retrieved_at: UtcDatetime
    text: str = Field(min_length=1, max_length=3_600)
    text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def evidence_reconciles(self) -> FilingChangeLabEvidence:
        if self.available_at < self.filed_at or self.retrieved_at < self.available_at:
            raise ValueError("filing-change lab source chronology is invalid")
        if sha256(self.text.encode()).hexdigest() != self.text_sha256:
            raise ValueError("filing-change lab evidence hash does not reconcile")
        expected_id = uuid5(
            NAMESPACE_URL,
            f"kalki:filing-change-lab-evidence:{self.accession_number}:{self.text_sha256}",
        )
        if self.evidence_id != expected_id:
            raise ValueError("filing-change lab evidence identity does not reconcile")
        return self


class FilingChangeLabPackage(BaseModel):
    """One frozen strategy over the same authoritative filing-change relationship."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    package_id: UUID
    case: str = Field(min_length=1, max_length=100)
    strategy: FilingChangeLabStrategy
    relationship: FilingChangeRelationship
    cik: str = Field(pattern=r"^[0-9]{1,10}$")
    previous_accession_number: str = Field(pattern=r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
    current_accession_number: str = Field(pattern=r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
    previous_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_source_characters: int = Field(gt=0, le=3_600)
    model_evidence_characters: int = Field(gt=0, le=3_700)
    estimated_evidence_tokens: int = Field(gt=0, le=100_000)
    evidence: tuple[FilingChangeLabEvidence, ...] = Field(min_length=1, max_length=2)
    required_fragments: tuple[str, ...] = Field(min_length=1, max_length=8)
    required_fragments_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    package_version: Literal["1.0.0"] = FILING_CHANGE_LAB_VERSION

    @model_validator(mode="after")
    def package_reconciles(self) -> FilingChangeLabPackage:
        if self.previous_accession_number == self.current_accession_number:
            raise ValueError("filing-change lab package requires distinct accessions")
        if len({item.accession_number for item in self.evidence}) != len(self.evidence):
            raise ValueError("filing-change lab evidence accessions must be unique")
        expected_accessions = (
            self.previous_accession_number,
            self.current_accession_number,
        )
        actual_accessions = tuple(item.accession_number for item in self.evidence)
        if actual_accessions != tuple(
            accession for accession in expected_accessions if accession in actual_accessions
        ):
            raise ValueError("filing-change lab evidence order or accession is invalid")
        expected_characters = sum(len(item.text) for item in self.evidence)
        if self.model_evidence_characters != expected_characters:
            raise ValueError("filing-change lab evidence characters do not reconcile")
        if self.strategy is FilingChangeLabStrategy.ACCEPTED_BASELINE:
            if actual_accessions != (self.current_accession_number,):
                raise ValueError("accepted baseline must contain only current filing evidence")
            if self.selected_source_characters != self.model_evidence_characters:
                raise ValueError("accepted baseline character counts do not reconcile")
        elif self.selected_source_characters > self.model_evidence_characters:
            raise ValueError("filing-change delta character counts do not reconcile")
        source_hashes = {
            self.previous_accession_number: self.previous_source_sha256,
            self.current_accession_number: self.current_source_sha256,
        }
        for item in self.evidence:
            if item.source_sha256 != source_hashes[item.accession_number]:
                raise ValueError("filing-change lab evidence source hash does not reconcile")
            expected_path = f"/Archives/edgar/data/{int(self.cik)}/"
            if expected_path not in item.source_url:
                raise ValueError("filing-change lab evidence source CIK does not reconcile")
            nested_accession = f"/{item.accession_number.replace('-', '')}/"
            flat_submission = f"/{item.accession_number}.txt"
            if nested_accession not in item.source_url and not item.source_url.endswith(
                flat_submission
            ):
                raise ValueError("filing-change lab evidence source accession does not reconcile")
        if self.estimated_evidence_tokens != (expected_characters + 3) // 4:
            raise ValueError("filing-change lab token estimate does not reconcile")
        expected_manifest = _evidence_manifest_sha256(self.evidence)
        if self.evidence_manifest_sha256 != expected_manifest:
            raise ValueError("filing-change lab evidence manifest does not reconcile")
        all_text = "\n".join(item.text for item in self.evidence)
        if any(fragment not in all_text for fragment in self.required_fragments):
            raise ValueError("filing-change lab required fragment is absent from evidence")
        expected_fragment_hash = _fragment_manifest_sha256(self.required_fragments)
        if self.required_fragments_sha256 != expected_fragment_hash:
            raise ValueError("filing-change lab required-fragment manifest does not reconcile")
        expected_id = _package_id(
            case=self.case,
            strategy=self.strategy,
            relationship=self.relationship,
            cik=self.cik,
            previous_accession_number=self.previous_accession_number,
            current_accession_number=self.current_accession_number,
            previous_manifest_sha256=self.previous_manifest_sha256,
            current_manifest_sha256=self.current_manifest_sha256,
            previous_source_sha256=self.previous_source_sha256,
            current_source_sha256=self.current_source_sha256,
            selection_sha256=self.selection_sha256,
            evidence_manifest_sha256=self.evidence_manifest_sha256,
            required_fragments_sha256=self.required_fragments_sha256,
        )
        if self.package_id != expected_id:
            raise ValueError("filing-change lab package identity does not reconcile")
        return self


class FilingChangeLabPackageSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    prepared_at: UtcDatetime
    packages: tuple[FilingChangeLabPackage, ...] = Field(min_length=2, max_length=12)
    schema_version: Literal["1.0.0"] = FILING_CHANGE_LAB_VERSION

    @model_validator(mode="after")
    def package_set_reconciles(self) -> FilingChangeLabPackageSet:
        if len({item.package_id for item in self.packages}) != len(self.packages):
            raise ValueError("filing-change lab package identities must be unique")
        grouped: dict[str, set[FilingChangeLabStrategy]] = {}
        packages_by_case: dict[str, list[FilingChangeLabPackage]] = {}
        for package in self.packages:
            grouped.setdefault(package.case, set()).add(package.strategy)
            packages_by_case.setdefault(package.case, []).append(package)
        expected = set(FilingChangeLabStrategy)
        if any(strategies != expected for strategies in grouped.values()):
            raise ValueError("each filing-change lab case requires both strategies")
        for case_packages in packages_by_case.values():
            if len(case_packages) != len(expected):
                raise ValueError("each filing-change lab case requires exactly one strategy pair")
            identities = {
                (
                    item.relationship,
                    item.cik,
                    item.previous_accession_number,
                    item.current_accession_number,
                    item.previous_manifest_sha256,
                    item.current_manifest_sha256,
                    item.previous_source_sha256,
                    item.current_source_sha256,
                    item.selection_sha256,
                )
                for item in case_packages
            }
            if len(identities) != 1:
                raise ValueError("filing-change lab strategy pair lineage does not reconcile")
        latest_retrieval = max(
            evidence.retrieved_at for package in self.packages for evidence in package.evidence
        )
        if self.prepared_at < latest_retrieval:
            raise ValueError("filing-change package preparation precedes source retrieval")
        return self


class FilingChangeLabRunRecord(BaseModel):
    """Content-free performance and deterministic-validation result."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    package_id: UUID
    case: str
    strategy: FilingChangeLabStrategy
    relationship: FilingChangeRelationship
    current_accession_number: str
    selection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_source_characters: int = Field(gt=0, le=3_600)
    model_evidence_characters: int = Field(gt=0, le=3_700)
    estimated_evidence_tokens: int = Field(gt=0)
    requested_call_count: Literal[2] = 2
    completed_call_count: int = Field(ge=0, le=2)
    accepted_contract_count: int = Field(ge=0, le=2)
    all_required_contracts_accepted: bool
    bounded_failures: tuple[str, ...] = Field(max_length=2)
    timeout_count: int = Field(ge=0, le=2)
    wall_seconds: float = Field(ge=0)
    provider_seconds: float | None = Field(default=None, ge=0)
    actual_prompt_tokens: int | None = Field(default=None, ge=0)
    generated_tokens: int | None = Field(default=None, ge=0)
    finding_count: int = Field(ge=0, le=24)
    citation_count: int = Field(ge=0, le=96)
    numeric_token_count: int = Field(ge=0, le=192)
    inspected_fragment_fidelity_passed: bool
    required_fragment_sha256s: tuple[str, ...] = Field(min_length=1, max_length=8)
    report_version: Literal["1.0.0"] = FILING_CHANGE_LAB_VERSION

    @model_validator(mode="after")
    def run_reconciles(self) -> FilingChangeLabRunRecord:
        if self.completed_call_count < self.accepted_contract_count:
            raise ValueError("accepted calls cannot exceed completed filing-change lab calls")
        if self.all_required_contracts_accepted != (self.accepted_contract_count == 2):
            raise ValueError("filing-change lab acceptance summary does not reconcile")
        if bool(self.bounded_failures) == self.all_required_contracts_accepted:
            raise ValueError("filing-change failures and acceptance are inconsistent")
        expected_timeouts = sum("TimeoutError" in item for item in self.bounded_failures)
        if self.timeout_count != expected_timeouts:
            raise ValueError("filing-change timeout count does not reconcile")
        return self


class FilingChangeLabComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    case: str
    accepted_baseline: FilingChangeLabRunRecord
    filing_change_delta: FilingChangeLabRunRecord
    contract_non_regression: bool
    finding_count_non_regression: bool
    citation_count_non_regression: bool
    numeric_count_non_regression: bool
    inspected_fragment_fidelity_non_regression: bool
    substantive_reference_available: bool
    model_evidence_character_ratio: float
    actual_prompt_token_ratio: float | None
    wall_latency_ratio: float | None


def build_filing_change_lab_packages(
    *,
    case: str,
    previous: FilingChangeSnapshot,
    current: FilingChangeSnapshot,
    selection: FilingChangeSelectionReceipt,
    current_body: bytes,
    baseline_required_fragments: tuple[str, ...],
    delta_required_fragments: tuple[str, ...],
) -> tuple[FilingChangeLabPackage, FilingChangeLabPackage]:
    """Freeze the accepted current excerpt and exact two-source Phase 42 delta."""

    if selection.previous_manifest_sha256 != previous.manifest_sha256:
        raise ValueError("filing-change lab prior manifest does not reconcile")
    if selection.current_manifest_sha256 != current.manifest_sha256:
        raise ValueError("filing-change lab current manifest does not reconcile")
    if sha256(current_body).hexdigest() != current.source_content_sha256:
        raise ValueError("filing-change lab current source hash does not reconcile")
    baseline_text = extract_research_excerpt(current_body).text
    if not baseline_text:
        raise ValueError("accepted baseline produced no filing-change lab evidence")
    baseline_evidence = (_evidence_record(current, baseline_text),)
    baseline = _build_package(
        case=case,
        strategy=FilingChangeLabStrategy.ACCEPTED_BASELINE,
        previous=previous,
        current=current,
        selection=selection,
        evidence=baseline_evidence,
        selected_source_characters=len(baseline_text),
        required_fragments=baseline_required_fragments,
    )

    previous_text = _selection_side_text(selection, previous=True)
    current_text = _selection_side_text(selection, previous=False)
    delta_evidence = tuple(
        record
        for record in (
            _evidence_record(previous, previous_text) if previous_text else None,
            _evidence_record(current, current_text) if current_text else None,
        )
        if record is not None
    )
    if not delta_evidence:
        raise ValueError("filing-change lab selection has no bounded delta evidence")
    delta = _build_package(
        case=case,
        strategy=FilingChangeLabStrategy.FILING_CHANGE_DELTA,
        previous=previous,
        current=current,
        selection=selection,
        evidence=delta_evidence,
        selected_source_characters=selection.selected_characters,
        required_fragments=delta_required_fragments,
    )
    return baseline, delta


def prepare_genuine_filing_change_packages(settings: Settings) -> FilingChangeLabPackageSet:
    """Fetch and freeze the hash-anchored genuine SEC comparison packages."""

    if settings.sec_user_agent is None:
        raise ValueError("KALKI_SEC_USER_AGENT is required for genuine package preparation")
    client = SecClient(
        user_agent=settings.sec_user_agent,
        requests_per_second=settings.sec_requests_per_second,
        timeout_seconds=settings.sec_timeout_seconds,
        maximum_response_bytes=settings.sec_maximum_response_bytes,
    )
    packages: list[FilingChangeLabPackage] = []
    for case in _GENUINE_BENCHMARK_CASES:
        previous_document = client.fetch_primary_html_document(
            cik=case.cik,
            accession_number=case.previous_accession,
            document_name=case.previous_document,
        )
        current_document = client.fetch_primary_html_document(
            cik=case.cik,
            accession_number=case.current_accession,
            document_name=case.current_document,
        )
        if previous_document.content_sha256 != case.previous_source_sha256:
            raise ValueError("genuine prior filing-change source hash changed")
        if current_document.content_sha256 != case.current_source_sha256:
            raise ValueError("genuine current filing-change source hash changed")
        previous_extraction = extract_filing_change_sections(
            previous_document.body,
            filing_form=case.previous_form,
        )
        current_extraction = extract_filing_change_sections(
            current_document.body,
            filing_form=case.current_form,
        )
        previous = build_snapshot_from_filing_change_extraction(
            previous_extraction,
            accession_number=case.previous_accession,
            cik=case.cik,
            filed_at=case.previous_accepted_at.replace(hour=0, minute=0, second=0),
            available_at=case.previous_accepted_at,
            retrieved_at=previous_document.retrieved_at,
            source_url=previous_document.url,
        )
        current = build_snapshot_from_filing_change_extraction(
            current_extraction,
            accession_number=case.current_accession,
            cik=case.cik,
            filed_at=case.current_accepted_at.replace(hour=0, minute=0, second=0),
            available_at=case.current_accepted_at,
            retrieved_at=current_document.retrieved_at,
            source_url=current_document.url,
        )
        selection = compare_and_select_filing_changes(
            previous,
            current,
            relationship=FilingChangeRelationship.PROSPECTUS_UPDATE,
        )
        packages.extend(
            build_filing_change_lab_packages(
                case=case.case,
                previous=previous,
                current=current,
                selection=selection,
                current_body=current_document.body,
                baseline_required_fragments=case.baseline_required_fragments,
                delta_required_fragments=case.delta_required_fragments,
            )
        )
    return FilingChangeLabPackageSet(
        prepared_at=datetime.now(UTC),
        packages=tuple(packages),
    )


def execute_filing_change_package(
    provider: InstrumentedProvider,
    package: FilingChangeLabPackage,
) -> FilingChangeLabRunRecord:
    """Run the unchanged two-role validator path once per role."""

    pipeline = AnalystPipeline(provider, maximum_attempts=1)
    evidence = tuple(_analyst_evidence(package, item) for item in package.evidence)
    knowledge_cutoff = max(item.retrieved_at for item in package.evidence)
    sample_start = len(provider.performance_samples)
    started = time.monotonic()
    findings: list[AnalystFinding] = []
    failures: list[str] = []
    completed = 0
    accepted = 0
    for role in CURRENT_ROLES:
        try:
            analysis = pipeline.analyze(
                role=role,
                evidence=evidence,
                knowledge_cutoff_at=knowledge_cutoff,
            )
        except Exception as error:
            failures.append(_bounded_failure(error))
            break
        completed += 1
        accepted += 1
        findings.extend(analysis.report.findings)
    samples = provider.performance_samples[sample_start:]
    completed = max(completed, len(samples))
    provider_seconds, prompt_tokens, generated_tokens = _sample_totals(samples)
    return FilingChangeLabRunRecord(
        package_id=package.package_id,
        case=package.case,
        strategy=package.strategy,
        relationship=package.relationship,
        current_accession_number=package.current_accession_number,
        selection_sha256=package.selection_sha256,
        evidence_manifest_sha256=package.evidence_manifest_sha256,
        selected_source_characters=package.selected_source_characters,
        model_evidence_characters=package.model_evidence_characters,
        estimated_evidence_tokens=package.estimated_evidence_tokens,
        completed_call_count=completed,
        accepted_contract_count=accepted,
        all_required_contracts_accepted=accepted == 2,
        bounded_failures=tuple(failures),
        timeout_count=sum("TimeoutError" in item for item in failures),
        wall_seconds=round(time.monotonic() - started, 3),
        provider_seconds=provider_seconds,
        actual_prompt_tokens=prompt_tokens,
        generated_tokens=generated_tokens,
        finding_count=len(findings),
        citation_count=sum(len(item.citations) for item in findings),
        numeric_token_count=sum(len(_NUMBER_PATTERN.findall(item.statement)) for item in findings),
        inspected_fragment_fidelity_passed=all(
            fragment in "\n".join(item.text for item in package.evidence)
            for fragment in package.required_fragments
        ),
        required_fragment_sha256s=tuple(
            sha256(fragment.encode()).hexdigest() for fragment in package.required_fragments
        ),
    )


def compare_filing_change_runs(
    baseline: FilingChangeLabRunRecord,
    delta: FilingChangeLabRunRecord,
) -> FilingChangeLabComparison:
    if baseline.case != delta.case or baseline.selection_sha256 != delta.selection_sha256:
        raise ValueError("filing-change lab comparison requires one exact case")
    if baseline.strategy is not FilingChangeLabStrategy.ACCEPTED_BASELINE:
        raise ValueError("filing-change lab comparison baseline strategy is invalid")
    if delta.strategy is not FilingChangeLabStrategy.FILING_CHANGE_DELTA:
        raise ValueError("filing-change lab comparison delta strategy is invalid")
    prompt_ratio = _ratio(delta.actual_prompt_tokens, baseline.actual_prompt_tokens)
    wall_ratio = _ratio(delta.wall_seconds, baseline.wall_seconds)
    return FilingChangeLabComparison(
        case=baseline.case,
        accepted_baseline=baseline,
        filing_change_delta=delta,
        contract_non_regression=(
            baseline.all_required_contracts_accepted and delta.all_required_contracts_accepted
        ),
        finding_count_non_regression=delta.finding_count >= baseline.finding_count,
        citation_count_non_regression=delta.citation_count >= baseline.citation_count,
        numeric_count_non_regression=delta.numeric_token_count >= baseline.numeric_token_count,
        inspected_fragment_fidelity_non_regression=(
            baseline.inspected_fragment_fidelity_passed and delta.inspected_fragment_fidelity_passed
        ),
        substantive_reference_available=baseline.finding_count > 0,
        model_evidence_character_ratio=round(
            delta.model_evidence_characters / baseline.model_evidence_characters, 4
        ),
        actual_prompt_token_ratio=round(prompt_ratio, 4) if prompt_ratio is not None else None,
        wall_latency_ratio=round(wall_ratio, 4) if wall_ratio is not None else None,
    )


def summarize_filing_change_comparisons(
    comparisons: Sequence[FilingChangeLabComparison],
) -> dict[str, object]:
    rows = tuple(comparisons)
    if not rows:
        raise ValueError("filing-change lab summary requires at least one comparison")
    quality_gate = all(
        item.contract_non_regression
        and item.finding_count_non_regression
        and item.citation_count_non_regression
        and item.numeric_count_non_regression
        and item.inspected_fragment_fidelity_non_regression
        for item in rows
    )
    substantive = any(item.substantive_reference_available for item in rows)
    baseline_seconds = sum(item.accepted_baseline.wall_seconds for item in rows)
    delta_seconds = sum(item.filing_change_delta.wall_seconds for item in rows)
    latency_ratio = delta_seconds / baseline_seconds if baseline_seconds else None
    baseline_model_characters = sum(
        item.accepted_baseline.model_evidence_characters for item in rows
    )
    delta_model_characters = sum(
        item.filing_change_delta.model_evidence_characters for item in rows
    )
    baseline_estimated_tokens = sum(
        item.accepted_baseline.estimated_evidence_tokens for item in rows
    )
    delta_estimated_tokens = sum(
        item.filing_change_delta.estimated_evidence_tokens for item in rows
    )
    baseline_actual_tokens = _optional_sum(
        item.accepted_baseline.actual_prompt_tokens for item in rows
    )
    delta_actual_tokens = _optional_sum(
        item.filing_change_delta.actual_prompt_tokens for item in rows
    )
    if quality_gate and substantive and latency_ratio is not None and latency_ratio <= 1.2:
        decision = FilingChangeLabDecision.ELIGIBLE_FOR_GUARDED_REVIEW
    elif not substantive:
        decision = FilingChangeLabDecision.INSUFFICIENT_SUBSTANTIVE_COMPARISON
    else:
        decision = FilingChangeLabDecision.RETAIN_DETERMINISTIC_ONLY
    return {
        "sample_count": len(rows),
        "sample_label": "small_n" if len(rows) < 30 else "observed",
        "quality_non_regression_gate": quality_gate,
        "substantive_reference_available": substantive,
        "decision": decision.value,
        "baseline_total_calls": sum(item.accepted_baseline.completed_call_count for item in rows),
        "delta_total_calls": sum(item.filing_change_delta.completed_call_count for item in rows),
        "baseline_model_evidence_characters": baseline_model_characters,
        "delta_model_evidence_characters": delta_model_characters,
        "delta_to_baseline_character_ratio": round(
            delta_model_characters / baseline_model_characters, 4
        ),
        "baseline_estimated_evidence_tokens": baseline_estimated_tokens,
        "delta_estimated_evidence_tokens": delta_estimated_tokens,
        "baseline_actual_prompt_tokens": baseline_actual_tokens,
        "delta_actual_prompt_tokens": delta_actual_tokens,
        "delta_to_baseline_actual_prompt_token_ratio": (
            round(delta_actual_tokens / baseline_actual_tokens, 4)
            if baseline_actual_tokens not in {None, 0} and delta_actual_tokens is not None
            else None
        ),
        "baseline_total_seconds": round(baseline_seconds, 3),
        "delta_total_seconds": round(delta_seconds, 3),
        "delta_to_baseline_latency_ratio": (
            round(latency_ratio, 4) if latency_ratio is not None else None
        ),
        "baseline_median_seconds": round(
            statistics.median(item.accepted_baseline.wall_seconds for item in rows), 3
        ),
        "delta_median_seconds": round(
            statistics.median(item.filing_change_delta.wall_seconds for item in rows), 3
        ),
        "baseline_timeouts": sum(item.accepted_baseline.timeout_count for item in rows),
        "delta_timeouts": sum(item.filing_change_delta.timeout_count for item in rows),
    }


def _selection_side_text(selection: FilingChangeSelectionReceipt, *, previous: bool) -> str:
    values = (
        item.previous_text if previous else item.current_text
        for item in selection.selected_excerpts
    )
    return "\n\n[…]\n\n".join(value for value in values if value)


def _evidence_record(snapshot: FilingChangeSnapshot, text: str) -> FilingChangeLabEvidence:
    text_sha256 = sha256(text.encode()).hexdigest()
    return FilingChangeLabEvidence(
        evidence_id=uuid5(
            NAMESPACE_URL,
            f"kalki:filing-change-lab-evidence:{snapshot.accession_number}:{text_sha256}",
        ),
        accession_number=snapshot.accession_number,
        source_url=snapshot.source_url,
        source_sha256=snapshot.source_content_sha256,
        filed_at=snapshot.filed_at,
        available_at=snapshot.available_at,
        retrieved_at=snapshot.retrieved_at,
        text=text,
        text_sha256=text_sha256,
    )


def _build_package(
    *,
    case: str,
    strategy: FilingChangeLabStrategy,
    previous: FilingChangeSnapshot,
    current: FilingChangeSnapshot,
    selection: FilingChangeSelectionReceipt,
    evidence: tuple[FilingChangeLabEvidence, ...],
    selected_source_characters: int,
    required_fragments: tuple[str, ...],
) -> FilingChangeLabPackage:
    manifest_sha256 = _evidence_manifest_sha256(evidence)
    fragment_manifest_sha256 = _fragment_manifest_sha256(required_fragments)
    package_id = _package_id(
        case=case,
        strategy=strategy,
        relationship=selection.relationship,
        cik=current.cik,
        previous_accession_number=previous.accession_number,
        current_accession_number=current.accession_number,
        previous_manifest_sha256=previous.manifest_sha256,
        current_manifest_sha256=current.manifest_sha256,
        previous_source_sha256=previous.source_content_sha256,
        current_source_sha256=current.source_content_sha256,
        selection_sha256=selection.selection_sha256,
        evidence_manifest_sha256=manifest_sha256,
        required_fragments_sha256=fragment_manifest_sha256,
    )
    model_characters = sum(len(item.text) for item in evidence)
    return FilingChangeLabPackage(
        package_id=package_id,
        case=case,
        strategy=strategy,
        relationship=selection.relationship,
        cik=current.cik,
        previous_accession_number=previous.accession_number,
        current_accession_number=current.accession_number,
        previous_manifest_sha256=previous.manifest_sha256,
        current_manifest_sha256=current.manifest_sha256,
        previous_source_sha256=previous.source_content_sha256,
        current_source_sha256=current.source_content_sha256,
        selection_sha256=selection.selection_sha256,
        evidence_manifest_sha256=manifest_sha256,
        selected_source_characters=selected_source_characters,
        model_evidence_characters=model_characters,
        estimated_evidence_tokens=(model_characters + 3) // 4,
        evidence=evidence,
        required_fragments=required_fragments,
        required_fragments_sha256=fragment_manifest_sha256,
    )


def _package_id(
    *,
    case: str,
    strategy: FilingChangeLabStrategy,
    relationship: FilingChangeRelationship,
    cik: str,
    previous_accession_number: str,
    current_accession_number: str,
    previous_manifest_sha256: str,
    current_manifest_sha256: str,
    previous_source_sha256: str,
    current_source_sha256: str,
    selection_sha256: str,
    evidence_manifest_sha256: str,
    required_fragments_sha256: str,
) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        ":".join(
            (
                "kalki-filing-change-lab",
                FILING_CHANGE_LAB_VERSION,
                case,
                strategy.value,
                relationship.value,
                cik,
                previous_accession_number,
                current_accession_number,
                previous_manifest_sha256,
                current_manifest_sha256,
                previous_source_sha256,
                current_source_sha256,
                selection_sha256,
                evidence_manifest_sha256,
                required_fragments_sha256,
            )
        ),
    )


def _evidence_manifest_sha256(evidence: tuple[FilingChangeLabEvidence, ...]) -> str:
    payload = [
        {
            "evidence_id": str(item.evidence_id),
            "accession_number": item.accession_number,
            "source_url": item.source_url,
            "source_sha256": item.source_sha256,
            "filed_at": item.filed_at.isoformat(),
            "available_at": item.available_at.isoformat(),
            "retrieved_at": item.retrieved_at.isoformat(),
            "text_sha256": item.text_sha256,
            "text_characters": len(item.text),
        }
        for item in evidence
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _fragment_manifest_sha256(fragments: tuple[str, ...]) -> str:
    encoded = json.dumps(fragments, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _analyst_evidence(
    package: FilingChangeLabPackage, item: FilingChangeLabEvidence
) -> AnalystEvidence:
    return AnalystEvidence(
        evidence_id=item.evidence_id,
        subject_id=uuid5(NAMESPACE_URL, f"sec-cik:{package.cik}"),
        source_id=uuid5(NAMESPACE_URL, item.source_url),
        source_class=SourceClass.SEC,
        publisher="U.S. Securities and Exchange Commission",
        locator=item.source_url,
        text=item.text,
        content_sha256=item.text_sha256,
        published_at=item.filed_at,
        available_at=item.available_at,
        retrieved_at=item.retrieved_at,
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


def _ratio(numerator: int | float | None, denominator: int | float | None) -> float | None:
    if numerator is None or denominator in {None, 0}:
        return None
    return numerator / denominator


def _optional_sum(values: Iterable[int | None]) -> int | None:
    items = tuple(values)
    if any(item is None for item in items):
        return None
    return sum(item for item in items if item is not None)


def _load_packages(path: Path) -> FilingChangeLabPackageSet:
    return FilingChangeLabPackageSet.model_validate_json(path.read_text(encoding="utf-8"))


def _write_json_exclusive(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as target:
        json.dump(value, target, indent=2)
        target.write("\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--packages", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url")
    parser.add_argument("--model", default="qwen3:4b")
    parser.add_argument("--expected-digest", default=QWEN3_4B_DIGEST)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--case", action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.prepare:
            if arguments.packages is not None or arguments.base_url is not None:
                raise ValueError("package preparation does not accept run-only arguments")
            package_set = prepare_genuine_filing_change_packages(Settings())
            _write_json_exclusive(
                arguments.output,
                package_set.model_dump(mode="json"),
            )
            print(
                json.dumps(
                    {
                        "prepared_packages": len(package_set.packages),
                        "cases": len({item.case for item in package_set.packages}),
                    },
                    indent=2,
                )
            )
            return 0
        if arguments.packages is None or arguments.base_url is None:
            raise ValueError("benchmark execution requires --packages and --base-url")
        package_set = _load_packages(arguments.packages)
        selected = tuple(
            item
            for item in package_set.packages
            if not arguments.case or item.case in arguments.case
        )
        grouped: dict[str, dict[FilingChangeLabStrategy, FilingChangeLabPackage]] = {}
        for package in selected:
            grouped.setdefault(package.case, {})[package.strategy] = package
        if not grouped or any(len(items) != 2 for items in grouped.values()):
            raise ValueError("filing-change benchmark selection requires complete strategy pairs")
        provider = OllamaModelProvider(
            model=arguments.model,
            base_url=arguments.base_url,
            timeout_seconds=arguments.timeout,
            expected_digest=arguments.expected_digest,
        )
        comparisons: list[FilingChangeLabComparison] = []
        try:
            for index, case in enumerate(sorted(grouped)):
                packages = grouped[case]
                baseline_package = packages[FilingChangeLabStrategy.ACCEPTED_BASELINE]
                delta_package = packages[FilingChangeLabStrategy.FILING_CHANGE_DELTA]
                if index % 2 == 0:
                    baseline = execute_filing_change_package(provider, baseline_package)
                    delta = execute_filing_change_package(provider, delta_package)
                else:
                    delta = execute_filing_change_package(provider, delta_package)
                    baseline = execute_filing_change_package(provider, baseline_package)
                comparisons.append(compare_filing_change_runs(baseline, delta))
        finally:
            provider.unload()
        summary = summarize_filing_change_comparisons(comparisons)
        report = {
            "schema_version": FILING_CHANGE_LAB_VERSION,
            "generated_at": datetime.now(UTC).isoformat(),
            "package_set_sha256": sha256(arguments.packages.read_bytes()).hexdigest(),
            "model": arguments.model,
            "model_digest": arguments.expected_digest,
            "provider": "ollama",
            "context_tokens": 4_096,
            "maximum_output_tokens": 768,
            "maximum_attempts_per_call": 1,
            "concurrent_inference": False,
            "gemma_enabled": False,
            "worker_integration": False,
            "execution_order": "alternating_strategy_first_by_case",
            "summary": summary,
            "comparisons": [item.model_dump(mode="json") for item in comparisons],
            "limitations": [
                "This is a small engineering sample and is not market-performance evidence.",
                "Reports retain hashes, counts and performance only; source text, prompts, model "
                "responses, findings and hidden reasoning remain absent.",
                "The accepted baseline and filing-change strategies share the same filing pair "
                "but intentionally contain different bounded evidence.",
                "Count non-regression cannot establish semantic equivalence without substantive "
                "validated findings.",
                "The benchmark cannot configure or deploy a worker, model, publication or alert.",
            ],
        }
        _write_json_exclusive(arguments.output, report)
        print(json.dumps(summary, indent=2))
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print(f"filing-change lab failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
