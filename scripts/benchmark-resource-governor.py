#!/usr/bin/env python3
"""Run deterministic governor scenarios and measure pure policy overhead."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from time import perf_counter

from kalki_market_intelligence.radar.resource_governor import (
    GIBIBYTE,
    GovernorAction,
    ResourceGovernorReceipt,
    ResourceObservation,
    build_resource_observation,
    decide_resource_governor,
)

START = datetime(2026, 8, 31, 13, tzinfo=UTC)


def observation(
    minute: int,
    *,
    temperature: int = 70_000,
    queue_depth: int = 10,
    oldest_queue_age_seconds: int = 3_600,
) -> ResourceObservation:
    return build_resource_observation(
        observed_at=START + timedelta(minutes=minute),
        logical_cpu_count=8,
        load_1m_milli=2_000,
        cpu_temperature_millicelsius=temperature,
        memory_available_bytes=12 * GIBIBYTE,
        swap_used_bytes=GIBIBYTE,
        recent_inference_samples=5,
        recent_inference_p95_ms=120_000,
        recent_inference_timeouts=0,
        queue_depth=queue_depth,
        oldest_queue_age_seconds=oldest_queue_age_seconds,
        active_inference_count=0,
    )


def accepted_history() -> ResourceGovernorReceipt:
    receipt = decide_resource_governor(observation(0))
    for minute in range(1, 4):
        receipt = decide_resource_governor(observation(minute), previous=receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=100_000)
    args = parser.parse_args()
    if not 1 <= args.iterations <= 10_000_000:
        parser.error("iterations must be between 1 and 10000000")

    initial = decide_resource_governor(observation(0))
    active = accepted_history()
    hot_observation = observation(4, temperature=91_000)
    hot = decide_resource_governor(hot_observation, previous=active)
    pressured_observation = observation(
        4,
        queue_depth=800,
        oldest_queue_age_seconds=100_000,
    )
    pressured = decide_resource_governor(pressured_observation, previous=active)

    started = perf_counter()
    last: ResourceGovernorReceipt | None = None
    for _ in range(args.iterations):
        last = decide_resource_governor(hot_observation, previous=active)
    elapsed = perf_counter() - started
    assert last is not None
    replay = decide_resource_governor(hot_observation, previous=active)
    checks = {
        "initial_baseline_deferred": initial.action is GovernorAction.DEFER_NEW_INFERENCE,
        "three_observation_recovery": active.action is GovernorAction.RESUME_INFERENCE,
        "thermal_defers_new_inference": hot.maximum_new_inferences == 0,
        "thermal_preserves_discovery": hot.continue_sec_discovery,
        "thermal_preserves_persistence": hot.continue_durable_persistence,
        "backlog_cannot_override_resources": pressured.maximum_new_inferences == 1,
    }
    report = {
        "report_version": "1.0.0",
        "iterations": args.iterations,
        "elapsed_seconds": round(elapsed, 6),
        "decisions_per_second": round(args.iterations / elapsed, 2),
        "deterministic_replay": replay == last,
        "checks": checks,
    }
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if all(checks.values()) and replay == last else 1


if __name__ == "__main__":
    raise SystemExit(main())
