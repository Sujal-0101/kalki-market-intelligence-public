"""Run deterministic, schema-constrained benchmarks against a local Ollama server."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, ValidationError

from kalki_market_intelligence.benchmarking.cases import BENCHMARK_CASES, BenchmarkCase
from kalki_market_intelligence.contracts.common import ContractModel

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen3:4b"
SYSTEM_PROMPT = (
    "You are evaluating synthetic market-research text. Use only facts in the supplied "
    "text, never add outside facts, and return exactly the requested schema."
)


class OllamaMessage(BaseModel):
    """Subset of an Ollama response message used by the benchmark."""

    model_config = ConfigDict(extra="ignore")
    content: str


class OllamaChatResponse(BaseModel):
    """Validated subset of Ollama's non-streaming chat response."""

    model_config = ConfigDict(extra="ignore")
    message: OllamaMessage
    total_duration: int = 0
    load_duration: int = 0
    prompt_eval_count: int = 0
    prompt_eval_duration: int = 0
    eval_count: int = 0
    eval_duration: int = 0


class BenchmarkRecord(BaseModel):
    """One case execution with validation, scoring, and timing data."""

    case: str
    repeat: int
    schema_valid: bool
    checks_passed: int
    checks_total: int
    wall_seconds: float
    ollama_seconds_excluding_load: float | None
    load_seconds: float | None
    prompt_tokens: int | None
    generated_tokens: int | None
    eval_tokens_per_second: float | None
    parsed_output: dict[str, object] | None
    error: str | None


class BenchmarkSummary(BaseModel):
    """Aggregate benchmark gates."""

    runs: int
    schema_valid_rate: float
    assertion_accuracy: float
    deterministic_case_rate: float
    median_seconds_excluding_load: float
    median_eval_tokens_per_second: float
    errors: int
    passed: bool


def build_payload(case: BenchmarkCase, model: str) -> dict[str, object]:
    """Build a deterministic local-only structured-output request."""

    return {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": case.prompt},
        ],
        "stream": False,
        "think": False,
        "format": case.response_model.model_json_schema(),
        "keep_alive": "10m",
        "options": {
            "temperature": 0,
            "seed": 42,
            "num_ctx": 2048,
            "num_predict": 256,
        },
    }


def score_response(
    response: ContractModel,
    expected: Mapping[str, object],
) -> tuple[int, int]:
    """Compare schema-validated output with deterministic expected values."""

    values = response.model_dump(mode="json")
    passed = sum(values.get(field) == expected_value for field, expected_value in expected.items())
    return passed, len(expected)


def _request_json(
    method: str,
    url: str,
    *,
    payload: Mapping[str, object] | None = None,
    timeout: float,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(  # noqa: S310 - URL is validated as a loopback origin by the caller
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - loopback URL is explicit
        decoded: object = json.loads(response.read().decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("Ollama returned a non-object JSON response")
    return cast(dict[str, Any], decoded)


def _seconds(nanoseconds: int) -> float:
    return nanoseconds / 1_000_000_000


def validate_base_url(base_url: str) -> str:
    """Accept only an uncredentialed loopback HTTP Ollama endpoint."""

    normalized = base_url.rstrip("/")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path
    ):
        raise ValueError("Ollama base URL must be an uncredentialed loopback HTTP origin")
    try:
        _ = parsed.port
    except ValueError as error:
        raise ValueError("Ollama base URL has an invalid port") from error
    return normalized


def _execute_case(
    case: BenchmarkCase,
    *,
    repeat: int,
    base_url: str,
    model: str,
    timeout: float,
) -> BenchmarkRecord:
    started = time.perf_counter()
    try:
        raw_response = _request_json(
            "POST",
            f"{base_url}/api/chat",
            payload=build_payload(case, model),
            timeout=timeout,
        )
        response = OllamaChatResponse.model_validate(raw_response)
        parsed = case.response_model.model_validate_json(response.message.content)
        checks_passed, checks_total = score_response(parsed, case.expected)
        eval_rate = (
            response.eval_count / _seconds(response.eval_duration)
            if response.eval_count and response.eval_duration
            else None
        )
        return BenchmarkRecord(
            case=case.name,
            repeat=repeat,
            schema_valid=True,
            checks_passed=checks_passed,
            checks_total=checks_total,
            wall_seconds=time.perf_counter() - started,
            ollama_seconds_excluding_load=_seconds(
                max(0, response.total_duration - response.load_duration)
            ),
            load_seconds=_seconds(response.load_duration),
            prompt_tokens=response.prompt_eval_count,
            generated_tokens=response.eval_count,
            eval_tokens_per_second=eval_rate,
            parsed_output=parsed.model_dump(mode="json"),
            error=None,
        )
    except (HTTPError, URLError, TimeoutError, ValueError, ValidationError) as error:
        return BenchmarkRecord(
            case=case.name,
            repeat=repeat,
            schema_valid=False,
            checks_passed=0,
            checks_total=len(case.expected),
            wall_seconds=time.perf_counter() - started,
            ollama_seconds_excluding_load=None,
            load_seconds=None,
            prompt_tokens=None,
            generated_tokens=None,
            eval_tokens_per_second=None,
            parsed_output=None,
            error=f"{type(error).__name__}: {error}",
        )


def summarize(
    records: Sequence[BenchmarkRecord],
    *,
    maximum_median_seconds: float,
) -> BenchmarkSummary:
    """Aggregate quality, stability, latency, and failure gates."""

    if not records:
        raise ValueError("at least one benchmark record is required")
    total_checks = sum(record.checks_total for record in records)
    valid_records = [record for record in records if record.schema_valid]
    durations = [
        record.ollama_seconds_excluding_load
        for record in records
        if record.ollama_seconds_excluding_load is not None
    ]
    eval_rates = [
        record.eval_tokens_per_second
        for record in records
        if record.eval_tokens_per_second is not None
    ]
    grouped_outputs: dict[str, set[str]] = {}
    for record in valid_records:
        serialized = json.dumps(record.parsed_output, sort_keys=True)
        grouped_outputs.setdefault(record.case, set()).add(serialized)
    case_names = {record.case for record in records}
    deterministic_cases = sum(len(grouped_outputs.get(name, set())) == 1 for name in case_names)
    schema_rate = len(valid_records) / len(records)
    assertion_accuracy = sum(record.checks_passed for record in records) / total_checks
    deterministic_rate = deterministic_cases / len(case_names)
    median_seconds = statistics.median(durations) if durations else float("inf")
    median_eval_rate = statistics.median(eval_rates) if eval_rates else 0.0
    errors = sum(record.error is not None for record in records)
    passed = (
        schema_rate == 1.0
        and assertion_accuracy >= 0.90
        and deterministic_rate == 1.0
        and median_seconds <= maximum_median_seconds
        and errors == 0
    )
    return BenchmarkSummary(
        runs=len(records),
        schema_valid_rate=schema_rate,
        assertion_accuracy=assertion_accuracy,
        deterministic_case_rate=deterministic_rate,
        median_seconds_excluding_load=median_seconds,
        median_eval_tokens_per_second=median_eval_rate,
        errors=errors,
        passed=passed,
    )


def _model_metadata(base_url: str, model: str, timeout: float) -> dict[str, object]:
    version = _request_json("GET", f"{base_url}/api/version", timeout=timeout)
    tags = _request_json("GET", f"{base_url}/api/tags", timeout=timeout)
    models = tags.get("models", [])
    selected = next(
        (item for item in models if isinstance(item, dict) and item.get("name") == model),
        None,
    )
    if selected is None:
        raise ValueError(f"model {model!r} is not installed")
    return {
        "ollama_version": version.get("version"),
        "model": model,
        "model_digest": selected.get("digest"),
        "model_size_bytes": selected.get("size"),
        "model_details": selected.get("details"),
    }


def run_benchmark(
    *,
    base_url: str,
    model: str,
    repeats: int,
    timeout: float,
    maximum_median_seconds: float,
) -> dict[str, object]:
    """Run the complete benchmark and return a serializable report."""

    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    base_url = validate_base_url(base_url)
    metadata = _model_metadata(base_url, model, timeout)
    records = [
        _execute_case(
            case,
            repeat=repeat,
            base_url=base_url,
            model=model,
            timeout=timeout,
        )
        for repeat in range(1, repeats + 1)
        for case in BENCHMARK_CASES
    ]
    summary = summarize(records, maximum_median_seconds=maximum_median_seconds)
    return {
        "created_at": datetime.now(UTC).isoformat(),
        **metadata,
        "thresholds": {
            "schema_valid_rate": 1.0,
            "assertion_accuracy": 0.90,
            "deterministic_case_rate": 1.0,
            "maximum_median_seconds_excluding_load": maximum_median_seconds,
            "errors": 0,
        },
        "summary": summary.model_dump(mode="json"),
        "records": [record.model_dump(mode="json") for record in records],
    }


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--maximum-median-seconds", type=float, default=60.0)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""

    args = _parse_args(argv)
    try:
        report = run_benchmark(
            base_url=args.base_url,
            model=args.model,
            repeats=args.repeats,
            timeout=args.timeout,
            maximum_median_seconds=args.maximum_median_seconds,
        )
    except (HTTPError, URLError, TimeoutError, ValueError) as error:
        print(f"benchmark setup failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    summary = cast(dict[str, object], report["summary"])
    return 0 if summary.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
