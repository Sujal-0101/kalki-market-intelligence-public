"""Tests for the benchmark-gated adaptive compute shadow policy."""

from __future__ import annotations

from hashlib import sha256

import pytest
from pydantic import ValidationError

from kalki_market_intelligence.forensics.tiers import choose_tier
from kalki_market_intelligence.radar.adaptive_compute import (
    AdaptiveComputeInput,
    AdaptiveComputeReceipt,
    ComplexityReason,
    ComputeRoute,
    ImportanceBasis,
    LargerModelEscalation,
    RouteDeploymentStatus,
    ServingBenchmarkDecision,
    accepted_serving_benchmark_decision,
    choose_adaptive_compute,
)

ACCESSION = "0000000001-26-000001"
SOURCE_HASH = sha256(b"authoritative filing").hexdigest()
EVIDENCE_HASH = sha256(b"bounded evidence").hexdigest()


def observations(
    *,
    relevant: bool,
    material: bool,
    ambiguous: bool = False,
    complexity: tuple[ComplexityReason, ...] = (),
    importance: ImportanceBasis = ImportanceBasis.NOT_ESTABLISHED,
) -> AdaptiveComputeInput:
    return AdaptiveComputeInput(
        accession_number=ACCESSION,
        source_content_sha256=SOURCE_HASH,
        evidence_sha256=EVIDENCE_HASH if relevant else None,
        evidence_characters=16 if relevant else 0,
        tier_decision=choose_tier(
            research_relevant=relevant,
            material_terms=material,
            ambiguous=ambiguous,
            context_chars=16 if relevant else 0,
        ),
        complexity_reasons=complexity,
        importance_basis=importance,
    )


def test_benchmark_decision_retains_only_measured_ollama_qwen_path() -> None:
    decision = accepted_serving_benchmark_decision()

    assert decision.ollama_qwen3_4b == "retained"
    assert decision.llama_cpp_cpu == "rejected"
    assert decision.llama_cpp_vulkan == "rejected"
    assert decision.qwen3_8b == "not_assessed"
    assert decision.gemma == "prohibited"
    assert decision.maximum_concurrent_inference == 1
    assert decision.richer_evidence_runtime_switch_authorized is False
    assert decision.larger_model_authorized is False


def test_deterministic_reject_allocates_no_model_resources() -> None:
    receipt = choose_adaptive_compute(observations(relevant=False, material=False))

    assert receipt.route is ComputeRoute.NO_LLM
    assert receipt.provider == "none"
    assert receipt.model == "none"
    assert receipt.model_digest is None
    assert receipt.maximum_evidence_characters == 0
    assert receipt.maximum_context_tokens == 0
    assert receipt.maximum_output_tokens == 0
    assert receipt.deployment_status is RouteDeploymentStatus.CURRENT_RUNTIME


def test_normal_relevant_event_retains_current_bounded_qwen() -> None:
    receipt = choose_adaptive_compute(observations(relevant=True, material=True))

    assert receipt.route is ComputeRoute.QWEN3_4B_BOUNDED
    assert receipt.provider == "ollama"
    assert receipt.model == "qwen3:4b"
    assert receipt.maximum_evidence_characters == 3_600
    assert receipt.maximum_context_tokens == 4_096
    assert receipt.maximum_output_tokens == 768
    assert receipt.larger_model_escalation is LargerModelEscalation.NOT_REQUESTED
    assert receipt.deployment_status is RouteDeploymentStatus.CURRENT_RUNTIME


def test_complex_event_is_shadow_only_and_cannot_select_a_larger_model() -> None:
    receipt = choose_adaptive_compute(
        observations(
            relevant=True,
            material=True,
            complexity=(ComplexityReason.MULTIPLE_MATERIAL_SECTIONS,),
        )
    )

    assert receipt.route is ComputeRoute.QWEN3_4B_RICHER_BOUNDED
    assert receipt.model == "qwen3:4b"
    assert receipt.evidence_profile == "richer_bounded_shadow"
    assert receipt.deployment_status is RouteDeploymentStatus.SHADOW_ONLY
    assert receipt.larger_model_escalation is LargerModelEscalation.UNAVAILABLE_NO_BENEFIT_EVIDENCE
    assert receipt.gemma_enabled is False
    assert receipt.maximum_concurrent_inference == 1


def test_important_ambiguous_case_falls_back_to_shadow_qwen4_not_unmeasured_8b() -> None:
    receipt = choose_adaptive_compute(
        observations(
            relevant=True,
            material=False,
            ambiguous=True,
            complexity=(ComplexityReason.AMBIGUOUS_EVIDENCE,),
            importance=ImportanceBasis.FOCUS_MATERIAL_EVENT,
        )
    )

    assert receipt.route is ComputeRoute.QWEN3_4B_RICHER_BOUNDED
    assert receipt.model == "qwen3:4b"
    assert receipt.larger_model_escalation is LargerModelEscalation.UNAVAILABLE_NO_BENEFIT_EVIDENCE


def test_ambiguous_tier_requires_matching_closed_complexity_reason() -> None:
    with pytest.raises(ValidationError, match="matching complexity reason"):
        observations(relevant=True, material=False, ambiguous=True)


def test_richer_route_cannot_be_marked_as_deployed() -> None:
    receipt = choose_adaptive_compute(
        observations(
            relevant=True,
            material=True,
            complexity=(ComplexityReason.AMENDMENT_MATERIAL_DELTA,),
        )
    )
    payload = receipt.model_dump()
    payload["deployment_status"] = RouteDeploymentStatus.CURRENT_RUNTIME

    with pytest.raises(ValidationError, match="shadow-only"):
        AdaptiveComputeReceipt.model_validate(payload)


def test_same_inputs_and_benchmark_replay_to_identical_receipt() -> None:
    inputs = observations(relevant=True, material=True)

    assert (
        choose_adaptive_compute(inputs).model_dump_json()
        == choose_adaptive_compute(inputs).model_dump_json()
    )


def test_receipt_identity_binds_complexity_importance_and_evidence_size() -> None:
    normal = choose_adaptive_compute(observations(relevant=True, material=True))
    complex_route = choose_adaptive_compute(
        observations(
            relevant=True,
            material=True,
            complexity=(ComplexityReason.MULTIPLE_MATERIAL_SECTIONS,),
        )
    )

    assert normal.routing_input_sha256 != complex_route.routing_input_sha256
    assert normal.receipt_id != complex_route.receipt_id

    payload = normal.model_dump()
    payload["evidence_characters"] = 15
    with pytest.raises(ValidationError, match="input fingerprint"):
        AdaptiveComputeReceipt.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("provider", "none"),
        ("maximum_context_tokens", 0),
        ("maximum_output_tokens", 1),
        ("evidence_profile", "none"),
    ),
)
def test_model_route_rejects_mixed_or_changed_runtime_envelope(field: str, value: object) -> None:
    receipt = choose_adaptive_compute(observations(relevant=True, material=True))
    payload = receipt.model_dump()
    payload[field] = value

    with pytest.raises(ValidationError, match="bounded accepted Qwen|current bounded Qwen"):
        AdaptiveComputeReceipt.model_validate(payload)


def test_no_model_input_cannot_claim_complexity_or_importance() -> None:
    tier = choose_tier(
        research_relevant=False,
        material_terms=False,
        context_chars=0,
    )
    with pytest.raises(ValidationError, match="no-model routing"):
        AdaptiveComputeInput(
            accession_number=ACCESSION,
            source_content_sha256=SOURCE_HASH,
            evidence_characters=0,
            tier_decision=tier,
            complexity_reasons=(ComplexityReason.MULTIPLE_MATERIAL_SECTIONS,),
        )


def test_benchmark_artifact_hashes_and_decision_identity_are_closed() -> None:
    decision = accepted_serving_benchmark_decision()
    payload = decision.model_dump()
    payload["package_set_sha256"] = "a" * 64
    with pytest.raises(ValidationError):
        ServingBenchmarkDecision.model_validate(payload)

    payload = decision.model_dump()
    payload["decision_id"] = "10000000-0000-4000-8000-000000000001"
    with pytest.raises(ValidationError, match="identity does not reconcile"):
        ServingBenchmarkDecision.model_validate(payload)


def test_receipt_contract_contains_no_source_or_model_content_fields() -> None:
    receipt = choose_adaptive_compute(observations(relevant=True, material=True))
    serialized = receipt.model_dump_json().casefold()

    for prohibited in (
        "prompt",
        "excerpt",
        "hypothesis",
        "response",
        "reasoning",
        "exception",
        "discord",
        "human",
    ):
        assert prohibited not in serialized
