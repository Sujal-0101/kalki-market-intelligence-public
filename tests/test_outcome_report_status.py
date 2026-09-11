"""Outcome reports must expose their limited inferential basis."""

from datetime import UTC, datetime

from kalki_market_intelligence.predictions.contracts import EvaluationReport


def test_default_report_status_is_inconclusive() -> None:
    report = EvaluationReport(
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        knowledge_cutoff_at=datetime(2026, 1, 1, tzinfo=UTC),
        prediction_count=0,
        evaluated_count=0,
        unavailable_count=0,
        status_counts={},
        assessment_counts={},
        mean_asset_return=None,
        mean_benchmark_relative_return=None,
        limitations=("No observations.",),
    )
    assert report.inference_status == "inconclusive"
