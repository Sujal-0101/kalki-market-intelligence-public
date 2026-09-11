"""Tests for frozen, identical model-serving benchmark packages."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

import pytest
from pydantic import ValidationError

from kalki_market_intelligence.analysis.contracts import AnalystRole
from kalki_market_intelligence.benchmarking.serving_lab import (
    PACKAGE_SCHEMA_VERSION,
    ServingEvidencePackage,
    ServingRunRecord,
    summarize_records,
)


def package() -> ServingEvidencePackage:
    text = "The filing reports exactly $10 million in proceeds."
    digest = sha256(text.encode()).hexdigest()
    package_id = uuid5(
        NAMESPACE_URL,
        ":".join(
            (
                "kalki-serving-package",
                PACKAGE_SCHEMA_VERSION,
                "0000000001-26-000001",
                "accepted_baseline",
                AnalystRole.CATALYST_ANALYST.value,
                digest,
            )
        ),
    )
    return ServingEvidencePackage(
        package_id=package_id,
        case="synthetic-contract-test",
        strategy="accepted_baseline",
        accession="0000000001-26-000001",
        cik="1",
        company="SYNTHETIC TEST ISSUER",
        form="8-K",
        source_url="https://www.sec.gov/Archives/edgar/data/1/test.txt",
        source_sha256="a" * 64,
        source_filed_at=datetime(2026, 8, 1, tzinfo=UTC),
        source_retrieved_at=datetime(2026, 8, 2, tzinfo=UTC),
        role=AnalystRole.CATALYST_ANALYST,
        evidence_text=text,
        evidence_sha256=digest,
        required_fragments=("exactly $10 million",),
    )


def record(*, seconds: float, accepted: bool = True) -> ServingRunRecord:
    item = package()
    return ServingRunRecord(
        package_id=item.package_id,
        case=item.case,
        strategy=item.strategy,
        accession=item.accession,
        form=item.form,
        role=item.role,
        source_sha256=item.source_sha256,
        evidence_sha256=item.evidence_sha256,
        evidence_characters=len(item.evidence_text),
        actual_prompt_tokens=100,
        generated_tokens=20,
        prompt_tokens_per_second=10,
        generated_tokens_per_second=5,
        provider_seconds=seconds,
        wall_seconds=seconds,
        contract_accepted=accepted,
        assessment="evidence_sufficient" if accepted else None,
        finding_count=1 if accepted else 0,
        inspected_fragment_fidelity_passed=True,
        required_fragment_sha256s=(sha256(b"exactly $10 million").hexdigest(),),
        bounded_failure=None if accepted else "malformed_json",
    )


def test_package_reconciles_identity_hash_and_retains_fidelity_reference() -> None:
    item = package()

    assert item.evidence_sha256 == sha256(item.evidence_text.encode()).hexdigest()
    assert item.required_fragments[0] in item.evidence_text


def test_package_can_truthfully_retain_a_missing_fragment_for_fidelity_measurement() -> None:
    item = package().model_dump()
    item["required_fragments"] = ("not retained by this strategy",)

    validated = ServingEvidencePackage.model_validate(item)

    assert validated.required_fragments[0] not in validated.evidence_text


def test_package_rejects_content_mutation() -> None:
    with pytest.raises(ValidationError, match="evidence hash does not reconcile"):
        package().model_copy(
            update={"evidence_text": "mutated"}, deep=True
        ).__class__.model_validate({**package().model_dump(), "evidence_text": "mutated"})


def test_summary_labels_small_samples_and_reports_interpolated_percentiles() -> None:
    summary = summarize_records((record(seconds=10), record(seconds=20, accepted=False)))

    assert summary["sample_label"] == "small_n"
    assert summary["contract_acceptance_rate"] == 0.5
    assert summary["latency_seconds"] == {
        "minimum": 10.0,
        "p50": 15.0,
        "p90": 19.0,
        "p95": 19.5,
        "maximum": 20.0,
    }
