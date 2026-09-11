"""Deterministic runtime generation for private engineering measurements.

This module converts already-persisted, content-free operational observations
into the closed receipts defined in :mod:`radar.measurements`.  It never reads
source excerpts, prompts, model responses, human research, or secrets.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from kalki_market_intelligence.contracts.common import UtcDatetime, normalize_utc
from kalki_market_intelligence.radar.measurements import (
    EngineeringMeasurementReceipt,
    EngineeringMetricName,
    FilingLatencyReceipt,
    MeasurementAvailability,
    MeasurementUnavailableReason,
    build_distribution_measurement,
    build_gauge_measurement,
    build_ratio_measurement,
    build_unavailable_measurement,
)

MEASUREMENT_WINDOWS_HOURS: tuple[Literal[24, 168], ...] = (24, 168)
MEASUREMENT_CADENCE_SECONDS = 3_600


@dataclass(frozen=True, slots=True)
class AnalystCallObservation:
    completed_at: UtcDatetime
    accession_number: str
    evidence_characters: int
    prompt_tokens: int | None
    latency_ms: int
    timed_out: bool
    latency_observed: bool = True


@dataclass(frozen=True, slots=True)
class TerminalDecisionObservation:
    decided_at: UtcDatetime
    accession_number: str
    disposition: str
    analyst_attempt_count: int


@dataclass(frozen=True, slots=True)
class PublicationObservation:
    brief_id: str
    accession_number: str
    published_at: UtcDatetime


@dataclass(frozen=True, slots=True)
class DeliveryObservation:
    brief_id: str
    completed_at: UtcDatetime
    status: str


@dataclass(frozen=True, slots=True)
class QueueObservation:
    depth: int
    oldest_age_seconds: int | None


@dataclass(frozen=True, slots=True)
class HostResourceObservation:
    logical_cpu_count: int
    load_1m: float | None
    cpu_temperature_celsius: float | None
    memory_available_bytes: int | None
    swap_used_bytes: int | None


@dataclass(frozen=True, slots=True)
class EngineeringMeasurementInput:
    telemetry_started_at: UtcDatetime
    observed_at: UtcDatetime
    analyst_calls: tuple[AnalystCallObservation, ...]
    terminal_decisions: tuple[TerminalDecisionObservation, ...]
    publications: tuple[PublicationObservation, ...]
    deliveries: tuple[DeliveryObservation, ...]
    filing_latencies: tuple[FilingLatencyReceipt, ...]
    queue: QueueObservation
    resources: HostResourceObservation


def build_runtime_engineering_measurements(
    source: EngineeringMeasurementInput,
) -> tuple[EngineeringMeasurementReceipt, ...]:
    """Build the complete 24-hour/7-day and instantaneous receipt set."""

    observed_at = normalize_utc(source.observed_at)
    telemetry_started_at = normalize_utc(source.telemetry_started_at)
    receipts: list[EngineeringMeasurementReceipt] = []
    for hours in MEASUREMENT_WINDOWS_HOURS:
        window_started_at = observed_at - timedelta(hours=hours)
        coverage_started_at = max(window_started_at, telemetry_started_at)
        partial = coverage_started_at > window_started_at
        availability = (
            MeasurementAvailability.PARTIAL if partial else MeasurementAvailability.AVAILABLE
        )
        partial_start = coverage_started_at if partial else None

        for metric_name in (
            EngineeringMetricName.FALSE_NEW_PUBLICATION_RATE,
            EngineeringMetricName.RECAP_SUPPRESSION_ACCURACY,
            EngineeringMetricName.MATERIAL_UPDATE_RECALL,
            EngineeringMetricName.FRESH_EVENT_PRECISION,
        ):
            receipts.append(
                build_unavailable_measurement(
                    metric_name=metric_name,
                    window_started_at=window_started_at,
                    window_ended_at=observed_at,
                    measured_at=observed_at,
                    reason=MeasurementUnavailableReason.REFERENCE_LABELS_UNAVAILABLE,
                )
            )

        calls = tuple(
            item
            for item in source.analyst_calls
            if coverage_started_at <= item.completed_at <= observed_at
        )
        decisions = tuple(
            item
            for item in source.terminal_decisions
            if coverage_started_at <= item.decided_at <= observed_at
        )
        deep_filings = {item.accession_number for item in decisions if item.analyst_attempt_count}
        receipts.append(
            _ratio_or_unavailable(
                metric_name=EngineeringMetricName.QWEN_CALLS_PER_FILING,
                numerator=len(calls),
                denominator=len(deep_filings),
                window_started_at=window_started_at,
                observed_at=observed_at,
                availability=availability,
                coverage_started_at=partial_start,
            )
        )
        receipts.append(
            _distribution_or_unavailable(
                metric_name=EngineeringMetricName.EVIDENCE_CHARACTERS,
                samples=tuple(item.evidence_characters for item in calls),
                window_started_at=window_started_at,
                observed_at=observed_at,
                availability=availability,
                coverage_started_at=partial_start,
            )
        )
        if calls and all(item.prompt_tokens is not None for item in calls):
            receipts.append(
                build_distribution_measurement(
                    metric_name=EngineeringMetricName.ACTUAL_INPUT_TOKENS,
                    window_started_at=window_started_at,
                    window_ended_at=observed_at,
                    measured_at=observed_at,
                    samples=tuple(
                        item.prompt_tokens for item in calls if item.prompt_tokens is not None
                    ),
                    availability=availability,
                    coverage_started_at=partial_start,
                )
            )
        else:
            reason = (
                MeasurementUnavailableReason.ACTUAL_TOKEN_COUNTS_UNAVAILABLE
                if calls
                else _empty_reason(partial)
            )
            receipts.append(
                build_unavailable_measurement(
                    metric_name=EngineeringMetricName.ACTUAL_INPUT_TOKENS,
                    window_started_at=window_started_at,
                    window_ended_at=observed_at,
                    measured_at=observed_at,
                    reason=reason,
                )
            )
        receipts.append(
            _distribution_or_unavailable(
                metric_name=EngineeringMetricName.ANALYST_LATENCY_MS,
                samples=tuple(item.latency_ms for item in calls if item.latency_observed),
                window_started_at=window_started_at,
                observed_at=observed_at,
                availability=availability,
                coverage_started_at=partial_start,
            )
        )
        receipts.append(
            _ratio_or_unavailable(
                metric_name=EngineeringMetricName.ANALYST_TIMEOUT_RATE,
                numerator=sum(item.timed_out for item in calls),
                denominator=len(calls),
                window_started_at=window_started_at,
                observed_at=observed_at,
                availability=availability,
                coverage_started_at=partial_start,
            )
        )

        qualified = tuple(item for item in decisions if item.disposition == "QUALIFIED")
        publication_counts = {
            item.accession_number: sum(
                publication.accession_number == item.accession_number
                for publication in source.publications
            )
            for item in qualified
        }
        receipts.append(
            _ratio_or_unavailable(
                metric_name=EngineeringMetricName.PUBLICATION_EXACT_ONCE_RATE,
                numerator=sum(count == 1 for count in publication_counts.values()),
                denominator=len(qualified),
                window_started_at=window_started_at,
                observed_at=observed_at,
                availability=availability,
                coverage_started_at=partial_start,
            )
        )
        window_publications = tuple(
            item
            for item in source.publications
            if coverage_started_at <= item.published_at <= observed_at
        )
        sent_counts = {
            item.brief_id: sum(
                delivery.brief_id == item.brief_id and delivery.status == "sent"
                for delivery in source.deliveries
            )
            for item in window_publications
        }
        receipts.append(
            _ratio_or_unavailable(
                metric_name=EngineeringMetricName.DISCORD_EXACT_ONCE_RATE,
                numerator=sum(count == 1 for count in sent_counts.values()),
                denominator=len(window_publications),
                window_started_at=window_started_at,
                observed_at=observed_at,
                availability=availability,
                coverage_started_at=partial_start,
            )
        )

        latencies = tuple(
            item
            for item in _latest_filing_latencies(source.filing_latencies)
            if coverage_started_at <= item.discovered_at <= observed_at
        )
        receipts.extend(
            _latency_measurements(
                latencies=latencies,
                window_started_at=window_started_at,
                observed_at=observed_at,
                availability=availability,
                coverage_started_at=partial_start,
                partial=partial,
            )
        )

    receipts.extend(_gauge_measurements(source))
    return tuple(receipts)


def _ratio_or_unavailable(
    *,
    metric_name: EngineeringMetricName,
    numerator: int,
    denominator: int,
    window_started_at: UtcDatetime,
    observed_at: UtcDatetime,
    availability: MeasurementAvailability,
    coverage_started_at: UtcDatetime | None,
) -> EngineeringMeasurementReceipt:
    if denominator:
        return build_ratio_measurement(
            metric_name=metric_name,
            window_started_at=window_started_at,
            window_ended_at=observed_at,
            measured_at=observed_at,
            numerator=numerator,
            denominator=denominator,
            availability=availability,
            coverage_started_at=coverage_started_at,
        )
    return build_unavailable_measurement(
        metric_name=metric_name,
        window_started_at=window_started_at,
        window_ended_at=observed_at,
        measured_at=observed_at,
        reason=_empty_reason(availability is MeasurementAvailability.PARTIAL),
    )


def _distribution_or_unavailable(
    *,
    metric_name: EngineeringMetricName,
    samples: tuple[int, ...],
    window_started_at: UtcDatetime,
    observed_at: UtcDatetime,
    availability: MeasurementAvailability,
    coverage_started_at: UtcDatetime | None,
) -> EngineeringMeasurementReceipt:
    if samples:
        return build_distribution_measurement(
            metric_name=metric_name,
            window_started_at=window_started_at,
            window_ended_at=observed_at,
            measured_at=observed_at,
            samples=samples,
            availability=availability,
            coverage_started_at=coverage_started_at,
        )
    return build_unavailable_measurement(
        metric_name=metric_name,
        window_started_at=window_started_at,
        window_ended_at=observed_at,
        measured_at=observed_at,
        reason=_empty_reason(availability is MeasurementAvailability.PARTIAL),
    )


def _latency_measurements(
    *,
    latencies: tuple[FilingLatencyReceipt, ...],
    window_started_at: UtcDatetime,
    observed_at: UtcDatetime,
    availability: MeasurementAvailability,
    coverage_started_at: UtcDatetime | None,
    partial: bool,
) -> tuple[EngineeringMeasurementReceipt, ...]:
    values = (
        (
            EngineeringMetricName.AUTHORITATIVE_DISCLOSURE_TO_DISCOVERY_MS,
            tuple(
                item.first_known_to_discovery.value_ms
                for item in latencies
                if item.first_known_to_discovery.value_ms is not None
            ),
            MeasurementUnavailableReason.AUTHORITATIVE_FIRST_KNOWN_UNAVAILABLE,
        ),
        (
            EngineeringMetricName.DISCOVERY_TO_PUBLICATION_MS,
            tuple(
                item.discovery_to_publication.value_ms
                for item in latencies
                if item.discovery_to_publication.value_ms is not None
            ),
            MeasurementUnavailableReason.PUBLICATION_UNAVAILABLE,
        ),
        (
            EngineeringMetricName.AUTHORITATIVE_DISCLOSURE_TO_ALERT_MS,
            tuple(
                item.first_known_to_alert.value_ms
                for item in latencies
                if item.first_known_to_alert.value_ms is not None
            ),
            MeasurementUnavailableReason.AUTHORITATIVE_FIRST_KNOWN_UNAVAILABLE,
        ),
    )
    receipts: list[EngineeringMeasurementReceipt] = []
    for metric_name, samples, missing_reason in values:
        if samples:
            receipts.append(
                build_distribution_measurement(
                    metric_name=metric_name,
                    window_started_at=window_started_at,
                    window_ended_at=observed_at,
                    measured_at=observed_at,
                    samples=samples,
                    availability=availability,
                    coverage_started_at=coverage_started_at,
                )
            )
        else:
            receipts.append(
                build_unavailable_measurement(
                    metric_name=metric_name,
                    window_started_at=window_started_at,
                    window_ended_at=observed_at,
                    measured_at=observed_at,
                    reason=(missing_reason if latencies else _empty_reason(partial)),
                )
            )
    return tuple(receipts)


def _latest_filing_latencies(
    receipts: tuple[FilingLatencyReceipt, ...],
) -> tuple[FilingLatencyReceipt, ...]:
    latest: dict[str, FilingLatencyReceipt] = {}
    for receipt in receipts:
        current = latest.get(receipt.accession_number)
        if current is None or (
            receipt.published_at is not None,
            receipt.alerted_at is not None,
            receipt.measured_at,
            str(receipt.receipt_id),
        ) > (
            current.published_at is not None,
            current.alerted_at is not None,
            current.measured_at,
            str(current.receipt_id),
        ):
            latest[receipt.accession_number] = receipt
    return tuple(latest[key] for key in sorted(latest))


def _gauge_measurements(
    source: EngineeringMeasurementInput,
) -> tuple[EngineeringMeasurementReceipt, ...]:
    observed_at = normalize_utc(source.observed_at)
    receipts: list[EngineeringMeasurementReceipt] = [
        build_gauge_measurement(
            metric_name=EngineeringMetricName.QUEUE_DEPTH,
            observed_at=observed_at,
            measured_at=observed_at,
            value=source.queue.depth,
        )
    ]
    if source.queue.oldest_age_seconds is None:
        receipts.append(
            build_unavailable_measurement(
                metric_name=EngineeringMetricName.QUEUE_OLDEST_AGE_SECONDS,
                window_started_at=observed_at,
                window_ended_at=observed_at,
                measured_at=observed_at,
                reason=MeasurementUnavailableReason.NO_OBSERVATIONS,
            )
        )
    else:
        receipts.append(
            build_gauge_measurement(
                metric_name=EngineeringMetricName.QUEUE_OLDEST_AGE_SECONDS,
                observed_at=observed_at,
                measured_at=observed_at,
                value=source.queue.oldest_age_seconds,
            )
        )

    resource_values: tuple[tuple[EngineeringMetricName, int | None], ...] = (
        (
            EngineeringMetricName.CPU_TEMPERATURE_MILLICELSIUS,
            (
                max(0, round(source.resources.cpu_temperature_celsius * 1_000))
                if source.resources.cpu_temperature_celsius is not None
                else None
            ),
        ),
        (
            EngineeringMetricName.CPU_LOAD_PER_CPU_MILLI,
            (
                max(
                    0,
                    round(source.resources.load_1m * 1_000 / source.resources.logical_cpu_count),
                )
                if source.resources.load_1m is not None
                else None
            ),
        ),
        (EngineeringMetricName.MEMORY_AVAILABLE_BYTES, source.resources.memory_available_bytes),
        (EngineeringMetricName.SWAP_USED_BYTES, source.resources.swap_used_bytes),
    )
    for metric_name, value in resource_values:
        receipts.append(
            build_gauge_measurement(
                metric_name=metric_name,
                observed_at=observed_at,
                measured_at=observed_at,
                value=value,
            )
            if value is not None
            else build_unavailable_measurement(
                metric_name=metric_name,
                window_started_at=observed_at,
                window_ended_at=observed_at,
                measured_at=observed_at,
                reason=MeasurementUnavailableReason.SENSOR_UNAVAILABLE,
            )
        )
    return tuple(receipts)


def _empty_reason(partial: bool) -> MeasurementUnavailableReason:
    return (
        MeasurementUnavailableReason.TELEMETRY_EPOCH_INCOMPLETE
        if partial
        else MeasurementUnavailableReason.NO_OBSERVATIONS
    )
