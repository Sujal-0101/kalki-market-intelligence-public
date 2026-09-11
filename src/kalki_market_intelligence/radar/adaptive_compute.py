"""Benchmark-gated, shadow-only adaptive compute routing contracts."""

from __future__ import annotations

import json
from enum import StrEnum
from hashlib import sha256
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, model_validator

from kalki_market_intelligence.contracts.common import ContractModel, Sha256Hex
from kalki_market_intelligence.forensics.tiers import EscalationReason, TierDecision

ADAPTIVE_COMPUTE_POLICY_VERSION: Literal["1.0.0"] = "1.0.0"
SERVING_BENCHMARK_DECISION_VERSION: Literal["1.0.0"] = "1.0.0"
QWEN3_4B_DIGEST: Literal["359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7"] = (
    "359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7"
)
SERVING_PACKAGE_SET_SHA256: Literal[
    "395402cab54b543aec994d977660a7167f1cdf9836423be51fe6f9c22d633f10"
] = "395402cab54b543aec994d977660a7167f1cdf9836423be51fe6f9c22d633f10"
SERVING_REPORT_SHA256S: tuple[
    Literal["3b09a007b3308ca54d2f05a9160efbd6d4f744149f6f3ed7ffc9d4de01808448"],
    Literal["dda018ef96b75bb8c9bd6d7e6a39026886e15b64744370481cdbc4ad37cde89c"],
    Literal["8d5847317dd73967b5db241848db49d624444015799c61dccd805c44fd76359b"],
] = (
    "3b09a007b3308ca54d2f05a9160efbd6d4f744149f6f3ed7ffc9d4de01808448",
    "dda018ef96b75bb8c9bd6d7e6a39026886e15b64744370481cdbc4ad37cde89c",
    "8d5847317dd73967b5db241848db49d624444015799c61dccd805c44fd76359b",
)


class ComputeRoute(StrEnum):
    NO_LLM = "no_llm"
    QWEN3_4B_BOUNDED = "qwen3_4b_bounded"
    QWEN3_4B_RICHER_BOUNDED = "qwen3_4b_richer_bounded"


class ComplexityReason(StrEnum):
    MULTIPLE_MATERIAL_SECTIONS = "multiple_material_sections"
    AMENDMENT_MATERIAL_DELTA = "amendment_material_delta"
    NUMERIC_CONTEXT_AMBIGUITY = "numeric_context_ambiguity"
    AMBIGUOUS_EVIDENCE = "ambiguous_evidence"
    DETERMINISTIC_CONTRADICTION = "deterministic_contradiction"
    PUBLICATION_CANDIDATE = "publication_candidate"


class ImportanceBasis(StrEnum):
    NOT_ESTABLISHED = "not_established"
    FOCUS_MATERIAL_EVENT = "focus_material_event"
    DETERMINISTIC_CONTRADICTION = "deterministic_contradiction"
    PUBLICATION_CANDIDATE = "publication_candidate"


class RouteDeploymentStatus(StrEnum):
    CURRENT_RUNTIME = "current_runtime"
    SHADOW_ONLY = "shadow_only"


class LargerModelEscalation(StrEnum):
    NOT_REQUESTED = "not_requested"
    UNAVAILABLE_NO_BENEFIT_EVIDENCE = "unavailable_no_benefit_evidence"


class ServingBenchmarkDecision(ContractModel):
    """Content-free decision derived from the accepted identical-package replay."""

    decision_id: UUID
    package_set_sha256: Literal["395402cab54b543aec994d977660a7167f1cdf9836423be51fe6f9c22d633f10"]
    report_sha256s: tuple[
        Literal["3b09a007b3308ca54d2f05a9160efbd6d4f744149f6f3ed7ffc9d4de01808448"],
        Literal["dda018ef96b75bb8c9bd6d7e6a39026886e15b64744370481cdbc4ad37cde89c"],
        Literal["8d5847317dd73967b5db241848db49d624444015799c61dccd805c44fd76359b"],
    ]
    ollama_qwen3_4b: Literal["retained"] = "retained"
    llama_cpp_cpu: Literal["rejected"] = "rejected"
    llama_cpp_vulkan: Literal["rejected"] = "rejected"
    qwen3_8b: Literal["not_assessed"] = "not_assessed"
    gemma: Literal["prohibited"] = "prohibited"
    accepted_model: Literal["qwen3:4b"] = "qwen3:4b"
    accepted_model_digest: Literal[
        "359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7"
    ]
    accepted_provider: Literal["ollama"] = "ollama"
    accepted_placement: Literal["cpu"] = "cpu"
    maximum_context_tokens: Literal[4096] = 4_096
    maximum_output_tokens: Literal[768] = 768
    maximum_evidence_characters: Literal[3600] = 3_600
    maximum_concurrent_inference: Literal[1] = 1
    richer_evidence_runtime_switch_authorized: Literal[False] = False
    larger_model_authorized: Literal[False] = False
    decision_version: Literal["1.0.0"] = SERVING_BENCHMARK_DECISION_VERSION

    @model_validator(mode="after")
    def identity_reconciles(self) -> ServingBenchmarkDecision:
        expected = _benchmark_decision_id(
            self.package_set_sha256,
            self.report_sha256s,
            self.accepted_model_digest,
        )
        if self.decision_id != expected:
            raise ValueError("serving benchmark decision identity does not reconcile")
        return self


class AdaptiveComputeInput(ContractModel):
    """Deterministic, content-free observations available before model execution."""

    accession_number: str = Field(pattern=r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
    source_content_sha256: Sha256Hex
    evidence_sha256: Sha256Hex | None = None
    evidence_characters: int = Field(ge=0, le=3_600)
    tier_decision: TierDecision
    complexity_reasons: tuple[ComplexityReason, ...] = Field(default=(), max_length=6)
    importance_basis: ImportanceBasis = ImportanceBasis.NOT_ESTABLISHED

    @model_validator(mode="after")
    def evidence_and_reasons_reconcile(self) -> AdaptiveComputeInput:
        if bool(self.evidence_sha256) != bool(self.evidence_characters):
            raise ValueError("adaptive compute evidence hash and size must be present together")
        if self.tier_decision.estimated_context_chars != self.evidence_characters:
            raise ValueError("tier context size must reconcile to bounded routing evidence")
        if len(set(self.complexity_reasons)) != len(self.complexity_reasons):
            raise ValueError("adaptive compute complexity reasons must be unique")
        if self.tier_decision.requires_model and self.evidence_sha256 is None:
            raise ValueError("model routing requires bounded evidence lineage")
        if not self.tier_decision.requires_model and (
            self.complexity_reasons or self.importance_basis is not ImportanceBasis.NOT_ESTABLISHED
        ):
            raise ValueError("no-model routing cannot claim model complexity or importance")
        required_reason = {
            EscalationReason.AMBIGUOUS_EVIDENCE: ComplexityReason.AMBIGUOUS_EVIDENCE,
            EscalationReason.DETERMINISTIC_CONTRADICTION: (
                ComplexityReason.DETERMINISTIC_CONTRADICTION
            ),
            EscalationReason.PUBLICATION_REVIEW: ComplexityReason.PUBLICATION_CANDIDATE,
        }.get(self.tier_decision.reason)
        if self.tier_decision.requires_model and required_reason is not None:
            if required_reason not in self.complexity_reasons:
                raise ValueError("tier decision requires its matching complexity reason")
        allowed_importance_reasons = {
            ImportanceBasis.FOCUS_MATERIAL_EVENT: {
                EscalationReason.MATERIAL_EVENT,
                EscalationReason.AMBIGUOUS_EVIDENCE,
            },
            ImportanceBasis.DETERMINISTIC_CONTRADICTION: {
                EscalationReason.DETERMINISTIC_CONTRADICTION
            },
            ImportanceBasis.PUBLICATION_CANDIDATE: {EscalationReason.PUBLICATION_REVIEW},
        }.get(self.importance_basis)
        if (
            allowed_importance_reasons is not None
            and self.tier_decision.reason not in allowed_importance_reasons
        ):
            raise ValueError("importance basis must match the deterministic tier reason")
        return self


class AdaptiveComputeReceipt(ContractModel):
    """Replay-stable shadow decision that cannot itself invoke a model."""

    receipt_id: UUID
    accession_number: str = Field(pattern=r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
    source_content_sha256: Sha256Hex
    evidence_sha256: Sha256Hex | None = None
    evidence_characters: int = Field(ge=0, le=3_600)
    tier_decision_sha256: Sha256Hex
    complexity_reasons: tuple[ComplexityReason, ...] = Field(max_length=6)
    importance_basis: ImportanceBasis
    route: ComputeRoute
    deployment_status: RouteDeploymentStatus
    provider: Literal["none", "ollama"]
    model: Literal["none", "qwen3:4b"]
    model_digest: (
        Literal["359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7"] | None
    ) = None
    evidence_profile: Literal["none", "accepted_bounded", "richer_bounded_shadow"]
    maximum_evidence_characters: int = Field(ge=0, le=3_600)
    maximum_context_tokens: int = Field(ge=0, le=4_096)
    maximum_output_tokens: int = Field(ge=0, le=768)
    maximum_concurrent_inference: Literal[1] = 1
    gemma_enabled: Literal[False] = False
    larger_model_escalation: LargerModelEscalation
    benchmark_decision_id: UUID
    routing_input_sha256: Sha256Hex
    policy_version: Literal["1.0.0"] = ADAPTIVE_COMPUTE_POLICY_VERSION

    @model_validator(mode="after")
    def route_is_safe_and_consistent(self) -> AdaptiveComputeReceipt:
        no_model = self.route is ComputeRoute.NO_LLM
        if bool(self.evidence_sha256) != bool(self.evidence_characters):
            raise ValueError("receipt evidence hash and size must be present together")
        expected_input_sha256 = _routing_input_sha256(
            accession_number=self.accession_number,
            source_content_sha256=self.source_content_sha256,
            evidence_sha256=self.evidence_sha256,
            evidence_characters=self.evidence_characters,
            tier_decision_sha256=self.tier_decision_sha256,
            complexity_reasons=self.complexity_reasons,
            importance_basis=self.importance_basis,
        )
        if self.routing_input_sha256 != expected_input_sha256:
            raise ValueError("adaptive compute input fingerprint does not reconcile")
        expected_receipt_id = _adaptive_compute_receipt_id(
            routing_input_sha256=self.routing_input_sha256,
            benchmark_decision_id=self.benchmark_decision_id,
        )
        if self.receipt_id != expected_receipt_id:
            raise ValueError("adaptive compute receipt identity does not reconcile")
        if no_model:
            if (
                self.provider != "none"
                or self.model != "none"
                or self.model_digest is not None
                or self.evidence_profile != "none"
                or self.evidence_sha256 is not None
                or self.evidence_characters != 0
                or self.maximum_evidence_characters != 0
                or self.maximum_context_tokens != 0
                or self.maximum_output_tokens != 0
                or self.deployment_status is not RouteDeploymentStatus.CURRENT_RUNTIME
                or self.larger_model_escalation is not LargerModelEscalation.NOT_REQUESTED
            ):
                raise ValueError("no-LLM route must allocate no model or evidence resources")
            return self
        if (
            self.provider != "ollama"
            or self.model != "qwen3:4b"
            or self.model_digest != QWEN3_4B_DIGEST
            or self.evidence_sha256 is None
            or self.evidence_characters == 0
            or self.maximum_evidence_characters != 3_600
            or self.maximum_context_tokens != 4_096
            or self.maximum_output_tokens != 768
        ):
            raise ValueError("model routes must retain the bounded accepted Qwen3 4B envelope")
        if self.route is ComputeRoute.QWEN3_4B_RICHER_BOUNDED and (
            self.deployment_status is not RouteDeploymentStatus.SHADOW_ONLY
            or self.evidence_profile != "richer_bounded_shadow"
            or self.larger_model_escalation
            is not LargerModelEscalation.UNAVAILABLE_NO_BENEFIT_EVIDENCE
        ):
            raise ValueError("richer evidence routing remains shadow-only")
        if self.route is ComputeRoute.QWEN3_4B_BOUNDED and (
            self.deployment_status is not RouteDeploymentStatus.CURRENT_RUNTIME
            or self.evidence_profile != "accepted_bounded"
            or self.larger_model_escalation is not LargerModelEscalation.NOT_REQUESTED
        ):
            raise ValueError("normal route must retain the current bounded Qwen path")
        return self


def _benchmark_decision_id(
    package_set_sha256: str,
    report_sha256s: tuple[str, ...],
    model_digest: str,
) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        ":".join(
            (
                "kalki-serving-benchmark-decision",
                SERVING_BENCHMARK_DECISION_VERSION,
                package_set_sha256,
                *report_sha256s,
                model_digest,
            )
        ),
    )


def accepted_serving_benchmark_decision() -> ServingBenchmarkDecision:
    """Return the closed decision backed by the retained local report hashes."""

    return ServingBenchmarkDecision(
        decision_id=_benchmark_decision_id(
            SERVING_PACKAGE_SET_SHA256,
            SERVING_REPORT_SHA256S,
            QWEN3_4B_DIGEST,
        ),
        package_set_sha256=SERVING_PACKAGE_SET_SHA256,
        report_sha256s=SERVING_REPORT_SHA256S,
        accepted_model_digest=QWEN3_4B_DIGEST,
    )


def _contract_sha256(value: ContractModel) -> str:
    encoded = json.dumps(
        value.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _routing_input_sha256(
    *,
    accession_number: str,
    source_content_sha256: str,
    evidence_sha256: str | None,
    evidence_characters: int,
    tier_decision_sha256: str,
    complexity_reasons: tuple[ComplexityReason, ...],
    importance_basis: ImportanceBasis,
) -> str:
    payload = {
        "accession_number": accession_number,
        "complexity_reasons": [item.value for item in complexity_reasons],
        "evidence_characters": evidence_characters,
        "evidence_sha256": evidence_sha256,
        "importance_basis": importance_basis.value,
        "policy_version": ADAPTIVE_COMPUTE_POLICY_VERSION,
        "source_content_sha256": source_content_sha256,
        "tier_decision_sha256": tier_decision_sha256,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def _adaptive_compute_receipt_id(*, routing_input_sha256: str, benchmark_decision_id: UUID) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        ":".join(
            (
                "kalki-adaptive-compute",
                ADAPTIVE_COMPUTE_POLICY_VERSION,
                routing_input_sha256,
                benchmark_decision_id.hex,
            )
        ),
    )


def choose_adaptive_compute(
    observations: AdaptiveComputeInput,
    *,
    benchmark: ServingBenchmarkDecision | None = None,
) -> AdaptiveComputeReceipt:
    """Choose the least expensive benchmark-authorized route without executing it."""

    decision = benchmark or accepted_serving_benchmark_decision()
    tier_hash = _contract_sha256(observations.tier_decision)
    if not observations.tier_decision.requires_model:
        route = ComputeRoute.NO_LLM
        deployment = RouteDeploymentStatus.CURRENT_RUNTIME
        provider: Literal["none", "ollama"] = "none"
        model: Literal["none", "qwen3:4b"] = "none"
        model_digest = None
        evidence_profile: Literal["none", "accepted_bounded", "richer_bounded_shadow"] = "none"
        evidence_limit = context_limit = output_limit = 0
        larger = LargerModelEscalation.NOT_REQUESTED
    elif observations.complexity_reasons or (
        observations.importance_basis is not ImportanceBasis.NOT_ESTABLISHED
    ):
        route = ComputeRoute.QWEN3_4B_RICHER_BOUNDED
        deployment = RouteDeploymentStatus.SHADOW_ONLY
        provider = "ollama"
        model = "qwen3:4b"
        model_digest = decision.accepted_model_digest
        evidence_profile = "richer_bounded_shadow"
        evidence_limit = decision.maximum_evidence_characters
        context_limit = decision.maximum_context_tokens
        output_limit = decision.maximum_output_tokens
        larger = LargerModelEscalation.UNAVAILABLE_NO_BENEFIT_EVIDENCE
    else:
        route = ComputeRoute.QWEN3_4B_BOUNDED
        deployment = RouteDeploymentStatus.CURRENT_RUNTIME
        provider = "ollama"
        model = "qwen3:4b"
        model_digest = decision.accepted_model_digest
        evidence_profile = "accepted_bounded"
        evidence_limit = decision.maximum_evidence_characters
        context_limit = decision.maximum_context_tokens
        output_limit = decision.maximum_output_tokens
        larger = LargerModelEscalation.NOT_REQUESTED
    routing_input_sha256 = _routing_input_sha256(
        accession_number=observations.accession_number,
        source_content_sha256=observations.source_content_sha256,
        evidence_sha256=observations.evidence_sha256,
        evidence_characters=observations.evidence_characters,
        tier_decision_sha256=tier_hash,
        complexity_reasons=observations.complexity_reasons,
        importance_basis=observations.importance_basis,
    )
    receipt_id = _adaptive_compute_receipt_id(
        routing_input_sha256=routing_input_sha256,
        benchmark_decision_id=decision.decision_id,
    )
    return AdaptiveComputeReceipt(
        receipt_id=receipt_id,
        accession_number=observations.accession_number,
        source_content_sha256=observations.source_content_sha256,
        evidence_sha256=observations.evidence_sha256,
        evidence_characters=observations.evidence_characters,
        tier_decision_sha256=tier_hash,
        complexity_reasons=observations.complexity_reasons,
        importance_basis=observations.importance_basis,
        route=route,
        deployment_status=deployment,
        provider=provider,
        model=model,
        model_digest=model_digest,
        evidence_profile=evidence_profile,
        maximum_evidence_characters=evidence_limit,
        maximum_context_tokens=context_limit,
        maximum_output_tokens=output_limit,
        larger_model_escalation=larger,
        benchmark_decision_id=decision.decision_id,
        routing_input_sha256=routing_input_sha256,
    )
