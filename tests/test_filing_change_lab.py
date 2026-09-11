"""Content-free Phase 42 filing-change benchmark tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from pydantic import ValidationError

from kalki_market_intelligence.analysis.contracts import (
    AnalystReport,
    AnalystRole,
    Assessment,
    ModelRequest,
    ModelResponse,
)
from kalki_market_intelligence.analysis.ollama import OllamaPerformanceSample
from kalki_market_intelligence.benchmarking.filing_change_lab import (
    FilingChangeLabDecision,
    FilingChangeLabPackage,
    FilingChangeLabPackageSet,
    FilingChangeLabStrategy,
    build_filing_change_lab_packages,
    compare_filing_change_runs,
    execute_filing_change_package,
    summarize_filing_change_comparisons,
)
from kalki_market_intelligence.forensics.filing_change import (
    FilingChangeForm,
    FilingChangeRelationship,
    FilingChangeSnapshot,
    build_filing_change_snapshot,
    compare_and_select_filing_changes,
)
from kalki_market_intelligence.providers.sec.filing_change import (
    extract_filing_change_sections,
)

NOW = datetime(2026, 8, 31, 10, tzinfo=UTC)
PREVIOUS_BODY = b"""
<body>RISK FACTORS The issuer depends on one supplier and may face disruption.
DILUTION The prior offering described 100,000 shares and a price of $2.00 per share.
</body>
"""
CURRENT_BODY = b"""
<body>RISK FACTORS The issuer depends on two suppliers and may face disruption.
DILUTION The current offering describes 200,000 shares and a price of $1.50 per share.
USE OF PROCEEDS The issuer states proceeds would support working capital and research.
</body>
"""


class InstrumentedSequenceProvider:
    def __init__(self, responses: tuple[str, ...]) -> None:
        self._responses = iter(responses)
        self.requests: list[ModelRequest] = []
        self._samples: list[OllamaPerformanceSample] = []

    @property
    def performance_samples(self) -> tuple[OllamaPerformanceSample, ...]:
        return tuple(self._samples)

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        self._samples.append(
            OllamaPerformanceSample(
                total_seconds=1.0,
                load_seconds=0.0,
                prompt_tokens=100,
                generated_tokens=20,
                prompt_tokens_per_second=100.0,
                generated_tokens_per_second=20.0,
            )
        )
        return ModelResponse(
            provider_name="deterministic-sequence",
            model_name="fixture-model",
            model_digest="a" * 64,
            content=next(self._responses),
            prompt_tokens=100,
            generated_tokens=20,
        )


def _report(role: AnalystRole) -> str:
    return AnalystReport(
        prompt_version="analyst-v2",
        role=role,
        assessment=Assessment.INSUFFICIENT_EVIDENCE,
        findings=(),
        contradictions=(),
        limitations=(),
    ).model_dump_json()


def _snapshot(body: bytes, *, accession: str, accepted_at: datetime) -> FilingChangeSnapshot:
    extraction = extract_filing_change_sections(body, filing_form=FilingChangeForm.FORM_424_B_5)
    return build_filing_change_snapshot(
        accession_number=accession,
        cik="1075880",
        filing_form=FilingChangeForm.FORM_424_B_5,
        filed_at=accepted_at,
        available_at=accepted_at,
        retrieved_at=accepted_at + timedelta(minutes=1),
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/1075880/"
            f"{accession.replace('-', '')}/filing.htm"
        ),
        source_content_sha256=extraction.source_content_sha256,
        normalized_visible_sha256=extraction.normalized_visible_sha256,
        sections=extraction.sections,
    )


def _packages(
    current_body: bytes = CURRENT_BODY,
) -> tuple[FilingChangeLabPackage, FilingChangeLabPackage]:
    previous = _snapshot(
        PREVIOUS_BODY,
        accession="0001213900-26-000001",
        accepted_at=NOW,
    )
    current = _snapshot(
        current_body,
        accession="0001213900-26-000002",
        accepted_at=NOW + timedelta(hours=1),
    )
    selection = compare_and_select_filing_changes(
        previous,
        current,
        relationship=FilingChangeRelationship.PROSPECTUS_UPDATE,
    )
    return build_filing_change_lab_packages(
        case="synthetic-prospectus-change",
        previous=previous,
        current=current,
        selection=selection,
        current_body=current_body,
        baseline_required_fragments=("200,000 shares", "$1.50"),
        delta_required_fragments=("100,000 shares", "200,000 shares"),
    )


def test_builder_preserves_two_source_delta_and_accepted_baseline() -> None:
    baseline, delta = _packages()

    assert baseline.strategy is FilingChangeLabStrategy.ACCEPTED_BASELINE
    assert len(baseline.evidence) == 1
    assert baseline.evidence[0].accession_number == "0001213900-26-000002"
    assert delta.strategy is FilingChangeLabStrategy.FILING_CHANGE_DELTA
    assert [item.accession_number for item in delta.evidence] == [
        "0001213900-26-000001",
        "0001213900-26-000002",
    ]
    assert delta.selected_source_characters <= 3_600
    assert delta.model_evidence_characters == sum(len(item.text) for item in delta.evidence)
    assert delta.estimated_evidence_tokens == (delta.model_evidence_characters + 3) // 4
    assert sha256(delta.evidence[0].text.encode()).hexdigest() == delta.evidence[0].text_sha256


def test_both_strategies_use_the_unchanged_two_role_validator_path() -> None:
    baseline_package, delta_package = _packages()
    responses = (
        _report(AnalystRole.CATALYST_ANALYST),
        _report(AnalystRole.BULL_BEAR_RISK_ANALYST),
    )
    baseline_provider = InstrumentedSequenceProvider(responses)
    delta_provider = InstrumentedSequenceProvider(responses)

    baseline = execute_filing_change_package(baseline_provider, baseline_package)
    delta = execute_filing_change_package(delta_provider, delta_package)
    comparison = compare_filing_change_runs(baseline, delta)
    summary = summarize_filing_change_comparisons((comparison,))

    assert len(baseline_provider.requests) == 2
    assert len(delta_provider.requests) == 2
    assert baseline.all_required_contracts_accepted
    assert delta.all_required_contracts_accepted
    assert baseline.actual_prompt_tokens == 200
    assert delta.actual_prompt_tokens == 200
    assert comparison.contract_non_regression
    assert comparison.inspected_fragment_fidelity_non_regression
    assert summary["decision"] == FilingChangeLabDecision.INSUFFICIENT_SUBSTANTIVE_COMPARISON.value


def test_package_set_requires_complete_pairs_and_records_exclude_content() -> None:
    baseline_package, delta_package = _packages()
    package_set = FilingChangeLabPackageSet(
        prepared_at=NOW + timedelta(hours=2),
        packages=(baseline_package, delta_package),
    )
    assert len(package_set.packages) == 2

    with pytest.raises(ValidationError, match="identities must be unique"):
        FilingChangeLabPackageSet(
            prepared_at=NOW + timedelta(hours=2),
            packages=(baseline_package, baseline_package),
        )
    tampered_delta = delta_package.model_copy(update={"selection_sha256": "a" * 64})
    with pytest.raises(ValidationError, match="package identity"):
        FilingChangeLabPackageSet(
            prepared_at=NOW + timedelta(hours=2),
            packages=(baseline_package, tampered_delta),
        )

    extra_baseline, _ = _packages(CURRENT_BODY.replace(b"two suppliers", b"three suppliers"))
    with pytest.raises(ValidationError, match="exactly one strategy pair"):
        FilingChangeLabPackageSet(
            prepared_at=NOW + timedelta(hours=2),
            packages=(baseline_package, delta_package, extra_baseline),
        )

    with pytest.raises(ValidationError, match="precedes source retrieval"):
        FilingChangeLabPackageSet(
            prepared_at=NOW,
            packages=(baseline_package, delta_package),
        )

    provider = InstrumentedSequenceProvider(
        (
            _report(AnalystRole.CATALYST_ANALYST),
            _report(AnalystRole.BULL_BEAR_RISK_ANALYST),
        )
    )
    serialized = execute_filing_change_package(provider, delta_package).model_dump_json().casefold()
    for forbidden in (
        "100,000 shares",
        "200,000 shares",
        "system_prompt",
        "user_prompt",
        "response",
        "reasoning",
        "excerpt",
    ):
        assert forbidden.casefold() not in serialized


def test_builder_rejects_changed_current_source_bytes() -> None:
    baseline_package, _ = _packages()
    assert baseline_package.current_accession_number == "0001213900-26-000002"
    previous = _snapshot(
        PREVIOUS_BODY,
        accession="0001213900-26-000001",
        accepted_at=NOW,
    )
    current = _snapshot(
        CURRENT_BODY,
        accession="0001213900-26-000002",
        accepted_at=NOW + timedelta(hours=1),
    )
    selection = compare_and_select_filing_changes(
        previous,
        current,
        relationship=FilingChangeRelationship.PROSPECTUS_UPDATE,
    )
    with pytest.raises(ValueError, match="source hash"):
        build_filing_change_lab_packages(
            case="synthetic-prospectus-change",
            previous=previous,
            current=current,
            selection=selection,
            current_body=CURRENT_BODY + b"changed",
            baseline_required_fragments=("200,000 shares",),
            delta_required_fragments=("100,000 shares",),
        )


def test_loaded_package_reconciles_source_hash_accession_and_utc() -> None:
    baseline, _ = _packages()
    payload = baseline.model_dump(mode="json")
    payload["current_source_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="source hash"):
        FilingChangeLabPackage.model_validate(payload)

    payload = baseline.model_dump(mode="json")
    payload["evidence"][0]["source_url"] = (
        "https://www.sec.gov/Archives/edgar/data/1075880/000121390026999999/filing.htm"
    )
    with pytest.raises(ValidationError, match="source accession"):
        FilingChangeLabPackage.model_validate(payload)

    payload = baseline.model_dump(mode="json")
    payload["evidence"][0]["retrieved_at"] = "2026-08-31T11:01:00"
    with pytest.raises(ValidationError, match="timezone offset"):
        FilingChangeLabPackage.model_validate(payload)


def test_summary_reports_requested_resource_and_fidelity_totals() -> None:
    baseline_package, delta_package = _packages()
    responses = (
        _report(AnalystRole.CATALYST_ANALYST),
        _report(AnalystRole.BULL_BEAR_RISK_ANALYST),
    )
    baseline = execute_filing_change_package(
        InstrumentedSequenceProvider(responses), baseline_package
    )
    delta = execute_filing_change_package(InstrumentedSequenceProvider(responses), delta_package)
    comparison = compare_filing_change_runs(baseline, delta)
    summary = summarize_filing_change_comparisons((comparison,))

    assert comparison.finding_count_non_regression
    assert summary["baseline_model_evidence_characters"] == baseline.model_evidence_characters
    assert summary["delta_model_evidence_characters"] == delta.model_evidence_characters
    assert summary["baseline_estimated_evidence_tokens"] == baseline.estimated_evidence_tokens
    assert summary["delta_estimated_evidence_tokens"] == delta.estimated_evidence_tokens
    assert summary["baseline_actual_prompt_tokens"] == 200
    assert summary["delta_actual_prompt_tokens"] == 200
    assert summary["baseline_timeouts"] == 0
    assert summary["delta_timeouts"] == 0

    missing_finding = compare_filing_change_runs(
        baseline.model_copy(update={"finding_count": 1, "citation_count": 1}),
        delta,
    )
    assert not missing_finding.finding_count_non_regression
    assert (
        summarize_filing_change_comparisons((missing_finding,))["decision"]
        == FilingChangeLabDecision.RETAIN_DETERMINISTIC_ONLY.value
    )
