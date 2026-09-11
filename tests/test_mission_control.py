"""Mission Control health remains conservative and secret-free."""

from __future__ import annotations

from datetime import UTC, datetime

from kalki_market_intelligence.radar.contracts import WorkerSnapshot, WorkerState
from kalki_market_intelligence.web.operations import (
    FunnelCurrent,
    FunnelSnapshot,
    FunnelWindow,
    HealthLevel,
    ResourceSnapshot,
    mission_control_snapshot,
)

NOW = datetime(2026, 8, 26, 12, tzinfo=UTC)


def snapshot(state: WorkerState) -> WorkerSnapshot:
    return WorkerSnapshot(
        state=state,
        heartbeat_at=NOW,
        last_success_at=NOW,
        next_run_at=NOW,
        last_error_code=None,
        discovered_count=0,
        pending_count=0,
        published_count=0,
        discord_enabled=False,
        model_name="qwen3:4b",
    )


def resources(*, disk_free_bytes: int | None) -> ResourceSnapshot:
    return ResourceSnapshot(
        load_1m=None,
        memory_used_bytes=None,
        memory_available_bytes=None,
        swap_used_bytes=None,
        disk_free_bytes=disk_free_bytes,
        uptime_seconds=None,
        temperature_celsius=None,
        gpu_status="UNAVAILABLE",
    )


def funnel(*, degraded_polls: int = 0, timeouts: int = 0) -> FunnelSnapshot:
    window_values: dict[str, object] = {
        "hours": 24,
        "telemetry_complete": True,
        "sec_polls_attempted": 3,
        "unterminated_sec_polls": 0,
        "terminal_sec_polls": 3,
        "completed_sec_polls": 3 - degraded_polls,
        "degraded_sec_polls": degraded_polls,
        "failed_sec_polls": 0,
        "discovered_rows": 2,
        "unique_candidates": 2,
        "processing_transitions": 2,
        "retry_wait_transitions": 0,
        "skipped_transitions": 2,
        "failed_transitions": 0,
        "retained_transitions": 0,
        "escalated_transitions": 2,
        "retrieved": 2,
        "parsed": 2,
        "normalized": 2,
        "stale_recoveries": 0,
        "analyst_invocations": 4,
        "qwen_attempts": 4,
        "valid_contracts": 4,
        "invalid_contracts": 0,
        "runtime_failures": timeouts,
        "timeouts": timeouts,
        "pipeline_retry_attempts": 0,
        "pipeline_retry_successes": 0,
        "work_item_retry_attempts": 0,
        "work_item_retry_successes": 0,
        "latency_sample_size": 4,
        "latency_sample_label": "small_n",
        "latency_minimum_ms": 100,
        "latency_p50_ms": 150.0,
        "latency_p95_ms": 200.0,
        "latency_maximum_ms": 200,
        "verifier_accepted": 0,
        "verifier_rejected": 0,
        "quarantined": 0,
        "published": 0,
        "discord_sent": 0,
        "discord_duplicates": 0,
        "human_leads": 0,
        "human_results": 0,
        "human_delivered": 0,
        "human_delivery_failed": 0,
        "human_duplicates": 0,
        "failure_categories": (),
        "detectors": (),
    }
    return FunnelSnapshot(
        observed_at=NOW.isoformat(),
        telemetry_started_at=NOW.isoformat(),
        windows=(FunnelWindow(**window_values),),  # type: ignore[arg-type]
        current=FunnelCurrent(
            pending=0,
            processing=0,
            retry_wait=0,
            skipped=2,
            published=0,
            quarantined=0,
            failed=0,
            retained=0,
            escalated=2,
            backlog_depth=0,
            oldest_backlog_seconds=None,
        ),
        unavailable_metrics=(),
    )


def test_missing_worker_is_unknown_not_healthy() -> None:
    result = mission_control_snapshot(None, resources=resources(disk_free_bytes=None))

    assert result.overall is HealthLevel.UNKNOWN
    assert result.worker is HealthLevel.UNKNOWN
    assert "has not published" in result.notes[0]


def test_degraded_worker_and_disk_thresholds_are_explicit() -> None:
    result = mission_control_snapshot(
        snapshot(WorkerState.DEGRADED), resources=resources(disk_free_bytes=512 * 1024 * 1024)
    )

    assert result.overall is HealthLevel.CRITICAL
    assert result.worker is HealthLevel.DEGRADED
    assert any("critical threshold" in note for note in result.notes)


def test_healthy_worker_does_not_claim_unavailable_sensors() -> None:
    result = mission_control_snapshot(
        snapshot(WorkerState.IDLE), resources=resources(disk_free_bytes=20 * 1024**3)
    )

    assert result.overall is HealthLevel.HEALTHY
    assert result.resources.gpu_status == "UNAVAILABLE"
    assert any("Temperature sensor is unavailable" in note for note in result.notes)


def test_recent_application_failures_degrade_health_even_when_worker_is_idle() -> None:
    result = mission_control_snapshot(
        snapshot(WorkerState.IDLE),
        resources=resources(disk_free_bytes=20 * 1024**3),
        funnel=funnel(degraded_polls=1, timeouts=1),
    )

    assert result.overall is HealthLevel.DEGRADED
    assert any("degraded or failed SEC cycles" in note for note in result.notes)
    assert any("Qwen timeouts" in note for note in result.notes)
