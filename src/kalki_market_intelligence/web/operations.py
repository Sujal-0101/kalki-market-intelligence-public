"""Low-overhead, secret-free Mission Control status projections."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from kalki_market_intelligence.prospective.science import (
    OutcomeScienceSnapshot,
    OutcomeScienceStratum,
)
from kalki_market_intelligence.radar.contracts import WorkerSnapshot, WorkerState
from kalki_market_intelligence.radar.measurements import EngineeringMeasurementReceipt


class HealthLevel(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    load_1m: float | None
    memory_used_bytes: int | None
    memory_available_bytes: int | None
    swap_used_bytes: int | None
    disk_free_bytes: int | None
    uptime_seconds: float | None
    temperature_celsius: float | None
    gpu_status: str


@dataclass(frozen=True, slots=True)
class NamedCount:
    name: str
    count: int


@dataclass(frozen=True, slots=True)
class DetectorCount:
    name: str
    invoked: int
    positive: int
    negative: int
    unknown: int
    not_assessed: int
    insufficient_evidence: int
    escalation_contributions: int


@dataclass(frozen=True, slots=True)
class FunnelWindow:
    hours: int
    telemetry_complete: bool
    sec_polls_attempted: int
    unterminated_sec_polls: int
    terminal_sec_polls: int
    completed_sec_polls: int
    degraded_sec_polls: int
    failed_sec_polls: int
    discovered_rows: int
    unique_candidates: int
    processing_transitions: int
    retry_wait_transitions: int
    skipped_transitions: int
    failed_transitions: int
    retained_transitions: int
    escalated_transitions: int
    retrieved: int
    parsed: int
    normalized: int
    stale_recoveries: int
    analyst_invocations: int
    qwen_attempts: int
    valid_contracts: int
    invalid_contracts: int
    runtime_failures: int
    timeouts: int
    pipeline_retry_attempts: int
    pipeline_retry_successes: int
    work_item_retry_attempts: int
    work_item_retry_successes: int
    latency_sample_size: int
    latency_sample_label: str
    latency_minimum_ms: int | None
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    latency_maximum_ms: int | None
    verifier_accepted: int
    verifier_rejected: int
    quarantined: int
    published: int
    discord_sent: int
    discord_duplicates: int
    human_leads: int
    human_results: int
    human_delivered: int
    human_delivery_failed: int
    human_duplicates: int
    failure_categories: tuple[NamedCount, ...]
    detectors: tuple[DetectorCount, ...]


@dataclass(frozen=True, slots=True)
class FunnelCurrent:
    pending: int
    processing: int
    retry_wait: int
    skipped: int
    published: int
    quarantined: int
    failed: int
    retained: int
    escalated: int
    backlog_depth: int
    oldest_backlog_seconds: float | None


@dataclass(frozen=True, slots=True)
class FunnelSnapshot:
    observed_at: str
    telemetry_started_at: str
    windows: tuple[FunnelWindow, ...]
    current: FunnelCurrent
    unavailable_metrics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScreeningReconciliationWindow:
    hours: int
    telemetry_complete: bool
    qualified: int
    screened_out: int
    analysis_incomplete: int
    reasons: tuple[NamedCount, ...]


@dataclass(frozen=True, slots=True)
class ScreeningReconciliation:
    observed_at: str
    telemetry_started_at: str
    windows: tuple[ScreeningReconciliationWindow, ...]
    retry_wait: int
    published: int
    quarantined: int
    failed: int
    discord_sent: int
    discord_duplicates: int
    legacy_terminal_without_decision: int


@dataclass(frozen=True, slots=True)
class OwnershipOperations:
    observed_at: str
    telemetry_started_at: str
    pending: int
    processing: int
    retry_wait: int
    completed: int
    failed: int
    receipt_count: int
    model_free_retained: int
    escalated_for_review: int
    oldest_backlog_seconds: float | None
    forms: tuple[NamedCount, ...]
    failure_categories: tuple[NamedCount, ...]


@dataclass(frozen=True, slots=True)
class FinancingOperations:
    observed_at: str
    telemetry_started_at: str
    pending: int
    processing: int
    retry_wait: int
    completed: int
    no_terms: int
    failed: int
    receipt_count: int
    model_free_retained: int
    oldest_backlog_seconds: float | None
    forms: tuple[NamedCount, ...]
    contexts: tuple[NamedCount, ...]
    failure_categories: tuple[NamedCount, ...]


@dataclass(frozen=True, slots=True)
class AccountingOperations:
    observed_at: str
    telemetry_started_at: str
    pending: int
    processing: int
    retry_wait: int
    completed: int
    no_events: int
    failed: int
    receipt_count: int
    model_free_retained: int
    oldest_backlog_seconds: float | None
    forms: tuple[NamedCount, ...]
    event_types: tuple[NamedCount, ...]
    comparisons: tuple[NamedCount, ...]
    failure_categories: tuple[NamedCount, ...]


@dataclass(frozen=True, slots=True)
class ConvergenceOperations:
    observed_at: str
    receipt_count: int
    families: tuple[NamedCount, ...]
    dispositions: tuple[NamedCount, ...]
    sources: tuple[NamedCount, ...]


@dataclass(frozen=True, slots=True)
class OutcomeScienceStratumOperations:
    cohort_sha256: str
    horizon: int
    origin: str
    classification: str
    sample_size: int
    completed_count: int
    unavailable_count: int
    favorable_count: int
    adverse_count: int
    observed_favorable_rate: Decimal | None
    wilson_lower: Decimal | None
    wilson_upper: Decimal | None
    power_sufficiency: str
    disposition: str


@dataclass(frozen=True, slots=True)
class OutcomeScienceOperations:
    observed_at: str
    protocol_version: str
    protocol_locked_at: str
    minimum_calibration_sample: int
    power_required_sample: int
    enrolled_plan_count: int
    terminal_outcome_count: int
    not_yet_due_plan_count: int
    due_without_outcome_count: int
    sample_size: int
    genuine_forward_count: int
    reconstructed_count: int
    completed_count: int
    unavailable_count: int
    favorable_count: int
    adverse_count: int
    disposition: str
    limitations: tuple[str, ...]
    strata: tuple[OutcomeScienceStratumOperations, ...]


def outcome_science_operations(snapshot: OutcomeScienceSnapshot) -> OutcomeScienceOperations:
    """Project a validated science snapshot without case or publication content."""

    population = snapshot.population
    report = snapshot.report
    return OutcomeScienceOperations(
        observed_at=population.knowledge_cutoff_at.isoformat(),
        protocol_version=report.protocol.protocol_version,
        protocol_locked_at=report.protocol.locked_at.isoformat(),
        minimum_calibration_sample=report.protocol.minimum_calibration_sample,
        power_required_sample=report.protocol.power_required_sample,
        enrolled_plan_count=population.enrolled_plan_count,
        terminal_outcome_count=population.terminal_outcome_count,
        not_yet_due_plan_count=population.not_yet_due_plan_count,
        due_without_outcome_count=population.due_without_outcome_count,
        sample_size=report.sample_size,
        genuine_forward_count=report.genuine_forward_count,
        reconstructed_count=report.reconstructed_count,
        completed_count=report.completed_count,
        unavailable_count=report.unavailable_count,
        favorable_count=report.favorable_count,
        adverse_count=report.adverse_count,
        disposition=report.disposition.value,
        limitations=report.limitations,
        strata=tuple(
            OutcomeScienceStratumOperations(
                cohort_sha256=_outcome_science_cohort_sha256(item),
                horizon=int(item.horizon),
                origin=item.origin.value,
                classification=item.signal_classification.value,
                sample_size=item.sample_size,
                completed_count=item.completed_count,
                unavailable_count=item.unavailable_count,
                favorable_count=item.favorable_count,
                adverse_count=item.adverse_count,
                observed_favorable_rate=item.observed_favorable_rate,
                wilson_lower=item.wilson_lower,
                wilson_upper=item.wilson_upper,
                power_sufficiency=item.power_sufficiency.value,
                disposition=item.disposition.value,
            )
            for item in report.strata
        ),
    )


def _outcome_science_cohort_sha256(item: OutcomeScienceStratum) -> str:
    payload = {
        "horizon": int(item.horizon),
        "origin": item.origin.value,
        "publication_schema_version": item.publication_schema_version,
        "signal_ruleset_version": item.signal_ruleset_version,
        "signal_classification": item.signal_classification.value,
        "analysis_model_name": item.analysis_model_name,
        "analysis_model_digest": item.analysis_model_digest,
        "analysis_prompt_version": item.analysis_prompt_version,
        "outcome_methodology_version": item.outcome_methodology_version,
        "outcome_calculation_version": item.outcome_calculation_version,
        "outcome_schema_version": item.outcome_schema_version,
        "provider_name": item.provider_name,
        "provider_terms_version": item.provider_terms_version,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class EngineeringMeasurementWindow:
    hours: int
    measurements: tuple[EngineeringMeasurementReceipt, ...]


@dataclass(frozen=True, slots=True)
class EngineeringMeasurementsSnapshot:
    observed_at: str
    telemetry_started_at: str
    windows: tuple[EngineeringMeasurementWindow, ...]
    gauges: tuple[EngineeringMeasurementReceipt, ...]


@dataclass(frozen=True, slots=True)
class MissionControlSnapshot:
    overall: HealthLevel
    worker: HealthLevel
    worker_state: str
    worker_heartbeat: str | None
    last_success: str | None
    public_count: int
    pending_count: int
    resources: ResourceSnapshot
    funnel: FunnelSnapshot | None
    notes: tuple[str, ...]


def collect_resources(*, root: Path = Path("/")) -> ResourceSnapshot:
    """Read inexpensive kernel files; unsupported sensors remain unavailable."""

    load = os.getloadavg()[0] if hasattr(os, "getloadavg") else None
    memory = _meminfo()
    swap_total = memory.get("SwapTotal")
    swap_free = memory.get("SwapFree")
    disk = shutil.disk_usage(root)
    uptime = _read_float(Path("/proc/uptime"))
    temperature = _temperature()
    return ResourceSnapshot(
        load_1m=load,
        memory_used_bytes=(memory.get("MemTotal", 0) - memory.get("MemAvailable", 0))
        if "MemTotal" in memory and "MemAvailable" in memory
        else None,
        memory_available_bytes=memory.get("MemAvailable"),
        swap_used_bytes=(swap_total - swap_free)
        if swap_total is not None and swap_free is not None
        else None,
        disk_free_bytes=disk.free,
        uptime_seconds=uptime,
        temperature_celsius=temperature,
        gpu_status="UNAVAILABLE (no safe GPU probe configured)",
    )


def mission_control_snapshot(
    worker_snapshot: WorkerSnapshot | None,
    *,
    resources: ResourceSnapshot | None = None,
    funnel: FunnelSnapshot | None = None,
) -> MissionControlSnapshot:
    """Derive conservative health without claiming dependency health by process age."""

    resource_snapshot = resources or collect_resources()
    notes: list[str] = []
    if worker_snapshot is None:
        worker_level = HealthLevel.UNKNOWN
        overall = HealthLevel.UNKNOWN
        notes.append("Worker has not published a status snapshot.")
        return MissionControlSnapshot(
            overall=overall,
            worker=worker_level,
            worker_state="unavailable",
            worker_heartbeat=None,
            last_success=None,
            public_count=0,
            pending_count=0,
            resources=resource_snapshot,
            funnel=funnel,
            notes=tuple(notes),
        )
    worker_level = (
        HealthLevel.HEALTHY
        if worker_snapshot.state in {WorkerState.IDLE, WorkerState.RUNNING}
        else HealthLevel.DEGRADED
    )
    overall = worker_level
    if resource_snapshot.disk_free_bytes is not None and resource_snapshot.disk_free_bytes < (
        1_073_741_824
    ):
        overall = HealthLevel.CRITICAL
        notes.append("Disk free space is below the one-gibibyte critical threshold.")
    elif resource_snapshot.disk_free_bytes is not None and resource_snapshot.disk_free_bytes < (
        5_368_709_120
    ):
        overall = max(overall, HealthLevel.DEGRADED, key=_health_rank)
        notes.append("Disk free space is below the five-gibibyte warning threshold.")
    if resource_snapshot.temperature_celsius is None:
        notes.append("Temperature sensor is unavailable; no thermal health claim is made.")
    if funnel is None:
        notes.append("Application funnel metrics are unavailable.")
    else:
        recent = next((item for item in funnel.windows if item.hours == 24), None)
        if recent is None:
            overall = HealthLevel.UNKNOWN
            notes.append("The 24-hour application window is unavailable.")
        else:
            if recent.failed_sec_polls or recent.degraded_sec_polls:
                overall = max(overall, HealthLevel.DEGRADED, key=_health_rank)
                notes.append(
                    "The 24-hour application window contains degraded or failed SEC cycles."
                )
            if recent.timeouts:
                overall = max(overall, HealthLevel.DEGRADED, key=_health_rank)
                notes.append("The 24-hour application window contains bounded Qwen timeouts.")
            if not recent.telemetry_complete:
                notes.append(
                    "Lifecycle telemetry coverage is partial for the 24-hour window; "
                    "measured transition counts begin at the displayed telemetry start."
                )
        if (
            funnel.current.oldest_backlog_seconds is not None
            and funnel.current.oldest_backlog_seconds > 86_400
        ):
            overall = max(overall, HealthLevel.DEGRADED, key=_health_rank)
            notes.append("The oldest active candidate has remained in backlog for over 24 hours.")
    return MissionControlSnapshot(
        overall=overall,
        worker=worker_level,
        worker_state=worker_snapshot.state.value,
        worker_heartbeat=worker_snapshot.heartbeat_at.isoformat(),
        last_success=(
            worker_snapshot.last_success_at.isoformat()
            if worker_snapshot.last_success_at is not None
            else None
        ),
        public_count=worker_snapshot.published_count,
        pending_count=worker_snapshot.pending_count,
        resources=resource_snapshot,
        funnel=funnel,
        notes=tuple(notes),
    )


def _health_rank(level: HealthLevel) -> int:
    return {
        HealthLevel.UNKNOWN: 0,
        HealthLevel.HEALTHY: 1,
        HealthLevel.DEGRADED: 2,
        HealthLevel.CRITICAL: 3,
    }[level]


def _meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            key, raw = line.split(":", 1)
            parts = raw.strip().split()
            if parts and parts[0].isdigit():
                values[key] = int(parts[0]) * (1024 if len(parts) > 1 and parts[1] == "kB" else 1)
    except (OSError, ValueError):
        return {}
    return values


def _read_float(path: Path) -> float | None:
    try:
        return float(path.read_text(encoding="ascii").split()[0])
    except (OSError, ValueError, IndexError):
        return None


def _temperature() -> float | None:
    values: list[float] = []
    for path in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        value = _read_float(path)
        if value is not None:
            values.append(value / 1_000 if value > 200 else value)
    return max(values) if values else None
