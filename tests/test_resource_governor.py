"""Deterministic thermal/resource governor and recovery tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from kalki_market_intelligence.radar.resource_governor import (
    GIBIBYTE,
    GovernorAction,
    GovernorAdvisory,
    GovernorBlockReason,
    GovernorMode,
    ResourceGovernorReceipt,
    ResourceObservation,
    accepted_resource_governor_policy,
    build_resource_observation,
    decide_resource_governor,
)

NOW = datetime(2026, 8, 31, 13, tzinfo=UTC)


def observation(
    minute: int,
    *,
    load_1m_milli: int | None = 2_000,
    temperature: int | None = 70_000,
    memory_available: int | None = 12 * GIBIBYTE,
    swap_used: int | None = GIBIBYTE,
    samples: int = 5,
    p95_ms: int | None = 120_000,
    timeouts: int = 0,
    queue_depth: int = 10,
    oldest_age: int | None = 3_600,
    active: int = 0,
) -> ResourceObservation:
    return build_resource_observation(
        observed_at=NOW + timedelta(minutes=minute),
        logical_cpu_count=8,
        load_1m_milli=load_1m_milli,
        cpu_temperature_millicelsius=temperature,
        memory_available_bytes=memory_available,
        swap_used_bytes=swap_used,
        recent_inference_samples=samples,
        recent_inference_p95_ms=p95_ms,
        recent_inference_timeouts=timeouts,
        queue_depth=queue_depth,
        oldest_queue_age_seconds=oldest_age,
        active_inference_count=active,
    )


def active_receipt() -> ResourceGovernorReceipt:
    receipt = decide_resource_governor(observation(0))
    assert receipt.mode is GovernorMode.DEFERRED
    for minute in range(1, 4):
        receipt = decide_resource_governor(observation(minute), previous=receipt)
    assert receipt.mode is GovernorMode.ACTIVE
    return receipt


def test_initial_baseline_defers_only_model_work() -> None:
    result = decide_resource_governor(observation(0))

    assert result.mode is GovernorMode.DEFERRED
    assert result.action is GovernorAction.DEFER_NEW_INFERENCE
    assert result.blocking_reasons == (GovernorBlockReason.BASELINE_UNAVAILABLE,)
    assert result.maximum_new_inferences == 0
    assert result.continue_sec_discovery is True
    assert result.continue_durable_persistence is True
    assert result.allow_active_inference_to_finish is True


def test_three_safe_observations_are_required_before_resume() -> None:
    first = decide_resource_governor(observation(0))
    second = decide_resource_governor(observation(1), previous=first)
    third = decide_resource_governor(observation(2), previous=second)
    fourth = decide_resource_governor(observation(3), previous=third)

    assert second.action is GovernorAction.COOLDOWN and second.recovery_streak == 1
    assert third.action is GovernorAction.COOLDOWN and third.recovery_streak == 2
    assert fourth.action is GovernorAction.RESUME_INFERENCE
    assert fourth.mode is GovernorMode.ACTIVE
    assert fourth.recovery_streak == 3
    assert fourth.maximum_new_inferences == 1
    assert GovernorAdvisory.RECOVERY_COMPLETE in fourth.advisories


def test_thermal_hysteresis_resets_recovery_until_below_resume_limit() -> None:
    active = active_receipt()
    hot = decide_resource_governor(observation(4, temperature=91_000), previous=active)
    warm = decide_resource_governor(observation(5, temperature=85_000), previous=hot)
    cool = decide_resource_governor(observation(6, temperature=80_000), previous=warm)

    assert hot.blocking_reasons == (GovernorBlockReason.TEMPERATURE_HIGH,)
    assert warm.blocking_reasons == (GovernorBlockReason.TEMPERATURE_HIGH,)
    assert warm.recovery_streak == 0
    assert cool.action is GovernorAction.COOLDOWN
    assert cool.recovery_streak == 1
    assert cool.deferred_at == hot.observation.observed_at


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"load_1m_milli": 7_200}, GovernorBlockReason.LOAD_HIGH),
        ({"memory_available": 3 * GIBIBYTE}, GovernorBlockReason.MEMORY_LOW),
        (
            {"swap_used": GIBIBYTE + 64 * 1024 * 1024},
            GovernorBlockReason.SWAP_GROWTH,
        ),
        ({"p95_ms": 280_000}, GovernorBlockReason.INFERENCE_LATENCY_HIGH),
        ({"timeouts": 2}, GovernorBlockReason.INFERENCE_TIMEOUT_RATE_HIGH),
    ],
)
def test_each_measured_resource_boundary_defers_new_inference(
    updates: dict[str, int], reason: GovernorBlockReason
) -> None:
    active = active_receipt()
    result = decide_resource_governor(observation(4, **updates), previous=active)

    assert result.mode is GovernorMode.DEFERRED
    assert reason in result.blocking_reasons
    assert result.maximum_new_inferences == 0
    assert result.continue_sec_discovery is True
    assert result.continue_durable_persistence is True


def test_missing_required_sensor_and_stale_baseline_fail_closed() -> None:
    active = active_receipt()
    missing = decide_resource_governor(observation(4, temperature=None), previous=active)
    stale = decide_resource_governor(observation(30), previous=active)

    assert GovernorBlockReason.REQUIRED_SENSOR_UNAVAILABLE in missing.blocking_reasons
    assert GovernorBlockReason.BASELINE_UNAVAILABLE in stale.blocking_reasons
    assert missing.maximum_new_inferences == stale.maximum_new_inferences == 0


def test_queue_pressure_is_visible_but_cannot_override_safe_resource_rules() -> None:
    active = active_receipt()
    pressured = decide_resource_governor(
        observation(4, queue_depth=800, oldest_age=100_000), previous=active
    )
    hot_pressured = decide_resource_governor(
        observation(5, temperature=95_000, queue_depth=800, oldest_age=100_000),
        previous=pressured,
    )

    assert pressured.action is GovernorAction.PROCEED_INFERENCE
    assert pressured.maximum_new_inferences == 1
    assert GovernorAdvisory.BACKLOG_PRESSURE in pressured.advisories
    assert GovernorAdvisory.AGED_BACKLOG in pressured.advisories
    assert hot_pressured.action is GovernorAction.DEFER_NEW_INFERENCE
    assert hot_pressured.maximum_new_inferences == 0


def test_single_flight_holds_new_claim_and_allows_active_call_to_finish() -> None:
    active = active_receipt()
    held = decide_resource_governor(observation(4, active=1), previous=active)

    assert held.mode is GovernorMode.ACTIVE
    assert held.action is GovernorAction.HOLD_SINGLE_FLIGHT
    assert held.maximum_new_inferences == 0
    assert held.allow_active_inference_to_finish is True
    assert GovernorAdvisory.INFERENCE_ALREADY_ACTIVE in held.advisories


def test_observation_and_receipt_identity_mutation_fail_validation() -> None:
    value = observation(0)
    with pytest.raises(ValidationError, match="fingerprint"):
        ResourceObservation.model_validate(
            {**value.model_dump(), "memory_available_bytes": 2 * GIBIBYTE}
        )

    receipt = decide_resource_governor(value)
    with pytest.raises(ValidationError, match="identity"):
        ResourceGovernorReceipt.model_validate(
            {
                **receipt.model_dump(),
                "receipt_id": "10000000-0000-4000-8000-000000000001",
            }
        )
    with pytest.raises(ValidationError, match="identity"):
        ResourceGovernorReceipt.model_validate(
            {
                **receipt.model_dump(),
                "blocking_reasons": [GovernorBlockReason.REQUIRED_SENSOR_UNAVAILABLE],
            }
        )


def test_policy_identity_and_observation_chronology_are_closed() -> None:
    policy = accepted_resource_governor_policy()
    with pytest.raises(ValidationError, match="policy identity"):
        policy.__class__.model_validate(
            {
                **policy.model_dump(),
                "policy_id": "10000000-0000-4000-8000-000000000001",
            }
        )

    first = decide_resource_governor(observation(0))
    with pytest.raises(ValueError, match="advance in UTC"):
        decide_resource_governor(observation(0), previous=first)


def test_empty_queue_and_latency_measurements_must_reconcile() -> None:
    with pytest.raises(ValidationError, match="queue depth"):
        observation(0, queue_depth=0, oldest_age=1)
    with pytest.raises(ValidationError, match="latency samples"):
        observation(0, samples=0, p95_ms=120_000)
