"""Shadow-only deterministic thermal and resource governor contracts."""

from __future__ import annotations

import json
from datetime import timedelta
from enum import StrEnum
from hashlib import sha256
from typing import Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, model_validator

from kalki_market_intelligence.contracts.common import (
    ContractModel,
    Sha256Hex,
    UtcDatetime,
    normalize_utc,
)

RESOURCE_GOVERNOR_VERSION: Literal["1.0.0"] = "1.0.0"
GIBIBYTE = 1_073_741_824


class GovernorMode(StrEnum):
    ACTIVE = "active"
    DEFERRED = "deferred"


class GovernorAction(StrEnum):
    PROCEED_INFERENCE = "proceed_inference"
    HOLD_SINGLE_FLIGHT = "hold_single_flight"
    DEFER_NEW_INFERENCE = "defer_new_inference"
    COOLDOWN = "cooldown"
    RESUME_INFERENCE = "resume_inference"


class GovernorBlockReason(StrEnum):
    BASELINE_UNAVAILABLE = "baseline_unavailable"
    REQUIRED_SENSOR_UNAVAILABLE = "required_sensor_unavailable"
    TEMPERATURE_HIGH = "temperature_high"
    LOAD_HIGH = "load_high"
    MEMORY_LOW = "memory_low"
    SWAP_GROWTH = "swap_growth"
    INFERENCE_LATENCY_HIGH = "inference_latency_high"
    INFERENCE_TIMEOUT_RATE_HIGH = "inference_timeout_rate_high"


class GovernorAdvisory(StrEnum):
    SAFE_ENVELOPE = "safe_envelope"
    RECOVERY_CONFIRMING = "recovery_confirming"
    RECOVERY_COMPLETE = "recovery_complete"
    INFERENCE_ALREADY_ACTIVE = "inference_already_active"
    BACKLOG_PRESSURE = "backlog_pressure"
    AGED_BACKLOG = "aged_backlog"


class ResourceGovernorPolicy(ContractModel):
    """Closed thresholds chosen below measured unsafe host conditions."""

    policy_id: UUID
    defer_temperature_millicelsius: Literal[90000] = 90_000
    resume_temperature_millicelsius: Literal[82000] = 82_000
    defer_load_per_cpu_milli: Literal[900] = 900
    resume_load_per_cpu_milli: Literal[700] = 700
    defer_memory_available_bytes: Literal[4294967296] = 4_294_967_296
    resume_memory_available_bytes: Literal[6442450944] = 6_442_450_944
    maximum_swap_growth_bytes: Literal[67108864] = 67_108_864
    defer_inference_p95_ms: Literal[270000] = 270_000
    resume_inference_p95_ms: Literal[240000] = 240_000
    minimum_latency_samples: Literal[5] = 5
    timeout_rate_basis_points: Literal[2500] = 2_500
    backlog_advisory_depth: Literal[250] = 250
    aged_backlog_seconds: Literal[86400] = 86_400
    recovery_observations_required: Literal[3] = 3
    maximum_baseline_age_seconds: Literal[900] = 900
    maximum_concurrent_inference: Literal[1] = 1
    discovery_always_enabled: Literal[True] = True
    durable_persistence_always_enabled: Literal[True] = True
    policy_version: Literal["1.0.0"] = RESOURCE_GOVERNOR_VERSION

    @model_validator(mode="after")
    def identity_reconciles(self) -> Self:
        expected = uuid5(
            NAMESPACE_URL,
            "kalki:resource-governor-policy:1.0.0:90000:82000:900:700:"
            "4294967296:6442450944:67108864:270000:240000:5:2500:250:86400:3:900:1",
        )
        if self.policy_id != expected:
            raise ValueError("resource governor policy identity does not reconcile")
        return self


class ResourceObservation(ContractModel):
    """One content-free host/application observation before a new model claim."""

    observation_id: UUID
    observed_at: UtcDatetime
    logical_cpu_count: int = Field(ge=1, le=256)
    load_1m_milli: int | None = Field(default=None, ge=0, le=1_000_000)
    cpu_temperature_millicelsius: int | None = Field(default=None, ge=-50_000, le=150_000)
    memory_available_bytes: int | None = Field(default=None, ge=0, le=10**15)
    swap_used_bytes: int | None = Field(default=None, ge=0, le=10**15)
    recent_inference_samples: int = Field(ge=0, le=100_000)
    recent_inference_p95_ms: int | None = Field(default=None, ge=0, le=3_600_000)
    recent_inference_timeouts: int = Field(ge=0, le=100_000)
    queue_depth: int = Field(ge=0, le=10_000_000)
    oldest_queue_age_seconds: int | None = Field(default=None, ge=0, le=315_576_000)
    active_inference_count: int = Field(ge=0, le=1)
    observation_sha256: Sha256Hex
    observation_version: Literal["1.0.0"] = RESOURCE_GOVERNOR_VERSION

    @model_validator(mode="after")
    def observation_reconciles(self) -> Self:
        if bool(self.recent_inference_samples) != bool(self.recent_inference_p95_ms):
            raise ValueError("latency samples and p95 must be present together")
        if self.recent_inference_timeouts > self.recent_inference_samples:
            raise ValueError("inference timeouts cannot exceed the sample count")
        if bool(self.queue_depth) != (self.oldest_queue_age_seconds is not None):
            raise ValueError("non-empty queue depth and oldest age must be present together")
        if self.observation_sha256 != _observation_sha256(
            observed_at=self.observed_at,
            logical_cpu_count=self.logical_cpu_count,
            load_1m_milli=self.load_1m_milli,
            cpu_temperature_millicelsius=self.cpu_temperature_millicelsius,
            memory_available_bytes=self.memory_available_bytes,
            swap_used_bytes=self.swap_used_bytes,
            recent_inference_samples=self.recent_inference_samples,
            recent_inference_p95_ms=self.recent_inference_p95_ms,
            recent_inference_timeouts=self.recent_inference_timeouts,
            queue_depth=self.queue_depth,
            oldest_queue_age_seconds=self.oldest_queue_age_seconds,
            active_inference_count=self.active_inference_count,
        ):
            raise ValueError("resource observation fingerprint does not reconcile")
        expected_id = uuid5(
            NAMESPACE_URL,
            f"kalki:resource-observation:{self.observation_sha256}",
        )
        if self.observation_id != expected_id:
            raise ValueError("resource observation identity does not reconcile")
        return self


class ResourceGovernorReceipt(ContractModel):
    """Replay-stable shadow decision; discovery and persistence cannot be disabled."""

    receipt_id: UUID
    policy_id: UUID
    observation: ResourceObservation
    previous_receipt_id: UUID | None = None
    mode: GovernorMode
    action: GovernorAction
    blocking_reasons: tuple[GovernorBlockReason, ...] = Field(max_length=8)
    advisories: tuple[GovernorAdvisory, ...] = Field(max_length=8)
    recovery_streak: int = Field(ge=0, le=3)
    deferred_at: UtcDatetime | None = None
    maximum_new_inferences: Literal[0, 1]
    continue_sec_discovery: Literal[True] = True
    continue_durable_persistence: Literal[True] = True
    allow_active_inference_to_finish: Literal[True] = True
    governor_version: Literal["1.0.0"] = RESOURCE_GOVERNOR_VERSION

    @model_validator(mode="after")
    def decision_reconciles(self) -> Self:
        if self.blocking_reasons != tuple(sorted(set(self.blocking_reasons), key=str)):
            raise ValueError("governor blocking reasons must be unique and ordered")
        if self.advisories != tuple(sorted(set(self.advisories), key=str)):
            raise ValueError("governor advisories must be unique and ordered")
        deferred = self.mode is GovernorMode.DEFERRED
        if deferred != (self.deferred_at is not None):
            raise ValueError("deferred mode requires its original UTC deferral time")
        if deferred and self.maximum_new_inferences != 0:
            raise ValueError("deferred governor cannot admit new inference")
        if self.maximum_new_inferences and self.observation.active_inference_count:
            raise ValueError("single-flight governor cannot admit concurrent inference")
        if (
            self.action
            in {
                GovernorAction.DEFER_NEW_INFERENCE,
                GovernorAction.COOLDOWN,
            }
            and not deferred
        ):
            raise ValueError("defer and cooldown actions require deferred mode")
        if (
            self.action
            in {
                GovernorAction.PROCEED_INFERENCE,
                GovernorAction.HOLD_SINGLE_FLIGHT,
                GovernorAction.RESUME_INFERENCE,
            }
            and deferred
        ):
            raise ValueError("active actions cannot retain deferred mode")
        if self.action is GovernorAction.PROCEED_INFERENCE and self.maximum_new_inferences != 1:
            raise ValueError("proceed action must admit exactly one inference")
        if self.action is GovernorAction.HOLD_SINGLE_FLIGHT and (
            self.maximum_new_inferences != 0 or not self.observation.active_inference_count
        ):
            raise ValueError("single-flight hold requires one already-active inference")
        if self.action is GovernorAction.RESUME_INFERENCE and self.recovery_streak != 3:
            raise ValueError("resume action requires the complete recovery streak")
        expected_id = _governor_receipt_id(
            policy_id=self.policy_id,
            observation_sha256=self.observation.observation_sha256,
            previous_receipt_id=self.previous_receipt_id,
            mode=self.mode,
            action=self.action,
            blocking_reasons=self.blocking_reasons,
            advisories=self.advisories,
            recovery_streak=self.recovery_streak,
            deferred_at=self.deferred_at,
            maximum_new_inferences=self.maximum_new_inferences,
        )
        if self.receipt_id != expected_id:
            raise ValueError("resource governor receipt identity does not reconcile")
        return self


def accepted_resource_governor_policy() -> ResourceGovernorPolicy:
    return ResourceGovernorPolicy(
        policy_id=uuid5(
            NAMESPACE_URL,
            "kalki:resource-governor-policy:1.0.0:90000:82000:900:700:"
            "4294967296:6442450944:67108864:270000:240000:5:2500:250:86400:3:900:1",
        )
    )


def build_resource_observation(
    *,
    observed_at: UtcDatetime,
    logical_cpu_count: int,
    load_1m_milli: int | None,
    cpu_temperature_millicelsius: int | None,
    memory_available_bytes: int | None,
    swap_used_bytes: int | None,
    recent_inference_samples: int,
    recent_inference_p95_ms: int | None,
    recent_inference_timeouts: int,
    queue_depth: int,
    oldest_queue_age_seconds: int | None,
    active_inference_count: int,
) -> ResourceObservation:
    observed_at = normalize_utc(observed_at)
    fingerprint = _observation_sha256(
        observed_at=observed_at,
        logical_cpu_count=logical_cpu_count,
        load_1m_milli=load_1m_milli,
        cpu_temperature_millicelsius=cpu_temperature_millicelsius,
        memory_available_bytes=memory_available_bytes,
        swap_used_bytes=swap_used_bytes,
        recent_inference_samples=recent_inference_samples,
        recent_inference_p95_ms=recent_inference_p95_ms,
        recent_inference_timeouts=recent_inference_timeouts,
        queue_depth=queue_depth,
        oldest_queue_age_seconds=oldest_queue_age_seconds,
        active_inference_count=active_inference_count,
    )
    return ResourceObservation(
        observation_id=uuid5(NAMESPACE_URL, f"kalki:resource-observation:{fingerprint}"),
        observed_at=observed_at,
        logical_cpu_count=logical_cpu_count,
        load_1m_milli=load_1m_milli,
        cpu_temperature_millicelsius=cpu_temperature_millicelsius,
        memory_available_bytes=memory_available_bytes,
        swap_used_bytes=swap_used_bytes,
        recent_inference_samples=recent_inference_samples,
        recent_inference_p95_ms=recent_inference_p95_ms,
        recent_inference_timeouts=recent_inference_timeouts,
        queue_depth=queue_depth,
        oldest_queue_age_seconds=oldest_queue_age_seconds,
        active_inference_count=active_inference_count,
        observation_sha256=fingerprint,
    )


def decide_resource_governor(
    observation: ResourceObservation,
    *,
    previous: ResourceGovernorReceipt | None = None,
    policy: ResourceGovernorPolicy | None = None,
) -> ResourceGovernorReceipt:
    policy = policy or accepted_resource_governor_policy()
    if previous is not None:
        if previous.policy_id != policy.policy_id:
            raise ValueError("resource governor history must use one policy identity")
        if observation.observed_at <= previous.observation.observed_at:
            raise ValueError("resource observations must advance in UTC")

    baseline_valid = previous is not None and (
        observation.observed_at - previous.observation.observed_at
        <= timedelta(seconds=policy.maximum_baseline_age_seconds)
    )
    blockers = _blocking_reasons(
        observation,
        previous=previous if baseline_valid else None,
        policy=policy,
        recovering=previous is not None and previous.mode is GovernorMode.DEFERRED,
    )
    advisories = _queue_advisories(observation, policy)
    previous_deferred = previous is not None and previous.mode is GovernorMode.DEFERRED
    maximum_new: Literal[0, 1]

    if blockers:
        mode = GovernorMode.DEFERRED
        action = GovernorAction.DEFER_NEW_INFERENCE
        recovery_streak = 0
        if previous_deferred:
            assert previous is not None
            deferred_at = previous.deferred_at
        else:
            deferred_at = observation.observed_at
        maximum_new = 0
    elif previous_deferred:
        assert previous is not None
        recovery_streak = previous.recovery_streak + 1
        if recovery_streak < policy.recovery_observations_required:
            mode = GovernorMode.DEFERRED
            action = GovernorAction.COOLDOWN
            deferred_at = previous.deferred_at
            maximum_new = 0
            advisories = (*advisories, GovernorAdvisory.RECOVERY_CONFIRMING)
        else:
            mode = GovernorMode.ACTIVE
            action = (
                GovernorAction.HOLD_SINGLE_FLIGHT
                if observation.active_inference_count
                else GovernorAction.RESUME_INFERENCE
            )
            deferred_at = None
            maximum_new = 0 if observation.active_inference_count else 1
            advisories = (*advisories, GovernorAdvisory.RECOVERY_COMPLETE)
    else:
        mode = GovernorMode.ACTIVE
        recovery_streak = 0
        deferred_at = None
        if observation.active_inference_count:
            action = GovernorAction.HOLD_SINGLE_FLIGHT
            maximum_new = 0
            advisories = (*advisories, GovernorAdvisory.INFERENCE_ALREADY_ACTIVE)
        else:
            action = GovernorAction.PROCEED_INFERENCE
            maximum_new = 1
            advisories = (*advisories, GovernorAdvisory.SAFE_ENVELOPE)

    ordered_blockers = tuple(sorted(set(blockers), key=str))
    ordered_advisories = tuple(sorted(set(advisories), key=str))
    previous_id = previous.receipt_id if previous is not None else None
    receipt_id = _governor_receipt_id(
        policy_id=policy.policy_id,
        observation_sha256=observation.observation_sha256,
        previous_receipt_id=previous_id,
        mode=mode,
        action=action,
        blocking_reasons=ordered_blockers,
        advisories=ordered_advisories,
        recovery_streak=recovery_streak,
        deferred_at=deferred_at,
        maximum_new_inferences=maximum_new,
    )
    return ResourceGovernorReceipt(
        receipt_id=receipt_id,
        policy_id=policy.policy_id,
        observation=observation,
        previous_receipt_id=previous_id,
        mode=mode,
        action=action,
        blocking_reasons=ordered_blockers,
        advisories=ordered_advisories,
        recovery_streak=recovery_streak,
        deferred_at=deferred_at,
        maximum_new_inferences=maximum_new,
    )


def _blocking_reasons(
    observation: ResourceObservation,
    *,
    previous: ResourceGovernorReceipt | None,
    policy: ResourceGovernorPolicy,
    recovering: bool,
) -> tuple[GovernorBlockReason, ...]:
    reasons: list[GovernorBlockReason] = []
    required = (
        observation.load_1m_milli,
        observation.cpu_temperature_millicelsius,
        observation.memory_available_bytes,
        observation.swap_used_bytes,
    )
    if any(value is None for value in required):
        reasons.append(GovernorBlockReason.REQUIRED_SENSOR_UNAVAILABLE)
    if previous is None:
        reasons.append(GovernorBlockReason.BASELINE_UNAVAILABLE)

    temperature_limit = (
        policy.resume_temperature_millicelsius
        if recovering
        else policy.defer_temperature_millicelsius
    )
    if (
        observation.cpu_temperature_millicelsius is not None
        and observation.cpu_temperature_millicelsius >= temperature_limit
    ):
        reasons.append(GovernorBlockReason.TEMPERATURE_HIGH)
    load_limit = (
        policy.resume_load_per_cpu_milli if recovering else policy.defer_load_per_cpu_milli
    ) * observation.logical_cpu_count
    if observation.load_1m_milli is not None and observation.load_1m_milli >= load_limit:
        reasons.append(GovernorBlockReason.LOAD_HIGH)
    memory_limit = (
        policy.resume_memory_available_bytes if recovering else policy.defer_memory_available_bytes
    )
    if (
        observation.memory_available_bytes is not None
        and observation.memory_available_bytes < memory_limit
    ):
        reasons.append(GovernorBlockReason.MEMORY_LOW)
    if (
        previous is not None
        and observation.swap_used_bytes is not None
        and previous.observation.swap_used_bytes is not None
        and observation.swap_used_bytes - previous.observation.swap_used_bytes
        >= policy.maximum_swap_growth_bytes
    ):
        reasons.append(GovernorBlockReason.SWAP_GROWTH)
    latency_limit = policy.resume_inference_p95_ms if recovering else policy.defer_inference_p95_ms
    if (
        observation.recent_inference_samples >= policy.minimum_latency_samples
        and observation.recent_inference_p95_ms is not None
        and observation.recent_inference_p95_ms >= latency_limit
    ):
        reasons.append(GovernorBlockReason.INFERENCE_LATENCY_HIGH)
    if (
        observation.recent_inference_samples >= policy.minimum_latency_samples
        and observation.recent_inference_timeouts * 10_000
        >= observation.recent_inference_samples * policy.timeout_rate_basis_points
    ):
        reasons.append(GovernorBlockReason.INFERENCE_TIMEOUT_RATE_HIGH)
    return tuple(reasons)


def _queue_advisories(
    observation: ResourceObservation,
    policy: ResourceGovernorPolicy,
) -> tuple[GovernorAdvisory, ...]:
    values: list[GovernorAdvisory] = []
    if observation.queue_depth >= policy.backlog_advisory_depth:
        values.append(GovernorAdvisory.BACKLOG_PRESSURE)
    if (
        observation.oldest_queue_age_seconds is not None
        and observation.oldest_queue_age_seconds >= policy.aged_backlog_seconds
    ):
        values.append(GovernorAdvisory.AGED_BACKLOG)
    return tuple(values)


def _observation_sha256(**values: object) -> str:
    payload = {
        **values,
        "observed_at": normalize_utc(values["observed_at"]).isoformat(),  # type: ignore[arg-type]
        "observation_version": RESOURCE_GOVERNOR_VERSION,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _governor_receipt_id(
    *,
    policy_id: UUID,
    observation_sha256: str,
    previous_receipt_id: UUID | None,
    mode: GovernorMode,
    action: GovernorAction,
    blocking_reasons: tuple[GovernorBlockReason, ...],
    advisories: tuple[GovernorAdvisory, ...],
    recovery_streak: int,
    deferred_at: UtcDatetime | None,
    maximum_new_inferences: int,
) -> UUID:
    decision_sha256 = sha256(
        json.dumps(
            {
                "action": action.value,
                "advisories": [item.value for item in advisories],
                "blocking_reasons": [item.value for item in blocking_reasons],
                "deferred_at": normalize_utc(deferred_at).isoformat()
                if deferred_at is not None
                else None,
                "governor_version": RESOURCE_GOVERNOR_VERSION,
                "maximum_new_inferences": maximum_new_inferences,
                "mode": mode.value,
                "observation_sha256": observation_sha256,
                "policy_id": policy_id.hex,
                "previous_receipt_id": previous_receipt_id.hex
                if previous_receipt_id is not None
                else None,
                "recovery_streak": recovery_streak,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return uuid5(NAMESPACE_URL, f"kalki:resource-governor:{decision_sha256}")
