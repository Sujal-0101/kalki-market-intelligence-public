#!/usr/bin/env python3
"""Replay identical genuine SEC cases through baseline and form-aware Qwen packages."""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from time import monotonic
from uuid import NAMESPACE_URL, uuid5

from kalki_market_intelligence.analysis.contracts import AnalystEvidence
from kalki_market_intelligence.analysis.ollama import ModelProviderError, OllamaModelProvider
from kalki_market_intelligence.analysis.pipeline import AnalysisRejected, AnalystPipeline
from kalki_market_intelligence.benchmarking.serving_cases import SERVING_BENCHMARK_CASES
from kalki_market_intelligence.config import Settings
from kalki_market_intelligence.contracts.evidence import SourceClass
from kalki_market_intelligence.radar.extraction import (
    extract_form_aware_research_excerpt,
    extract_research_excerpt,
)
from kalki_market_intelligence.radar.sec_source import SecRadarClient


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default="http://ollama:11434")
    arguments = parser.parse_args()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=arguments.output.parent):
        pass
    settings = Settings()
    if settings.sec_user_agent is None:
        raise SystemExit("KALKI_SEC_USER_AGENT is required for the genuine SEC replay")
    client = SecRadarClient(
        user_agent=settings.sec_user_agent,
        requests_per_second=settings.sec_requests_per_second,
        timeout_seconds=settings.sec_timeout_seconds,
        maximum_response_bytes=settings.sec_maximum_response_bytes,
    )
    provider = OllamaModelProvider(
        model=settings.worker_model,
        base_url=arguments.base_url,
        timeout_seconds=300,
        expected_digest=settings.worker_model_digest,
    )
    pipeline = AnalystPipeline(provider, maximum_attempts=1)
    results: list[dict[str, object]] = []
    for case in SERVING_BENCHMARK_CASES:
        document = client.filing(str(case["url"]))
        if document.content_sha256 != case["source_sha256"]:
            raise SystemExit(f"immutable SEC source hash changed for {case['accession']}")
        baseline = extract_research_excerpt(document.body)
        form_aware = extract_form_aware_research_excerpt(
            document.body,
            filing_form=str(case["form"]),
        )
        missing_form_aware_fragments = tuple(
            fragment for fragment in case["required_fragments"] if fragment not in form_aware.text
        )
        if missing_form_aware_fragments:
            raise SystemExit(
                f"form-aware evidence lost required inspected facts for {case['accession']}"
            )
        for strategy, text in (
            ("accepted_baseline", baseline.text),
            ("form_aware", form_aware.text),
        ):
            evidence = AnalystEvidence(
                evidence_id=uuid5(
                    NAMESPACE_URL,
                    f"form-budget-benchmark:{case['accession']}:{strategy}",
                ),
                subject_id=uuid5(NAMESPACE_URL, f"sec-cik:{case['cik']}"),
                source_id=uuid5(NAMESPACE_URL, str(case["url"])),
                source_class=SourceClass.SEC,
                publisher="U.S. Securities and Exchange Commission",
                locator=str(case["url"]),
                text=text,
                content_sha256=sha256(text.encode()).hexdigest(),
                # The production candidate contract has only the SEC filing date.
                published_at=datetime(2026, 8, 28, tzinfo=UTC),
                available_at=document.retrieved_at,
                retrieved_at=document.retrieved_at,
            )
            before_samples = len(provider.performance_samples)
            started = monotonic()
            accepted = False
            assessment: str | None = None
            finding_count = 0
            failure: str | None = None
            try:
                analysis = pipeline.analyze(
                    role=case["role"],
                    evidence=(evidence,),
                    knowledge_cutoff_at=document.retrieved_at,
                )
                accepted = True
                assessment = analysis.report.assessment.value
                finding_count = len(analysis.report.findings)
            except AnalysisRejected as error:
                failure = ",".join(error.error_codes)
            except ModelProviderError as error:
                failure = (
                    type(error.__cause__).__name__ if error.__cause__ else type(error).__name__
                )
            elapsed = monotonic() - started
            sample = (
                provider.performance_samples[-1]
                if len(provider.performance_samples) > before_samples
                else None
            )
            receipt = form_aware.evidence_budget
            retained_fragments = tuple(
                fragment for fragment in case["required_fragments"] if fragment in text
            )
            required_numeric_tokens = tuple(
                dict.fromkeys(
                    token
                    for fragment in case["required_fragments"]
                    for token in re.findall(
                        r"(?:\$\s*)?\d[\d,.]*(?:\s*(?:million|billion))?", fragment
                    )
                )
            )
            retained_numeric_tokens = tuple(
                dict.fromkeys(
                    token
                    for fragment in retained_fragments
                    for token in re.findall(
                        r"(?:\$\s*)?\d[\d,.]*(?:\s*(?:million|billion))?", fragment
                    )
                )
            )
            results.append(
                {
                    "case": case["name"],
                    "accession": case["accession"],
                    "form": case["form"],
                    "source_url": case["url"],
                    "source_sha256": document.content_sha256,
                    "role": case["role"].value,
                    "strategy": strategy,
                    "evidence_characters": len(text),
                    "estimated_evidence_tokens": (len(text) + 3) // 4,
                    "actual_prompt_tokens": sample.prompt_tokens if sample else None,
                    "generated_tokens": sample.generated_tokens if sample else None,
                    "provider_seconds": sample.total_seconds if sample else None,
                    "wall_seconds": round(elapsed, 3),
                    "timed_out": failure == "TimeoutError",
                    "contract_accepted": accepted,
                    "accepted_findings_passed_schema_evidence_numeric_validation": accepted,
                    "assessment": assessment,
                    "finding_count": finding_count,
                    "required_inspected_fragment_count": len(case["required_fragments"]),
                    "retained_inspected_fragment_count": len(retained_fragments),
                    "inspected_fragment_fidelity_passed": len(retained_fragments)
                    == len(case["required_fragments"]),
                    "required_fragment_sha256s": [
                        sha256(fragment.encode()).hexdigest()
                        for fragment in case["required_fragments"]
                    ],
                    "required_numeric_token_count": len(required_numeric_tokens),
                    "retained_required_numeric_token_count": len(retained_numeric_tokens),
                    "required_numeric_fidelity_passed": len(retained_numeric_tokens)
                    == len(required_numeric_tokens),
                    "bounded_failure": failure,
                    "selected_document_type": (
                        receipt.selected_document_type
                        if strategy == "form_aware" and receipt
                        else None
                    ),
                    "selected_sections": (
                        [item.section_label for item in receipt.selected_windows]
                        if strategy == "form_aware" and receipt
                        else []
                    ),
                }
            )
    report = {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "model": settings.worker_model,
        "model_digest": settings.worker_model_digest,
        "context_tokens": 4096,
        "maximum_output_tokens": 768,
        "maximum_attempts_per_package": 1,
        "gemma_enabled": False,
        "concurrent_inference": False,
        "limitations": [
            "Three genuine SEC cases are an engineering sample, not market evidence.",
            "Each before/after pair uses one role and one attempt; percentiles remain unavailable.",
            "The accepted baseline runs first in each pair; the first baseline may include model "
            "load time, so latency differences alone do not establish causality.",
            "Contract acceptance can contain zero findings; finding_count prevents treating "
            "it as substantive output.",
            "Fidelity checks cover only manually selected inspected source fragments declared "
            "for these three cases; they are not an unbiased quality sample.",
            "No raw model response or unrestricted prompt is retained.",
        ],
        "results": results,
    }
    infrastructure_invalid = bool(results) and all(
        row["bounded_failure"] in {"ConnectionRefusedError", "URLError"} for row in results
    )
    report["benchmark_status"] = "INVALID_INFRASTRUCTURE" if infrastructure_invalid else "COMPLETE"
    arguments.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 2 if infrastructure_invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
