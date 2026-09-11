"""Tests for the deterministic Ollama benchmark harness."""

import pytest

from kalki_market_intelligence.benchmarking.cases import (
    BENCHMARK_CASES,
    ContractEventAnswer,
)
from kalki_market_intelligence.benchmarking.ollama import (
    BenchmarkRecord,
    build_payload,
    score_response,
    summarize,
    validate_base_url,
)


def test_benchmark_cases_cover_three_qualitative_roles() -> None:
    assert {case.name for case in BENCHMARK_CASES} == {
        "contract_event_extraction",
        "contradiction_detection",
        "risk_classification",
    }


def test_payload_enforces_schema_and_determinism() -> None:
    payload = build_payload(BENCHMARK_CASES[0], "example:latest")

    assert payload["model"] == "example:latest"
    assert payload["stream"] is False
    assert payload["think"] is False
    assert payload["format"] == ContractEventAnswer.model_json_schema()
    assert payload["options"] == {
        "temperature": 0,
        "seed": 42,
        "num_ctx": 2048,
        "num_predict": 256,
    }


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("http://127.0.0.1:11434/", "http://127.0.0.1:11434"),
        ("http://localhost:11434", "http://localhost:11434"),
        ("http://[::1]:11434", "http://[::1]:11434"),
    ],
)
def test_base_url_accepts_only_loopback_origins(base_url: str, expected: str) -> None:
    assert validate_base_url(base_url) == expected


@pytest.mark.parametrize(
    "base_url",
    [
        "https://127.0.0.1:11434",
        "http://example.com:11434",
        "http://127.0.0.1:11434/api",
        "http://user:password@127.0.0.1:11434",
        "http://127.0.0.1:not-a-port",
    ],
)
def test_base_url_rejects_nonlocal_or_ambiguous_origins(base_url: str) -> None:
    with pytest.raises(ValueError, match="Ollama base URL"):
        validate_base_url(base_url)


def test_scoring_is_deterministic() -> None:
    case = BENCHMARK_CASES[0]
    answer = ContractEventAnswer.model_validate(case.expected)

    assert score_response(answer, case.expected) == (6, 6)


def record(*, case: str, output: dict[str, object], seconds: float = 4.0) -> BenchmarkRecord:
    return BenchmarkRecord(
        case=case,
        repeat=1,
        schema_valid=True,
        checks_passed=4,
        checks_total=4,
        wall_seconds=seconds,
        ollama_seconds_excluding_load=seconds,
        load_seconds=0.0,
        prompt_tokens=10,
        generated_tokens=8,
        eval_tokens_per_second=2.0,
        parsed_output=output,
        error=None,
    )


def test_summary_passes_stable_accurate_runs() -> None:
    records = [
        record(case="a", output={"value": 1}),
        record(case="a", output={"value": 1}),
        record(case="b", output={"value": 2}),
        record(case="b", output={"value": 2}),
    ]

    summary = summarize(records, maximum_median_seconds=10.0)

    assert summary.passed is True
    assert summary.schema_valid_rate == 1.0
    assert summary.assertion_accuracy == 1.0
    assert summary.deterministic_case_rate == 1.0


def test_summary_rejects_nondeterministic_outputs() -> None:
    records = [
        record(case="a", output={"value": 1}),
        record(case="a", output={"value": 2}),
    ]

    summary = summarize(records, maximum_median_seconds=10.0)

    assert summary.passed is False
    assert summary.deterministic_case_rate == 0.0
