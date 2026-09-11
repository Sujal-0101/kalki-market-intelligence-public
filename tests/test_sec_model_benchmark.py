"""Tests for the workload-specific local-model comparison gate."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from kalki_market_intelligence.analysis.ollama import OllamaPerformanceSample
from kalki_market_intelligence.benchmarking.sec_cases import SEC_MODEL_CASES
from kalki_market_intelligence.benchmarking.sec_models import (
    SecModelRecord,
    ensure_output_writable,
    summarize,
)


def _record(*, case: str, capability: str, output: dict[str, object]) -> SecModelRecord:
    return SecModelRecord(
        case=case,
        source_kind="synthetic_sec_style_test",
        capability=capability,
        repeat=1,
        schema_valid=True,
        post_validation_accepted=True,
        assessment_correct=True,
        required_terms_found=1,
        required_terms_total=1,
        forbidden_terms_absent=True,
        exact_quotes=1,
        citations_total=1,
        unsupported_claim_detected=False,
        numeric_fidelity=True,
        identity_correct=True,
        instruction_followed=True,
        normalized_output=output,
        validation_error_codes=(),
        wall_seconds=2.0,
        performance=OllamaPerformanceSample(
            total_seconds=2.0,
            load_seconds=0.0,
            prompt_tokens=100,
            generated_tokens=20,
            prompt_tokens_per_second=10.0,
            generated_tokens_per_second=5.0,
        ),
        model_name="test-model",
        model_digest="a" * 64,
        error=None,
    )


def test_sec_corpus_is_bounded_reproducible_and_honestly_labelled() -> None:
    assert len(SEC_MODEL_CASES) == 6
    assert sum(case.source_kind == "real_public_sec_excerpt" for case in SEC_MODEL_CASES) == 1
    assert sum(case.source_kind == "synthetic_sec_style_test" for case in SEC_MODEL_CASES) == 5
    assert {case.capability for case in SEC_MODEL_CASES} == {
        "catalyst",
        "risk",
        "identity",
        "numeric_correction",
        "uncertainty",
    }
    for case in SEC_MODEL_CASES:
        for evidence in case.evidence:
            assert sha256(evidence.text.encode("utf-8")).hexdigest() == evidence.content_sha256
            if case.source_kind == "synthetic_sec_style_test":
                assert "SYNTHETIC TEST EXCERPT" in evidence.text
            else:
                assert evidence.publisher == "U.S. Securities and Exchange Commission"
                assert evidence.published_at < evidence.available_at
                assert evidence.available_at == evidence.retrieved_at


def test_summary_requires_repeatable_grounded_outputs() -> None:
    capabilities = ("catalyst", "risk", "uncertainty")
    records = [
        _record(case=capability, capability=capability, output={"answer": capability})
        for _repeat in range(2)
        for capability in capabilities
    ]

    summary = summarize(records)

    assert summary.schema_valid_rate == 1.0
    assert summary.exact_quotation_fidelity_rate == 1.0
    assert summary.unsupported_claim_run_rate == 0.0
    assert summary.deterministic_case_rate == 1.0
    assert summary.gate_passed is True


def test_summary_exposes_unsupported_and_nondeterministic_failures() -> None:
    first = _record(case="risk", capability="risk", output={"answer": "a"})
    second = _record(case="risk", capability="risk", output={"answer": "b"}).model_copy(
        update={
            "post_validation_accepted": False,
            "unsupported_claim_detected": True,
            "validation_error_codes": ("unsupported_numeric_token",),
        }
    )

    summary = summarize((first, second))

    assert summary.post_validation_acceptance_rate == 0.5
    assert summary.unsupported_claim_run_rate == 0.5
    assert summary.deterministic_case_rate == 0.0
    assert summary.gate_passed is False


def test_benchmark_rejects_unwritable_report_before_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "report.json"

    def deny_open(*_args: object, **_kwargs: object) -> None:
        raise PermissionError("synthetic permission denial")

    monkeypatch.setattr(Path, "open", deny_open)

    with pytest.raises(PermissionError):
        ensure_output_writable(output)
