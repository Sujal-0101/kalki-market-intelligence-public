"""Closed freshness and performance measurement contract tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from kalki_market_intelligence.radar.measurements import (
    EngineeringMeasurementReceipt,
    EngineeringMetricName,
    FilingLatencyReceipt,
    FilingLatencyUnavailableReason,
    MeasurementAvailability,
    MeasurementUnavailableReason,
    accepted_metric_definitions,
    build_distribution_measurement,
    build_filing_latency_receipt,
    build_gauge_measurement,
    build_ratio_measurement,
    build_unavailable_measurement,
)

NOW = datetime(2026, 8, 31, 15, tzinfo=UTC)
START = NOW - timedelta(hours=24)
LINEAGE_ID = UUID("10000000-0000-4000-8000-000000000001")


def test_metric_catalog_covers_every_required_measure_without_duplicates() -> None:
    definitions = accepted_metric_definitions()

    assert {item.metric_name for item in definitions} == set(EngineeringMetricName)
    assert len({item.definition_sha256 for item in definitions}) == len(definitions) == 20


def test_ratio_retains_raw_counts_and_deterministic_scaled_value() -> None:
    result = build_ratio_measurement(
        metric_name=EngineeringMetricName.ANALYST_TIMEOUT_RATE,
        window_started_at=START,
        window_ended_at=NOW,
        measured_at=NOW,
        numerator=3,
        denominator=8,
    )

    assert result.sample_count == 8
    assert result.scaled_value_millionths == 375_000
    assert result.minimum_value is None

    with pytest.raises(ValidationError, match="bounded fraction"):
        EngineeringMeasurementReceipt.model_validate(
            {
                **result.model_dump(),
                "numerator": 9,
                "scaled_value_millionths": 1_125_000,
            }
        )


def test_calls_per_filing_ratio_can_exceed_one_without_becoming_a_rate() -> None:
    result = build_ratio_measurement(
        metric_name=EngineeringMetricName.QWEN_CALLS_PER_FILING,
        window_started_at=START,
        window_ended_at=NOW,
        measured_at=NOW,
        numerator=12,
        denominator=5,
    )

    assert result.scaled_value_millionths == 2_400_000
    with pytest.raises(ValueError, match="positive denominator"):
        build_ratio_measurement(
            metric_name=EngineeringMetricName.QWEN_CALLS_PER_FILING,
            window_started_at=START,
            window_ended_at=NOW,
            measured_at=NOW,
            numerator=0,
            denominator=0,
        )


def test_distribution_uses_documented_nearest_rank_and_rejects_shape_mutation() -> None:
    result = build_distribution_measurement(
        metric_name=EngineeringMetricName.ANALYST_LATENCY_MS,
        window_started_at=START,
        window_ended_at=NOW,
        measured_at=NOW,
        samples=(10, 20, 30, 40, 50, 60, 70, 80, 90, 100),
    )

    assert (
        result.minimum_value,
        result.p50_value,
        result.p90_value,
        result.p95_value,
        result.maximum_value,
    ) == (10, 50, 90, 100, 100)

    with pytest.raises(ValidationError, match="monotonic"):
        EngineeringMeasurementReceipt.model_validate({**result.model_dump(), "p50_value": 95})


def test_partial_windows_name_the_later_telemetry_epoch() -> None:
    result = build_ratio_measurement(
        metric_name=EngineeringMetricName.PUBLICATION_EXACT_ONCE_RATE,
        window_started_at=START,
        window_ended_at=NOW,
        measured_at=NOW,
        numerator=4,
        denominator=4,
        availability=MeasurementAvailability.PARTIAL,
        coverage_started_at=START + timedelta(hours=4),
    )

    assert result.availability is MeasurementAvailability.PARTIAL
    with pytest.raises(ValidationError, match="later telemetry epoch"):
        EngineeringMeasurementReceipt.model_validate(
            {**result.model_dump(), "coverage_started_at": START}
        )


def test_unavailable_metrics_carry_no_plausible_value() -> None:
    result = build_unavailable_measurement(
        metric_name=EngineeringMetricName.MATERIAL_UPDATE_RECALL,
        window_started_at=START,
        window_ended_at=NOW,
        measured_at=NOW,
        reason=MeasurementUnavailableReason.REFERENCE_LABELS_UNAVAILABLE,
    )

    assert result.sample_count == 0
    assert result.numerator is result.p50_value is result.gauge_value is None
    with pytest.raises(ValidationError, match="cannot retain a value"):
        EngineeringMeasurementReceipt.model_validate({**result.model_dump(), "gauge_value": 0})
    with pytest.raises(ValidationError, match="invalid for this metric"):
        build_unavailable_measurement(
            metric_name=EngineeringMetricName.QUEUE_DEPTH,
            window_started_at=START,
            window_ended_at=NOW,
            measured_at=NOW,
            reason=MeasurementUnavailableReason.REFERENCE_LABELS_UNAVAILABLE,
        )


def test_resource_and_queue_gauges_are_instantaneous() -> None:
    result = build_gauge_measurement(
        metric_name=EngineeringMetricName.QUEUE_DEPTH,
        observed_at=NOW,
        measured_at=NOW + timedelta(seconds=1),
        value=247,
    )

    assert result.window_started_at == result.window_ended_at == NOW
    assert result.gauge_value == 247
    with pytest.raises(ValidationError, match="instantaneous"):
        EngineeringMeasurementReceipt.model_validate(
            {**result.model_dump(), "window_started_at": START}
        )


def test_known_first_disclosure_produces_all_three_exact_latencies() -> None:
    first_known = NOW - timedelta(hours=3)
    discovered = NOW - timedelta(hours=2)
    published = NOW - timedelta(hours=1)
    alerted = published + timedelta(seconds=10)
    result = build_filing_latency_receipt(
        accession_number="0001045810-26-000073",
        event_lineage_id=LINEAGE_ID,
        authoritative_first_known_at=first_known,
        discovered_at=discovered,
        published_at=published,
        alerted_at=alerted,
        measured_at=NOW,
    )

    assert result.first_known_to_discovery.value_ms == 3_600_000
    assert result.discovery_to_publication.value_ms == 3_600_000
    assert result.first_known_to_alert.value_ms == 7_210_000


def test_unknown_first_disclosure_makes_dependent_latencies_unavailable() -> None:
    result = build_filing_latency_receipt(
        accession_number="0001045810-26-000073",
        event_lineage_id=None,
        authoritative_first_known_at=None,
        discovered_at=NOW - timedelta(hours=2),
        published_at=NOW - timedelta(hours=1),
        alerted_at=NOW - timedelta(minutes=59),
        measured_at=NOW,
    )

    assert result.first_known_to_discovery.unavailable_reason is (
        FilingLatencyUnavailableReason.AUTHORITATIVE_FIRST_KNOWN_UNAVAILABLE
    )
    assert result.first_known_to_alert.unavailable_reason is (
        FilingLatencyUnavailableReason.AUTHORITATIVE_FIRST_KNOWN_UNAVAILABLE
    )
    assert result.discovery_to_publication.value_ms == 3_600_000

    lineage_without_time = build_filing_latency_receipt(
        accession_number="0001045810-26-000073",
        event_lineage_id=LINEAGE_ID,
        authoritative_first_known_at=None,
        discovered_at=NOW - timedelta(hours=2),
        published_at=None,
        alerted_at=None,
        measured_at=NOW,
    )
    assert lineage_without_time.event_lineage_id == LINEAGE_ID
    assert lineage_without_time.first_known_to_discovery.value_ms is None


def test_unpublished_filing_never_receives_invented_publication_or_alert_latency() -> None:
    result = build_filing_latency_receipt(
        accession_number="0001045810-26-000073",
        event_lineage_id=LINEAGE_ID,
        authoritative_first_known_at=NOW - timedelta(hours=3),
        discovered_at=NOW - timedelta(hours=2),
        published_at=None,
        alerted_at=None,
        measured_at=NOW,
    )

    assert result.discovery_to_publication.unavailable_reason is (
        FilingLatencyUnavailableReason.PUBLICATION_UNAVAILABLE
    )
    assert result.first_known_to_alert.unavailable_reason is (
        FilingLatencyUnavailableReason.ALERT_UNAVAILABLE
    )


def test_latency_chronology_and_both_receipt_identities_fail_closed() -> None:
    result = build_filing_latency_receipt(
        accession_number="0001045810-26-000073",
        event_lineage_id=None,
        authoritative_first_known_at=None,
        discovered_at=NOW - timedelta(hours=2),
        published_at=NOW - timedelta(hours=1),
        alerted_at=None,
        measured_at=NOW,
    )
    with pytest.raises(ValidationError, match="identity"):
        FilingLatencyReceipt.model_validate(
            {
                **result.model_dump(),
                "receipt_id": "20000000-0000-4000-8000-000000000002",
            }
        )
    with pytest.raises(ValidationError, match="cannot precede discovery"):
        FilingLatencyReceipt.model_validate(
            {**result.model_dump(), "published_at": NOW - timedelta(hours=3)}
        )

    gauge = build_gauge_measurement(
        metric_name=EngineeringMetricName.MEMORY_AVAILABLE_BYTES,
        observed_at=NOW,
        measured_at=NOW,
        value=8_000_000_000,
    )
    with pytest.raises(ValidationError, match="identity"):
        EngineeringMeasurementReceipt.model_validate(
            {
                **gauge.model_dump(),
                "receipt_id": "20000000-0000-4000-8000-000000000002",
            }
        )
