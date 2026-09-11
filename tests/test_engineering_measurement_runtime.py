"""Prospective deterministic engineering-measurement generation tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kalki_market_intelligence.radar.measurement_runtime import (
    AnalystCallObservation,
    DeliveryObservation,
    EngineeringMeasurementInput,
    HostResourceObservation,
    PublicationObservation,
    QueueObservation,
    TerminalDecisionObservation,
    build_runtime_engineering_measurements,
)
from kalki_market_intelligence.radar.measurements import (
    EngineeringMeasurementReceipt,
    EngineeringMetricName,
    MeasurementAvailability,
    MeasurementUnavailableReason,
    build_filing_latency_receipt,
)

NOW = datetime(2026, 8, 31, 18, tzinfo=UTC)
ACCESSION = "0001045810-26-000073"


def _by_metric(
    receipts: tuple[EngineeringMeasurementReceipt, ...],
    metric_name: EngineeringMetricName,
    *,
    hours: int,
) -> EngineeringMeasurementReceipt:
    return next(
        item
        for item in receipts
        if item.metric_name is metric_name
        and int((item.window_ended_at - item.window_started_at).total_seconds()) == hours * 3600
    )


def test_runtime_builds_complete_partial_windows_without_inventing_missing_values() -> None:
    decided_at = NOW - timedelta(minutes=35)
    published_at = NOW - timedelta(minutes=30)
    alerted_at = NOW - timedelta(minutes=29)
    latency = build_filing_latency_receipt(
        accession_number=ACCESSION,
        event_lineage_id=None,
        authoritative_first_known_at=None,
        discovered_at=NOW - timedelta(hours=1),
        published_at=published_at,
        alerted_at=alerted_at,
        measured_at=alerted_at,
    )
    source = EngineeringMeasurementInput(
        telemetry_started_at=NOW - timedelta(hours=2),
        observed_at=NOW,
        analyst_calls=(
            AnalystCallObservation(
                completed_at=NOW - timedelta(minutes=45),
                accession_number=ACCESSION,
                evidence_characters=3_200,
                prompt_tokens=1_900,
                latency_ms=92_000,
                timed_out=False,
            ),
            AnalystCallObservation(
                completed_at=NOW - timedelta(minutes=40),
                accession_number=ACCESSION,
                evidence_characters=3_300,
                prompt_tokens=None,
                latency_ms=300_100,
                timed_out=True,
                latency_observed=False,
            ),
        ),
        terminal_decisions=(
            TerminalDecisionObservation(
                decided_at=decided_at,
                accession_number=ACCESSION,
                disposition="QUALIFIED",
                analyst_attempt_count=2,
            ),
        ),
        publications=(
            PublicationObservation(
                brief_id="10000000-0000-4000-8000-000000000001",
                accession_number=ACCESSION,
                published_at=published_at,
            ),
        ),
        deliveries=(
            DeliveryObservation(
                brief_id="10000000-0000-4000-8000-000000000001",
                completed_at=alerted_at,
                status="sent",
            ),
        ),
        filing_latencies=(latency,),
        queue=QueueObservation(depth=0, oldest_age_seconds=None),
        resources=HostResourceObservation(
            logical_cpu_count=8,
            load_1m=4.0,
            cpu_temperature_celsius=None,
            memory_available_bytes=8_000_000_000,
            swap_used_bytes=0,
        ),
    )

    receipts = build_runtime_engineering_measurements(source)

    assert len(receipts) == 34
    calls = _by_metric(receipts, EngineeringMetricName.QWEN_CALLS_PER_FILING, hours=24)
    assert calls.availability is MeasurementAvailability.PARTIAL
    assert calls.numerator == 2 and calls.denominator == 1
    tokens = _by_metric(receipts, EngineeringMetricName.ACTUAL_INPUT_TOKENS, hours=24)
    assert tokens.unavailable_reason is (
        MeasurementUnavailableReason.ACTUAL_TOKEN_COUNTS_UNAVAILABLE
    )
    analyst_latency = _by_metric(receipts, EngineeringMetricName.ANALYST_LATENCY_MS, hours=24)
    assert analyst_latency.sample_count == 1
    assert analyst_latency.minimum_value == analyst_latency.maximum_value == 92_000
    reference = _by_metric(receipts, EngineeringMetricName.FRESH_EVENT_PRECISION, hours=24)
    assert reference.unavailable_reason is (
        MeasurementUnavailableReason.REFERENCE_LABELS_UNAVAILABLE
    )
    first_known = _by_metric(
        receipts,
        EngineeringMetricName.AUTHORITATIVE_DISCLOSURE_TO_DISCOVERY_MS,
        hours=24,
    )
    assert first_known.unavailable_reason is (
        MeasurementUnavailableReason.AUTHORITATIVE_FIRST_KNOWN_UNAVAILABLE
    )
    publication = _by_metric(receipts, EngineeringMetricName.DISCOVERY_TO_PUBLICATION_MS, hours=24)
    assert publication.minimum_value == 1_800_000
    gauges = {
        item.metric_name: item
        for item in receipts
        if item.window_started_at == item.window_ended_at
    }
    assert gauges[EngineeringMetricName.QUEUE_DEPTH].gauge_value == 0
    assert gauges[EngineeringMetricName.QUEUE_OLDEST_AGE_SECONDS].unavailable_reason is (
        MeasurementUnavailableReason.NO_OBSERVATIONS
    )
    assert gauges[EngineeringMetricName.CPU_LOAD_PER_CPU_MILLI].gauge_value == 500
    assert (
        gauges[EngineeringMetricName.CPU_TEMPERATURE_MILLICELSIUS].unavailable_reason
        is MeasurementUnavailableReason.SENSOR_UNAVAILABLE
    )


def test_complete_empty_window_reports_no_observations_not_a_zero_rate() -> None:
    receipts = build_runtime_engineering_measurements(
        EngineeringMeasurementInput(
            telemetry_started_at=NOW - timedelta(days=8),
            observed_at=NOW,
            analyst_calls=(),
            terminal_decisions=(),
            publications=(),
            deliveries=(),
            filing_latencies=(),
            queue=QueueObservation(depth=0, oldest_age_seconds=None),
            resources=HostResourceObservation(
                logical_cpu_count=8,
                load_1m=None,
                cpu_temperature_celsius=None,
                memory_available_bytes=None,
                swap_used_bytes=None,
            ),
        )
    )

    timeout = _by_metric(receipts, EngineeringMetricName.ANALYST_TIMEOUT_RATE, hours=24)
    assert timeout.availability is MeasurementAvailability.UNAVAILABLE
    assert timeout.unavailable_reason is MeasurementUnavailableReason.NO_OBSERVATIONS
    assert timeout.denominator is None
