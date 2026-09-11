"""Closed, private engineering-quality measurement contracts.

The contracts retain counts, bounded distributions, gauges, and content-free
filing lifecycle times. They do not make market-performance claims and they do
not contain filing text, prompts, model responses, human research, or secrets.
"""

from __future__ import annotations

import json
from enum import StrEnum
from hashlib import sha256
from math import ceil
from typing import Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, model_validator

from kalki_market_intelligence.contracts.common import (
    ContractModel,
    Sha256Hex,
    UtcDatetime,
    normalize_utc,
)
from kalki_market_intelligence.radar.contracts import AccessionNumber

ENGINEERING_MEASUREMENT_VERSION: Literal["1.0.0"] = "1.0.0"
MAX_MEASUREMENT_VALUE = 10**18


class EngineeringMetricName(StrEnum):
    FALSE_NEW_PUBLICATION_RATE = "false_new_publication_rate"
    RECAP_SUPPRESSION_ACCURACY = "recap_suppression_accuracy"
    MATERIAL_UPDATE_RECALL = "material_update_recall"
    FRESH_EVENT_PRECISION = "fresh_event_precision"
    QWEN_CALLS_PER_FILING = "qwen_calls_per_filing"
    EVIDENCE_CHARACTERS = "evidence_characters"
    ACTUAL_INPUT_TOKENS = "actual_input_tokens"
    ANALYST_LATENCY_MS = "analyst_latency_ms"
    ANALYST_TIMEOUT_RATE = "analyst_timeout_rate"
    QUEUE_DEPTH = "queue_depth"
    QUEUE_OLDEST_AGE_SECONDS = "queue_oldest_age_seconds"
    CPU_TEMPERATURE_MILLICELSIUS = "cpu_temperature_millicelsius"
    CPU_LOAD_PER_CPU_MILLI = "cpu_load_per_cpu_milli"
    MEMORY_AVAILABLE_BYTES = "memory_available_bytes"
    SWAP_USED_BYTES = "swap_used_bytes"
    PUBLICATION_EXACT_ONCE_RATE = "publication_exact_once_rate"
    DISCORD_EXACT_ONCE_RATE = "discord_exact_once_rate"
    AUTHORITATIVE_DISCLOSURE_TO_DISCOVERY_MS = "authoritative_disclosure_to_discovery_ms"
    DISCOVERY_TO_PUBLICATION_MS = "discovery_to_publication_ms"
    AUTHORITATIVE_DISCLOSURE_TO_ALERT_MS = "authoritative_disclosure_to_alert_ms"


class MetricShape(StrEnum):
    RATIO = "ratio"
    DISTRIBUTION = "distribution"
    GAUGE = "gauge"


class MetricUnit(StrEnum):
    FRACTION = "fraction"
    CALLS_PER_FILING = "calls_per_filing"
    CHARACTERS = "characters"
    TOKENS = "tokens"
    MILLISECONDS = "milliseconds"
    COUNT = "count"
    SECONDS = "seconds"
    MILLICELSIUS = "millicelsius"
    LOAD_PER_CPU_MILLI = "load_per_cpu_milli"
    BYTES = "bytes"


class MeasurementAvailability(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class MeasurementUnavailableReason(StrEnum):
    NO_OBSERVATIONS = "no_observations"
    TELEMETRY_EPOCH_INCOMPLETE = "telemetry_epoch_incomplete"
    REFERENCE_LABELS_UNAVAILABLE = "reference_labels_unavailable"
    ACTUAL_TOKEN_COUNTS_UNAVAILABLE = "actual_token_counts_unavailable"
    SENSOR_UNAVAILABLE = "sensor_unavailable"
    AUTHORITATIVE_FIRST_KNOWN_UNAVAILABLE = "authoritative_first_known_unavailable"
    PUBLICATION_UNAVAILABLE = "publication_unavailable"
    ALERT_UNAVAILABLE = "alert_unavailable"


class MetricDefinition(ContractModel):
    metric_name: EngineeringMetricName
    shape: MetricShape
    unit: MetricUnit
    bounded_fraction: bool
    definition_code: str = Field(pattern=r"^[A-Z0-9_]{3,96}$")
    definition_sha256: Sha256Hex
    metric_version: Literal["1.0.0"] = ENGINEERING_MEASUREMENT_VERSION

    @model_validator(mode="after")
    def hash_reconciles(self) -> Self:
        if self.definition_sha256 != _definition_hash(
            metric_name=self.metric_name,
            shape=self.shape,
            unit=self.unit,
            bounded_fraction=self.bounded_fraction,
            definition_code=self.definition_code,
        ):
            raise ValueError("metric definition hash does not reconcile")
        return self


_DEFINITION_ROWS: tuple[tuple[EngineeringMetricName, MetricShape, MetricUnit, bool, str], ...] = (
    (
        EngineeringMetricName.FALSE_NEW_PUBLICATION_RATE,
        MetricShape.RATIO,
        MetricUnit.FRACTION,
        True,
        "RECAP_OR_DUPLICATE_PUBLICATIONS_OVER_REVIEWED_PUBLICATIONS",
    ),
    (
        EngineeringMetricName.RECAP_SUPPRESSION_ACCURACY,
        MetricShape.RATIO,
        MetricUnit.FRACTION,
        True,
        "CORRECTLY_SUPPRESSED_RECAPS_OVER_LABELED_RECAPS",
    ),
    (
        EngineeringMetricName.MATERIAL_UPDATE_RECALL,
        MetricShape.RATIO,
        MetricUnit.FRACTION,
        True,
        "DETECTED_MATERIAL_UPDATES_OVER_LABELED_MATERIAL_UPDATES",
    ),
    (
        EngineeringMetricName.FRESH_EVENT_PRECISION,
        MetricShape.RATIO,
        MetricUnit.FRACTION,
        True,
        "CONFIRMED_FRESH_EVENTS_OVER_PUBLISHED_FRESH_EVENTS",
    ),
    (
        EngineeringMetricName.QWEN_CALLS_PER_FILING,
        MetricShape.RATIO,
        MetricUnit.CALLS_PER_FILING,
        False,
        "COMPLETED_QWEN_CALLS_OVER_DEEP_ANALYZED_FILINGS",
    ),
    (
        EngineeringMetricName.EVIDENCE_CHARACTERS,
        MetricShape.DISTRIBUTION,
        MetricUnit.CHARACTERS,
        False,
        "BOUNDED_EVIDENCE_CHARACTERS_PER_QWEN_CALL",
    ),
    (
        EngineeringMetricName.ACTUAL_INPUT_TOKENS,
        MetricShape.DISTRIBUTION,
        MetricUnit.TOKENS,
        False,
        "PROVIDER_REPORTED_PROMPT_TOKENS_PER_QWEN_CALL",
    ),
    (
        EngineeringMetricName.ANALYST_LATENCY_MS,
        MetricShape.DISTRIBUTION,
        MetricUnit.MILLISECONDS,
        False,
        "COMPLETED_ANALYST_CALL_LATENCY_MILLISECONDS",
    ),
    (
        EngineeringMetricName.ANALYST_TIMEOUT_RATE,
        MetricShape.RATIO,
        MetricUnit.FRACTION,
        True,
        "TIMEOUT_ANALYST_CALLS_OVER_COMPLETED_ANALYST_CALLS",
    ),
    (
        EngineeringMetricName.QUEUE_DEPTH,
        MetricShape.GAUGE,
        MetricUnit.COUNT,
        False,
        "CLAIMABLE_DEEP_ANALYSIS_QUEUE_DEPTH_AT_OBSERVATION",
    ),
    (
        EngineeringMetricName.QUEUE_OLDEST_AGE_SECONDS,
        MetricShape.GAUGE,
        MetricUnit.SECONDS,
        False,
        "OLDEST_CLAIMABLE_DEEP_ANALYSIS_QUEUE_AGE_SECONDS",
    ),
    (
        EngineeringMetricName.CPU_TEMPERATURE_MILLICELSIUS,
        MetricShape.GAUGE,
        MetricUnit.MILLICELSIUS,
        False,
        "HOST_CPU_PACKAGE_TEMPERATURE_MILLICELSIUS",
    ),
    (
        EngineeringMetricName.CPU_LOAD_PER_CPU_MILLI,
        MetricShape.GAUGE,
        MetricUnit.LOAD_PER_CPU_MILLI,
        False,
        "HOST_ONE_MINUTE_LOAD_PER_LOGICAL_CPU_MILLI",
    ),
    (
        EngineeringMetricName.MEMORY_AVAILABLE_BYTES,
        MetricShape.GAUGE,
        MetricUnit.BYTES,
        False,
        "HOST_AVAILABLE_MEMORY_BYTES",
    ),
    (
        EngineeringMetricName.SWAP_USED_BYTES,
        MetricShape.GAUGE,
        MetricUnit.BYTES,
        False,
        "HOST_SWAP_USED_BYTES",
    ),
    (
        EngineeringMetricName.PUBLICATION_EXACT_ONCE_RATE,
        MetricShape.RATIO,
        MetricUnit.FRACTION,
        True,
        "UNIQUE_QUALIFIED_ACCESSIONS_WITH_ONE_BRIEF_OVER_QUALIFIED_ACCESSIONS",
    ),
    (
        EngineeringMetricName.DISCORD_EXACT_ONCE_RATE,
        MetricShape.RATIO,
        MetricUnit.FRACTION,
        True,
        "UNIQUE_BRIEFS_WITH_ONE_SENT_DELIVERY_OVER_DELIVERY_ELIGIBLE_BRIEFS",
    ),
    (
        EngineeringMetricName.AUTHORITATIVE_DISCLOSURE_TO_DISCOVERY_MS,
        MetricShape.DISTRIBUTION,
        MetricUnit.MILLISECONDS,
        False,
        "AUTHORITATIVE_FIRST_KNOWN_TO_SEC_DISCOVERY_MILLISECONDS",
    ),
    (
        EngineeringMetricName.DISCOVERY_TO_PUBLICATION_MS,
        MetricShape.DISTRIBUTION,
        MetricUnit.MILLISECONDS,
        False,
        "SEC_DISCOVERY_TO_IMMUTABLE_PUBLICATION_MILLISECONDS",
    ),
    (
        EngineeringMetricName.AUTHORITATIVE_DISCLOSURE_TO_ALERT_MS,
        MetricShape.DISTRIBUTION,
        MetricUnit.MILLISECONDS,
        False,
        "AUTHORITATIVE_FIRST_KNOWN_TO_SENT_ALERT_MILLISECONDS",
    ),
)

_REFERENCE_METRICS = {
    EngineeringMetricName.FALSE_NEW_PUBLICATION_RATE,
    EngineeringMetricName.RECAP_SUPPRESSION_ACCURACY,
    EngineeringMetricName.MATERIAL_UPDATE_RECALL,
    EngineeringMetricName.FRESH_EVENT_PRECISION,
}
_SENSOR_METRICS = {
    EngineeringMetricName.CPU_TEMPERATURE_MILLICELSIUS,
    EngineeringMetricName.CPU_LOAD_PER_CPU_MILLI,
    EngineeringMetricName.MEMORY_AVAILABLE_BYTES,
    EngineeringMetricName.SWAP_USED_BYTES,
}


def accepted_metric_definitions() -> tuple[MetricDefinition, ...]:
    """Return the complete closed metric catalog in stable name order."""

    definitions = tuple(
        MetricDefinition(
            metric_name=name,
            shape=shape,
            unit=unit,
            bounded_fraction=bounded,
            definition_code=code,
            definition_sha256=_definition_hash(
                metric_name=name,
                shape=shape,
                unit=unit,
                bounded_fraction=bounded,
                definition_code=code,
            ),
        )
        for name, shape, unit, bounded, code in _DEFINITION_ROWS
    )
    return tuple(sorted(definitions, key=lambda item: item.metric_name.value))


class EngineeringMeasurementReceipt(ContractModel):
    """One aggregate-safe measurement; raw numerators remain authoritative."""

    receipt_id: UUID
    metric_name: EngineeringMetricName
    definition_sha256: Sha256Hex
    window_started_at: UtcDatetime
    window_ended_at: UtcDatetime
    measured_at: UtcDatetime
    availability: MeasurementAvailability
    unavailable_reason: MeasurementUnavailableReason | None = None
    coverage_started_at: UtcDatetime | None = None
    sample_count: int = Field(ge=0, le=MAX_MEASUREMENT_VALUE)
    numerator: int | None = Field(default=None, ge=0, le=MAX_MEASUREMENT_VALUE)
    denominator: int | None = Field(default=None, ge=1, le=MAX_MEASUREMENT_VALUE)
    scaled_value_millionths: int | None = Field(default=None, ge=0, le=MAX_MEASUREMENT_VALUE)
    minimum_value: int | None = Field(default=None, ge=0, le=MAX_MEASUREMENT_VALUE)
    p50_value: int | None = Field(default=None, ge=0, le=MAX_MEASUREMENT_VALUE)
    p90_value: int | None = Field(default=None, ge=0, le=MAX_MEASUREMENT_VALUE)
    p95_value: int | None = Field(default=None, ge=0, le=MAX_MEASUREMENT_VALUE)
    maximum_value: int | None = Field(default=None, ge=0, le=MAX_MEASUREMENT_VALUE)
    gauge_value: int | None = Field(default=None, ge=0, le=MAX_MEASUREMENT_VALUE)
    measurement_version: Literal["1.0.0"] = ENGINEERING_MEASUREMENT_VERSION

    @model_validator(mode="after")
    def shape_and_identity_reconcile(self) -> Self:
        definition = _DEFINITIONS[self.metric_name]
        if self.definition_sha256 != definition.definition_sha256:
            raise ValueError("measurement does not match its closed metric definition")
        if self.window_ended_at < self.window_started_at:
            raise ValueError("measurement window cannot end before it begins")
        if self.measured_at < self.window_ended_at:
            raise ValueError("measurement cannot be recorded before its window closes")

        value_fields = (
            self.numerator,
            self.denominator,
            self.scaled_value_millionths,
            self.minimum_value,
            self.p50_value,
            self.p90_value,
            self.p95_value,
            self.maximum_value,
            self.gauge_value,
        )
        if self.availability is MeasurementAvailability.UNAVAILABLE:
            if self.unavailable_reason is None or self.coverage_started_at is not None:
                raise ValueError("unavailable measurement requires one bounded reason only")
            if self.sample_count != 0 or any(value is not None for value in value_fields):
                raise ValueError("unavailable measurement cannot retain a value")
            if self.unavailable_reason not in _allowed_unavailable_reasons(self.metric_name):
                raise ValueError("unavailable reason is invalid for this metric")
        else:
            if self.unavailable_reason is not None:
                raise ValueError("available measurement cannot carry an unavailable reason")
            if self.availability is MeasurementAvailability.PARTIAL:
                if self.coverage_started_at is None or not (
                    self.window_started_at < self.coverage_started_at <= self.window_ended_at
                ):
                    raise ValueError("partial window requires its later telemetry epoch")
            elif self.coverage_started_at is not None:
                raise ValueError("complete measurement cannot carry a partial coverage time")
            self._validate_value_shape(definition)

        expected_id = uuid5(
            NAMESPACE_URL,
            f"kalki:engineering-measurement:{_measurement_fingerprint(self, include_id=False)}",
        )
        if self.receipt_id != expected_id:
            raise ValueError("engineering measurement identity does not reconcile")
        return self

    def _validate_value_shape(self, definition: MetricDefinition) -> None:
        distribution = (
            self.minimum_value,
            self.p50_value,
            self.p90_value,
            self.p95_value,
            self.maximum_value,
        )
        if definition.shape is MetricShape.RATIO:
            if self.numerator is None or self.denominator is None:
                raise ValueError("ratio measurement requires numerator and denominator")
            expected_scaled = self.numerator * 1_000_000 // self.denominator
            if self.scaled_value_millionths != expected_scaled:
                raise ValueError("ratio scaled value must be calculated deterministically")
            if self.sample_count != self.denominator:
                raise ValueError("ratio sample count must match its denominator")
            if definition.bounded_fraction and self.numerator > self.denominator:
                raise ValueError("bounded fraction numerator cannot exceed denominator")
            if any(value is not None for value in distribution) or self.gauge_value is not None:
                raise ValueError("ratio measurement cannot contain distribution or gauge values")
        elif definition.shape is MetricShape.DISTRIBUTION:
            if self.sample_count < 1 or any(value is None for value in distribution):
                raise ValueError("distribution measurement requires samples and all quantiles")
            values = tuple(value for value in distribution if value is not None)
            if values != tuple(sorted(values)):
                raise ValueError("distribution quantiles must be monotonic")
            if any(
                value is not None
                for value in (
                    self.numerator,
                    self.denominator,
                    self.scaled_value_millionths,
                    self.gauge_value,
                )
            ):
                raise ValueError("distribution measurement cannot contain ratio or gauge values")
        else:
            if self.window_started_at != self.window_ended_at or self.sample_count != 1:
                raise ValueError("gauge measurement must be one instantaneous observation")
            if self.gauge_value is None:
                raise ValueError("gauge measurement requires its observed value")
            if any(
                value is not None
                for value in (
                    self.numerator,
                    self.denominator,
                    self.scaled_value_millionths,
                    *distribution,
                )
            ):
                raise ValueError("gauge measurement cannot contain ratio or distribution values")


class FilingLatencyUnavailableReason(StrEnum):
    AUTHORITATIVE_FIRST_KNOWN_UNAVAILABLE = "authoritative_first_known_unavailable"
    PUBLICATION_UNAVAILABLE = "publication_unavailable"
    ALERT_UNAVAILABLE = "alert_unavailable"


class FilingLatencyValue(ContractModel):
    value_ms: int | None = Field(default=None, ge=0, le=MAX_MEASUREMENT_VALUE)
    unavailable_reason: FilingLatencyUnavailableReason | None = None

    @model_validator(mode="after")
    def availability_reconciles(self) -> Self:
        if (self.value_ms is None) == (self.unavailable_reason is None):
            raise ValueError("filing latency must have exactly one value or unavailable reason")
        return self


class FilingLatencyReceipt(ContractModel):
    """Content-free source/discovery/publication/alert chronology for one filing."""

    receipt_id: UUID
    accession_number: AccessionNumber
    event_lineage_id: UUID | None = None
    authoritative_first_known_at: UtcDatetime | None = None
    discovered_at: UtcDatetime
    published_at: UtcDatetime | None = None
    alerted_at: UtcDatetime | None = None
    first_known_to_discovery: FilingLatencyValue
    discovery_to_publication: FilingLatencyValue
    first_known_to_alert: FilingLatencyValue
    measured_at: UtcDatetime
    measurement_version: Literal["1.0.0"] = ENGINEERING_MEASUREMENT_VERSION

    @model_validator(mode="after")
    def chronology_and_identity_reconcile(self) -> Self:
        if self.authoritative_first_known_at is not None and self.event_lineage_id is None:
            raise ValueError("known authoritative time requires its event lineage")
        if (
            self.authoritative_first_known_at is not None
            and self.authoritative_first_known_at > self.discovered_at
        ):
            raise ValueError("authoritative first-known time cannot follow discovery")
        if self.published_at is not None and self.published_at < self.discovered_at:
            raise ValueError("publication cannot precede discovery")
        if self.alerted_at is not None and (
            self.published_at is None or self.alerted_at < self.published_at
        ):
            raise ValueError("alert requires and cannot precede publication")
        terminal_times = tuple(
            value
            for value in (self.discovered_at, self.published_at, self.alerted_at)
            if value is not None
        )
        if self.measured_at < max(terminal_times):
            raise ValueError("latency receipt cannot be measured before its retained events")
        expected = _expected_latency_values(
            first_known_at=self.authoritative_first_known_at,
            discovered_at=self.discovered_at,
            published_at=self.published_at,
            alerted_at=self.alerted_at,
        )
        if (
            self.first_known_to_discovery,
            self.discovery_to_publication,
            self.first_known_to_alert,
        ) != expected:
            raise ValueError("filing latency values do not reconcile to source chronology")
        expected_id = uuid5(
            NAMESPACE_URL,
            f"kalki:filing-latency:{_latency_fingerprint(self, include_id=False)}",
        )
        if self.receipt_id != expected_id:
            raise ValueError("filing latency receipt identity does not reconcile")
        return self


def build_ratio_measurement(
    *,
    metric_name: EngineeringMetricName,
    window_started_at: UtcDatetime,
    window_ended_at: UtcDatetime,
    measured_at: UtcDatetime,
    numerator: int,
    denominator: int,
    availability: MeasurementAvailability = MeasurementAvailability.AVAILABLE,
    coverage_started_at: UtcDatetime | None = None,
) -> EngineeringMeasurementReceipt:
    definition = _DEFINITIONS[metric_name]
    if definition.shape is not MetricShape.RATIO:
        raise ValueError("requested metric is not a ratio")
    if denominator < 1 or numerator < 0:
        raise ValueError("ratio requires a positive denominator and non-negative numerator")
    return _build_measurement(
        metric_name=metric_name,
        definition_sha256=definition.definition_sha256,
        window_started_at=normalize_utc(window_started_at),
        window_ended_at=normalize_utc(window_ended_at),
        measured_at=normalize_utc(measured_at),
        availability=availability,
        coverage_started_at=(
            normalize_utc(coverage_started_at) if coverage_started_at is not None else None
        ),
        sample_count=denominator,
        numerator=numerator,
        denominator=denominator,
        scaled_value_millionths=numerator * 1_000_000 // denominator,
    )


def build_distribution_measurement(
    *,
    metric_name: EngineeringMetricName,
    window_started_at: UtcDatetime,
    window_ended_at: UtcDatetime,
    measured_at: UtcDatetime,
    samples: tuple[int, ...],
    availability: MeasurementAvailability = MeasurementAvailability.AVAILABLE,
    coverage_started_at: UtcDatetime | None = None,
) -> EngineeringMeasurementReceipt:
    definition = _DEFINITIONS[metric_name]
    if definition.shape is not MetricShape.DISTRIBUTION:
        raise ValueError("requested metric is not a distribution")
    if not samples or any(value < 0 or value > MAX_MEASUREMENT_VALUE for value in samples):
        raise ValueError("distribution requires bounded non-negative samples")
    ordered = tuple(sorted(samples))
    return _build_measurement(
        metric_name=metric_name,
        definition_sha256=definition.definition_sha256,
        window_started_at=normalize_utc(window_started_at),
        window_ended_at=normalize_utc(window_ended_at),
        measured_at=normalize_utc(measured_at),
        availability=availability,
        coverage_started_at=(
            normalize_utc(coverage_started_at) if coverage_started_at is not None else None
        ),
        sample_count=len(ordered),
        minimum_value=ordered[0],
        p50_value=_nearest_rank(ordered, 50),
        p90_value=_nearest_rank(ordered, 90),
        p95_value=_nearest_rank(ordered, 95),
        maximum_value=ordered[-1],
    )


def build_gauge_measurement(
    *,
    metric_name: EngineeringMetricName,
    observed_at: UtcDatetime,
    measured_at: UtcDatetime,
    value: int,
) -> EngineeringMeasurementReceipt:
    definition = _DEFINITIONS[metric_name]
    if definition.shape is not MetricShape.GAUGE:
        raise ValueError("requested metric is not a gauge")
    observed_at = normalize_utc(observed_at)
    return _build_measurement(
        metric_name=metric_name,
        definition_sha256=definition.definition_sha256,
        window_started_at=observed_at,
        window_ended_at=observed_at,
        measured_at=normalize_utc(measured_at),
        availability=MeasurementAvailability.AVAILABLE,
        sample_count=1,
        gauge_value=value,
    )


def build_unavailable_measurement(
    *,
    metric_name: EngineeringMetricName,
    window_started_at: UtcDatetime,
    window_ended_at: UtcDatetime,
    measured_at: UtcDatetime,
    reason: MeasurementUnavailableReason,
) -> EngineeringMeasurementReceipt:
    definition = _DEFINITIONS[metric_name]
    return _build_measurement(
        metric_name=metric_name,
        definition_sha256=definition.definition_sha256,
        window_started_at=normalize_utc(window_started_at),
        window_ended_at=normalize_utc(window_ended_at),
        measured_at=normalize_utc(measured_at),
        availability=MeasurementAvailability.UNAVAILABLE,
        unavailable_reason=reason,
        sample_count=0,
    )


def build_filing_latency_receipt(
    *,
    accession_number: str,
    event_lineage_id: UUID | None,
    authoritative_first_known_at: UtcDatetime | None,
    discovered_at: UtcDatetime,
    published_at: UtcDatetime | None,
    alerted_at: UtcDatetime | None,
    measured_at: UtcDatetime,
) -> FilingLatencyReceipt:
    first_known_at = (
        normalize_utc(authoritative_first_known_at)
        if authoritative_first_known_at is not None
        else None
    )
    discovered_at = normalize_utc(discovered_at)
    published_at = normalize_utc(published_at) if published_at is not None else None
    alerted_at = normalize_utc(alerted_at) if alerted_at is not None else None
    latency_values = _expected_latency_values(
        first_known_at=first_known_at,
        discovered_at=discovered_at,
        published_at=published_at,
        alerted_at=alerted_at,
    )
    measured_at = normalize_utc(measured_at)
    draft = FilingLatencyReceipt.model_construct(
        receipt_id=UUID(int=0),
        accession_number=accession_number,
        event_lineage_id=event_lineage_id,
        authoritative_first_known_at=first_known_at,
        discovered_at=discovered_at,
        published_at=published_at,
        alerted_at=alerted_at,
        first_known_to_discovery=latency_values[0],
        discovery_to_publication=latency_values[1],
        first_known_to_alert=latency_values[2],
        measured_at=measured_at,
        measurement_version=ENGINEERING_MEASUREMENT_VERSION,
    )
    receipt_id = uuid5(
        NAMESPACE_URL,
        f"kalki:filing-latency:{_latency_fingerprint(draft, include_id=False)}",
    )
    return FilingLatencyReceipt(
        receipt_id=receipt_id,
        accession_number=accession_number,
        event_lineage_id=event_lineage_id,
        authoritative_first_known_at=first_known_at,
        discovered_at=discovered_at,
        published_at=published_at,
        alerted_at=alerted_at,
        first_known_to_discovery=latency_values[0],
        discovery_to_publication=latency_values[1],
        first_known_to_alert=latency_values[2],
        measured_at=measured_at,
    )


def _build_measurement(
    *,
    metric_name: EngineeringMetricName,
    definition_sha256: Sha256Hex,
    window_started_at: UtcDatetime,
    window_ended_at: UtcDatetime,
    measured_at: UtcDatetime,
    availability: MeasurementAvailability,
    unavailable_reason: MeasurementUnavailableReason | None = None,
    coverage_started_at: UtcDatetime | None = None,
    sample_count: int,
    numerator: int | None = None,
    denominator: int | None = None,
    scaled_value_millionths: int | None = None,
    minimum_value: int | None = None,
    p50_value: int | None = None,
    p90_value: int | None = None,
    p95_value: int | None = None,
    maximum_value: int | None = None,
    gauge_value: int | None = None,
) -> EngineeringMeasurementReceipt:
    draft = EngineeringMeasurementReceipt.model_construct(
        receipt_id=UUID(int=0),
        metric_name=metric_name,
        definition_sha256=definition_sha256,
        window_started_at=window_started_at,
        window_ended_at=window_ended_at,
        measured_at=measured_at,
        availability=availability,
        unavailable_reason=unavailable_reason,
        coverage_started_at=coverage_started_at,
        sample_count=sample_count,
        numerator=numerator,
        denominator=denominator,
        scaled_value_millionths=scaled_value_millionths,
        minimum_value=minimum_value,
        p50_value=p50_value,
        p90_value=p90_value,
        p95_value=p95_value,
        maximum_value=maximum_value,
        gauge_value=gauge_value,
        measurement_version=ENGINEERING_MEASUREMENT_VERSION,
    )
    receipt_id = uuid5(
        NAMESPACE_URL,
        f"kalki:engineering-measurement:{_measurement_fingerprint(draft, include_id=False)}",
    )
    return EngineeringMeasurementReceipt(
        receipt_id=receipt_id,
        metric_name=metric_name,
        definition_sha256=definition_sha256,
        window_started_at=window_started_at,
        window_ended_at=window_ended_at,
        measured_at=measured_at,
        availability=availability,
        unavailable_reason=unavailable_reason,
        coverage_started_at=coverage_started_at,
        sample_count=sample_count,
        numerator=numerator,
        denominator=denominator,
        scaled_value_millionths=scaled_value_millionths,
        minimum_value=minimum_value,
        p50_value=p50_value,
        p90_value=p90_value,
        p95_value=p95_value,
        maximum_value=maximum_value,
        gauge_value=gauge_value,
    )


def _nearest_rank(ordered: tuple[int, ...], percentile: int) -> int:
    return ordered[max(0, ceil(percentile * len(ordered) / 100) - 1)]


def _allowed_unavailable_reasons(
    metric_name: EngineeringMetricName,
) -> frozenset[MeasurementUnavailableReason]:
    common = {
        MeasurementUnavailableReason.NO_OBSERVATIONS,
        MeasurementUnavailableReason.TELEMETRY_EPOCH_INCOMPLETE,
    }
    if metric_name in _REFERENCE_METRICS:
        common.add(MeasurementUnavailableReason.REFERENCE_LABELS_UNAVAILABLE)
    if metric_name is EngineeringMetricName.ACTUAL_INPUT_TOKENS:
        common.add(MeasurementUnavailableReason.ACTUAL_TOKEN_COUNTS_UNAVAILABLE)
    if metric_name in _SENSOR_METRICS:
        common.add(MeasurementUnavailableReason.SENSOR_UNAVAILABLE)
    if metric_name in {
        EngineeringMetricName.AUTHORITATIVE_DISCLOSURE_TO_DISCOVERY_MS,
        EngineeringMetricName.AUTHORITATIVE_DISCLOSURE_TO_ALERT_MS,
    }:
        common.add(MeasurementUnavailableReason.AUTHORITATIVE_FIRST_KNOWN_UNAVAILABLE)
    if metric_name is EngineeringMetricName.DISCOVERY_TO_PUBLICATION_MS:
        common.add(MeasurementUnavailableReason.PUBLICATION_UNAVAILABLE)
    if metric_name is EngineeringMetricName.AUTHORITATIVE_DISCLOSURE_TO_ALERT_MS:
        common.add(MeasurementUnavailableReason.ALERT_UNAVAILABLE)
    return frozenset(common)


def _expected_latency_values(
    *,
    first_known_at: UtcDatetime | None,
    discovered_at: UtcDatetime,
    published_at: UtcDatetime | None,
    alerted_at: UtcDatetime | None,
) -> tuple[FilingLatencyValue, FilingLatencyValue, FilingLatencyValue]:
    first_to_discovery = (
        FilingLatencyValue(value_ms=int((discovered_at - first_known_at).total_seconds() * 1_000))
        if first_known_at is not None
        else FilingLatencyValue(
            unavailable_reason=(
                FilingLatencyUnavailableReason.AUTHORITATIVE_FIRST_KNOWN_UNAVAILABLE
            )
        )
    )
    discovery_to_publication = (
        FilingLatencyValue(value_ms=int((published_at - discovered_at).total_seconds() * 1_000))
        if published_at is not None
        else FilingLatencyValue(
            unavailable_reason=FilingLatencyUnavailableReason.PUBLICATION_UNAVAILABLE
        )
    )
    if first_known_at is None:
        first_to_alert = FilingLatencyValue(
            unavailable_reason=(
                FilingLatencyUnavailableReason.AUTHORITATIVE_FIRST_KNOWN_UNAVAILABLE
            )
        )
    elif alerted_at is None:
        first_to_alert = FilingLatencyValue(
            unavailable_reason=FilingLatencyUnavailableReason.ALERT_UNAVAILABLE
        )
    else:
        first_to_alert = FilingLatencyValue(
            value_ms=int((alerted_at - first_known_at).total_seconds() * 1_000)
        )
    return first_to_discovery, discovery_to_publication, first_to_alert


def _definition_hash(
    *,
    metric_name: EngineeringMetricName,
    shape: MetricShape,
    unit: MetricUnit,
    bounded_fraction: bool,
    definition_code: str,
) -> str:
    return sha256(
        json.dumps(
            {
                "bounded_fraction": bounded_fraction,
                "definition_code": definition_code,
                "metric_name": metric_name.value,
                "metric_version": ENGINEERING_MEASUREMENT_VERSION,
                "shape": shape.value,
                "unit": unit.value,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _measurement_fingerprint(receipt: EngineeringMeasurementReceipt, *, include_id: bool) -> str:
    payload = receipt.model_dump(mode="json")
    if not include_id:
        payload.pop("receipt_id", None)
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _latency_fingerprint(receipt: FilingLatencyReceipt, *, include_id: bool) -> str:
    payload = receipt.model_dump(mode="json")
    if not include_id:
        payload.pop("receipt_id", None)
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


_DEFINITIONS = {item.metric_name: item for item in accepted_metric_definitions()}
