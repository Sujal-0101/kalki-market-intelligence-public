"""Fail-closed analysis fingerprint reuse and amendment-delta contracts."""

from __future__ import annotations

import json
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
from kalki_market_intelligence.radar.contracts import AccessionNumber, CikText

ANALYSIS_CACHE_VERSION: Literal["1.0.0"] = "1.0.0"
AMENDMENT_DELTA_VERSION: Literal["1.1.0"] = "1.1.0"
QWEN3_4B_DIGEST: Literal["359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7"] = (
    "359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7"
)


class CacheReuseDisposition(StrEnum):
    EXACT_REUSE = "exact_reuse"
    MISS_NO_CANDIDATE = "miss_no_candidate"
    MISS_BOUNDARY_CHANGED = "miss_boundary_changed"
    MISS_FUTURE_RESULT = "miss_future_result"


class CacheMissReason(StrEnum):
    NO_CANDIDATE = "no_candidate"
    ACCESSION_CHANGED = "accession_changed"
    SOURCE_CHANGED = "source_changed"
    EVIDENCE_CHANGED = "evidence_changed"
    EVIDENCE_MANIFEST_CHANGED = "evidence_manifest_changed"
    EVENT_FINGERPRINT_CHANGED = "event_fingerprint_changed"
    TIER_DECISION_CHANGED = "tier_decision_changed"
    RULESET_CHANGED = "ruleset_changed"
    PROMPT_CHANGED = "prompt_changed"
    SCHEMA_CHANGED = "schema_changed"
    VALIDATOR_CHANGED = "validator_changed"
    MODEL_CHANGED = "model_changed"
    RESOURCE_ENVELOPE_CHANGED = "resource_envelope_changed"
    CACHED_AFTER_CUTOFF = "cached_after_cutoff"


class AnalysisCacheBoundary(ContractModel):
    """Every input and execution boundary that can affect accepted model output."""

    accession_number: AccessionNumber
    source_content_sha256: Sha256Hex
    evidence_sha256: Sha256Hex
    evidence_manifest_sha256: Sha256Hex
    event_fingerprint_manifest_sha256: Sha256Hex
    evidence_characters: int = Field(gt=0, le=3_600)
    tier_decision_sha256: Sha256Hex
    event_novelty_ruleset_version: str = Field(min_length=1, max_length=64)
    evidence_budget_version: str = Field(min_length=1, max_length=64)
    extraction_ruleset_version: str = Field(min_length=1, max_length=64)
    prompt_version: Literal["analyst-v2"] = "analyst-v2"
    output_schema_version: Literal["1.0.0"] = "1.0.0"
    validation_version: Literal["1.0.0"] = "1.0.0"
    provider: Literal["ollama"] = "ollama"
    model: Literal["qwen3:4b"] = "qwen3:4b"
    model_digest: Literal["359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7"] = (
        QWEN3_4B_DIGEST
    )
    analyst_roles: tuple[Literal["catalyst_analyst"], Literal["bull_bear_risk_analyst"]] = (
        "catalyst_analyst",
        "bull_bear_risk_analyst",
    )
    maximum_context_tokens: Literal[4096] = 4_096
    maximum_output_tokens: Literal[768] = 768
    maximum_concurrent_inference: Literal[1] = 1
    fingerprint_version: Literal["1.0.0"] = ANALYSIS_CACHE_VERSION


class AnalysisCacheKey(ContractModel):
    boundary: AnalysisCacheBoundary
    fingerprint: Sha256Hex

    @model_validator(mode="after")
    def fingerprint_reconciles(self) -> AnalysisCacheKey:
        if self.fingerprint != _boundary_fingerprint(self.boundary):
            raise ValueError("analysis cache fingerprint does not reconcile")
        return self


class AcceptedAnalysisCacheReceipt(ContractModel):
    """Content-free lineage for an already validated private analysis result."""

    receipt_id: UUID
    boundary: AnalysisCacheBoundary
    fingerprint: Sha256Hex
    output_sha256: Sha256Hex
    report_count: Literal[2] = 2
    validation_status: Literal["accepted"] = "accepted"
    knowledge_cutoff_at: UtcDatetime
    validated_at: UtcDatetime
    cache_version: Literal["1.0.0"] = ANALYSIS_CACHE_VERSION

    @model_validator(mode="after")
    def receipt_reconciles(self) -> AcceptedAnalysisCacheReceipt:
        expected_fingerprint = _boundary_fingerprint(self.boundary)
        if self.fingerprint != expected_fingerprint:
            raise ValueError("cache receipt boundary fingerprint does not reconcile")
        if self.validated_at < self.knowledge_cutoff_at:
            raise ValueError("cache receipt cannot be validated before its knowledge cutoff")
        expected_id = uuid5(
            NAMESPACE_URL,
            f"kalki:analysis-cache:{self.fingerprint}:{self.output_sha256}",
        )
        if self.receipt_id != expected_id:
            raise ValueError("cache receipt identity does not reconcile")
        return self


class CacheReuseDecision(ContractModel):
    disposition: CacheReuseDisposition
    current_fingerprint: Sha256Hex
    candidate_receipt_id: UUID | None = None
    reusable_output_sha256: Sha256Hex | None = None
    miss_reasons: tuple[CacheMissReason, ...] = Field(default=(), max_length=16)
    cache_version: Literal["1.0.0"] = ANALYSIS_CACHE_VERSION

    @model_validator(mode="after")
    def result_shape_reconciles(self) -> CacheReuseDecision:
        hit = self.disposition is CacheReuseDisposition.EXACT_REUSE
        if hit != bool(self.candidate_receipt_id and self.reusable_output_sha256):
            raise ValueError("exact reuse must reference one validated cached output")
        if hit == bool(self.miss_reasons):
            raise ValueError("cache hit and miss reasons are mutually exclusive")
        if len(set(self.miss_reasons)) != len(self.miss_reasons):
            raise ValueError("cache miss reasons must be unique")
        return self


class AmendmentSectionFingerprint(ContractModel):
    """One stable, relevant form section without retaining its text."""

    selector: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    evidence_sha256: Sha256Hex
    evidence_characters: int = Field(gt=0, le=20_000)


class AmendmentEvidenceManifest(ContractModel):
    accession_number: AccessionNumber
    cik: CikText
    filing_form: str = Field(min_length=1, max_length=32)
    source_content_sha256: Sha256Hex
    evidence_manifest_sha256: Sha256Hex
    manifest_sha256: Sha256Hex
    available_at: UtcDatetime
    retrieved_at: UtcDatetime
    sections: tuple[AmendmentSectionFingerprint, ...] = Field(max_length=64)
    event_novelty_ruleset_version: str = Field(min_length=1, max_length=64)
    evidence_budget_version: str = Field(min_length=1, max_length=64)
    extraction_ruleset_version: str = Field(min_length=1, max_length=64)
    manifest_version: Literal["1.1.0"] = AMENDMENT_DELTA_VERSION

    @model_validator(mode="after")
    def manifest_reconciles(self) -> Self:
        selectors = tuple(section.selector for section in self.sections)
        if len(set(selectors)) != len(selectors):
            raise ValueError("amendment section selectors must be unique")
        if selectors != tuple(sorted(selectors)):
            raise ValueError("amendment sections must use canonical selector order")
        if self.retrieved_at < self.available_at:
            raise ValueError("amendment evidence cannot be retrieved before availability")
        expected_evidence = _section_manifest_fingerprint(
            self.sections,
            event_novelty_ruleset_version=self.event_novelty_ruleset_version,
            evidence_budget_version=self.evidence_budget_version,
            extraction_ruleset_version=self.extraction_ruleset_version,
        )
        if self.evidence_manifest_sha256 != expected_evidence:
            raise ValueError("amendment evidence manifest fingerprint does not reconcile")
        if self.manifest_sha256 != _amendment_manifest_fingerprint(
            accession_number=self.accession_number,
            cik=self.cik,
            filing_form=self.filing_form,
            source_content_sha256=self.source_content_sha256,
            evidence_manifest_sha256=self.evidence_manifest_sha256,
            available_at=self.available_at,
            retrieved_at=self.retrieved_at,
            event_novelty_ruleset_version=self.event_novelty_ruleset_version,
            evidence_budget_version=self.evidence_budget_version,
            extraction_ruleset_version=self.extraction_ruleset_version,
        ):
            raise ValueError("amendment manifest fingerprint does not reconcile")
        return self


class FilingDeltaRelationship(StrEnum):
    AMENDMENT_OF = "amendment_of"
    SUCCESSIVE_PERIODIC_REPORT = "successive_periodic_report"
    PROSPECTUS_UPDATE = "prospectus_update"


_SUPPORTED_PROSPECTUS_FORMS = frozenset(
    {
        "S-1",
        "S-1/A",
        "S-3",
        "S-3/A",
        "424B2",
        "424B3",
        "424B4",
        "424B5",
        "424B7",
        "424B8",
        "424H",
        "FWP",
    }
)


class AmendmentDeltaDisposition(StrEnum):
    DELTA_READY = "delta_ready"
    NO_SELECTED_DELTA = "no_selected_delta"
    FULL_REANALYSIS = "full_reanalysis"


class AmendmentDeltaReason(StrEnum):
    RELIABLE_SECTION_DELTA = "reliable_section_delta"
    SELECTED_EVIDENCE_UNCHANGED = "selected_evidence_unchanged"
    MISSING_SECTION_MANIFEST = "missing_section_manifest"
    REMOVED_RELEVANT_SECTION = "removed_relevant_section"
    DELTA_EXCEEDS_BUDGET = "delta_exceeds_budget"
    RULESET_CHANGED = "ruleset_changed"


class AmendmentDeltaDecision(ContractModel):
    disposition: AmendmentDeltaDisposition
    relationship: FilingDeltaRelationship
    prior_accession_number: AccessionNumber
    current_accession_number: AccessionNumber
    prior_manifest_sha256: Sha256Hex
    current_manifest_sha256: Sha256Hex
    changed_selectors: tuple[str, ...] = Field(default=(), max_length=64)
    removed_selectors: tuple[str, ...] = Field(default=(), max_length=64)
    delta_manifest_sha256: Sha256Hex | None = None
    delta_characters: int = Field(default=0, ge=0, le=3_600)
    reason: AmendmentDeltaReason
    delta_version: Literal["1.1.0"] = AMENDMENT_DELTA_VERSION

    @model_validator(mode="after")
    def decision_shape_reconciles(self) -> Self:
        if self.prior_accession_number == self.current_accession_number:
            raise ValueError("filing delta requires distinct accessions")
        if self.prior_manifest_sha256 == self.current_manifest_sha256:
            raise ValueError("filing delta requires distinct bound manifests")
        if self.changed_selectors != tuple(sorted(set(self.changed_selectors))):
            raise ValueError("changed selectors must be unique and canonically ordered")
        if self.removed_selectors != tuple(sorted(set(self.removed_selectors))):
            raise ValueError("removed selectors must be unique and canonically ordered")
        if set(self.changed_selectors) & set(self.removed_selectors):
            raise ValueError("changed and removed selectors must be disjoint")
        ready = self.disposition is AmendmentDeltaDisposition.DELTA_READY
        if ready != bool(self.changed_selectors and self.delta_manifest_sha256):
            raise ValueError("ready amendment delta requires changed evidence")
        if ready != bool(self.delta_characters):
            raise ValueError("ready amendment delta requires a positive bounded size")
        if ready and self.removed_selectors:
            raise ValueError("removed relevant evidence requires full reanalysis")
        if not ready and self.changed_selectors:
            raise ValueError("non-delta decision cannot carry changed evidence")
        if not ready and (self.delta_manifest_sha256 is not None or self.delta_characters):
            raise ValueError("non-delta decision cannot carry a delta manifest")
        expected_reason = {
            AmendmentDeltaDisposition.DELTA_READY: AmendmentDeltaReason.RELIABLE_SECTION_DELTA,
            AmendmentDeltaDisposition.NO_SELECTED_DELTA: (
                AmendmentDeltaReason.SELECTED_EVIDENCE_UNCHANGED
            ),
        }.get(self.disposition)
        if expected_reason is not None and self.reason is not expected_reason:
            raise ValueError("amendment delta disposition and reason must reconcile")
        if self.disposition is AmendmentDeltaDisposition.FULL_REANALYSIS and self.reason not in {
            AmendmentDeltaReason.MISSING_SECTION_MANIFEST,
            AmendmentDeltaReason.REMOVED_RELEVANT_SECTION,
            AmendmentDeltaReason.DELTA_EXCEEDS_BUDGET,
            AmendmentDeltaReason.RULESET_CHANGED,
        }:
            raise ValueError("full reanalysis requires a fail-closed reason")
        return self


def build_analysis_cache_key(boundary: AnalysisCacheBoundary) -> AnalysisCacheKey:
    return AnalysisCacheKey(boundary=boundary, fingerprint=_boundary_fingerprint(boundary))


def build_accepted_cache_receipt(
    key: AnalysisCacheKey,
    *,
    output_sha256: Sha256Hex,
    knowledge_cutoff_at: UtcDatetime,
    validated_at: UtcDatetime,
) -> AcceptedAnalysisCacheReceipt:
    receipt_id = uuid5(
        NAMESPACE_URL,
        f"kalki:analysis-cache:{key.fingerprint}:{output_sha256}",
    )
    return AcceptedAnalysisCacheReceipt(
        receipt_id=receipt_id,
        boundary=key.boundary,
        fingerprint=key.fingerprint,
        output_sha256=output_sha256,
        knowledge_cutoff_at=knowledge_cutoff_at,
        validated_at=validated_at,
    )


def decide_cache_reuse(
    current: AnalysisCacheKey,
    *,
    knowledge_cutoff_at: UtcDatetime,
    candidate: AcceptedAnalysisCacheReceipt | None,
) -> CacheReuseDecision:
    knowledge_cutoff_at = normalize_utc(knowledge_cutoff_at)
    if candidate is None:
        return CacheReuseDecision(
            disposition=CacheReuseDisposition.MISS_NO_CANDIDATE,
            current_fingerprint=current.fingerprint,
            miss_reasons=(CacheMissReason.NO_CANDIDATE,),
        )
    if candidate.validated_at > knowledge_cutoff_at:
        return CacheReuseDecision(
            disposition=CacheReuseDisposition.MISS_FUTURE_RESULT,
            current_fingerprint=current.fingerprint,
            candidate_receipt_id=candidate.receipt_id,
            miss_reasons=(CacheMissReason.CACHED_AFTER_CUTOFF,),
        )
    reasons = _boundary_miss_reasons(current.boundary, candidate.boundary)
    if reasons:
        return CacheReuseDecision(
            disposition=CacheReuseDisposition.MISS_BOUNDARY_CHANGED,
            current_fingerprint=current.fingerprint,
            candidate_receipt_id=candidate.receipt_id,
            miss_reasons=reasons,
        )
    return CacheReuseDecision(
        disposition=CacheReuseDisposition.EXACT_REUSE,
        current_fingerprint=current.fingerprint,
        candidate_receipt_id=candidate.receipt_id,
        reusable_output_sha256=candidate.output_sha256,
    )


def build_amendment_manifest(
    *,
    accession_number: str,
    cik: str,
    filing_form: str,
    source_content_sha256: Sha256Hex,
    available_at: UtcDatetime,
    retrieved_at: UtcDatetime,
    sections: tuple[AmendmentSectionFingerprint, ...],
    event_novelty_ruleset_version: str,
    evidence_budget_version: str,
    extraction_ruleset_version: str,
) -> AmendmentEvidenceManifest:
    available_at = normalize_utc(available_at)
    retrieved_at = normalize_utc(retrieved_at)
    ordered = tuple(sorted(sections, key=lambda section: section.selector))
    evidence_manifest_sha256 = _section_manifest_fingerprint(
        ordered,
        event_novelty_ruleset_version=event_novelty_ruleset_version,
        evidence_budget_version=evidence_budget_version,
        extraction_ruleset_version=extraction_ruleset_version,
    )
    manifest_sha256 = _amendment_manifest_fingerprint(
        accession_number=accession_number,
        cik=cik,
        filing_form=filing_form,
        source_content_sha256=source_content_sha256,
        evidence_manifest_sha256=evidence_manifest_sha256,
        available_at=available_at,
        retrieved_at=retrieved_at,
        event_novelty_ruleset_version=event_novelty_ruleset_version,
        evidence_budget_version=evidence_budget_version,
        extraction_ruleset_version=extraction_ruleset_version,
    )
    return AmendmentEvidenceManifest(
        accession_number=accession_number,
        cik=cik,
        filing_form=filing_form,
        source_content_sha256=source_content_sha256,
        evidence_manifest_sha256=evidence_manifest_sha256,
        manifest_sha256=manifest_sha256,
        available_at=available_at,
        retrieved_at=retrieved_at,
        sections=ordered,
        event_novelty_ruleset_version=event_novelty_ruleset_version,
        evidence_budget_version=evidence_budget_version,
        extraction_ruleset_version=extraction_ruleset_version,
    )


def decide_amendment_delta(
    prior: AmendmentEvidenceManifest,
    current: AmendmentEvidenceManifest,
    *,
    relationship: FilingDeltaRelationship | None = None,
) -> AmendmentDeltaDecision:
    if prior.cik != current.cik:
        raise ValueError("amendment manifests must belong to the same canonical CIK")
    if current.accession_number == prior.accession_number:
        raise ValueError("amendment delta requires distinct accessions")
    prior_form = prior.filing_form.upper()
    current_form = current.filing_form.upper()
    prior_family = prior_form.removesuffix("/A")
    current_family = current_form.removesuffix("/A")
    if relationship is None:
        if not current_form.endswith("/A"):
            raise ValueError("current filing must be an amendment form")
        relationship = FilingDeltaRelationship.AMENDMENT_OF
    if relationship is FilingDeltaRelationship.AMENDMENT_OF and not current_form.endswith("/A"):
        raise ValueError("amendment relationship requires an amendment form")
    if relationship is FilingDeltaRelationship.AMENDMENT_OF:
        if current_family != prior_family:
            raise ValueError("amendment and prior form families must match")
    elif relationship is FilingDeltaRelationship.SUCCESSIVE_PERIODIC_REPORT:
        if current_form.endswith("/A") or current_family not in {"10-Q", "10-K"}:
            raise ValueError("successive filing delta requires a non-amendment 10-Q or 10-K")
        if current_family != prior_family:
            raise ValueError("successive periodic form families must match")
    elif relationship is FilingDeltaRelationship.PROSPECTUS_UPDATE:
        if (
            prior_form not in _SUPPORTED_PROSPECTUS_FORMS
            or current_form not in _SUPPORTED_PROSPECTUS_FORMS
        ):
            raise ValueError("prospectus delta requires two supported prospectus forms")
    else:
        raise ValueError("unsupported filing delta relationship")
    if current.available_at <= prior.available_at or current.retrieved_at <= prior.retrieved_at:
        raise ValueError("amendment must be available and retrieved after the prior filing")
    if _manifest_rules(prior) != _manifest_rules(current):
        return _full_delta_decision(
            prior,
            current,
            AmendmentDeltaReason.RULESET_CHANGED,
            relationship=relationship,
        )
    if not prior.sections or not current.sections:
        return _full_delta_decision(
            prior,
            current,
            AmendmentDeltaReason.MISSING_SECTION_MANIFEST,
            relationship=relationship,
        )
    prior_by_selector = {section.selector: section for section in prior.sections}
    current_by_selector = {section.selector: section for section in current.sections}
    removed = tuple(sorted(set(prior_by_selector) - set(current_by_selector)))
    changed = tuple(
        selector
        for selector, section in sorted(current_by_selector.items())
        if selector not in prior_by_selector
        or section.evidence_sha256 != prior_by_selector[selector].evidence_sha256
        or section.evidence_characters != prior_by_selector[selector].evidence_characters
    )
    if removed:
        return AmendmentDeltaDecision(
            disposition=AmendmentDeltaDisposition.FULL_REANALYSIS,
            relationship=relationship,
            prior_accession_number=prior.accession_number,
            current_accession_number=current.accession_number,
            prior_manifest_sha256=prior.manifest_sha256,
            current_manifest_sha256=current.manifest_sha256,
            removed_selectors=removed,
            reason=AmendmentDeltaReason.REMOVED_RELEVANT_SECTION,
        )
    if not changed:
        return AmendmentDeltaDecision(
            disposition=AmendmentDeltaDisposition.NO_SELECTED_DELTA,
            relationship=relationship,
            prior_accession_number=prior.accession_number,
            current_accession_number=current.accession_number,
            prior_manifest_sha256=prior.manifest_sha256,
            current_manifest_sha256=current.manifest_sha256,
            reason=AmendmentDeltaReason.SELECTED_EVIDENCE_UNCHANGED,
        )
    delta_characters = sum(current_by_selector[key].evidence_characters for key in changed)
    if delta_characters > 3_600:
        return _full_delta_decision(
            prior,
            current,
            AmendmentDeltaReason.DELTA_EXCEEDS_BUDGET,
            relationship=relationship,
        )
    delta_sha256 = _canonical_sha256(
        {
            "prior_accession_number": prior.accession_number,
            "current_accession_number": current.accession_number,
            "prior_manifest_sha256": prior.manifest_sha256,
            "current_manifest_sha256": current.manifest_sha256,
            "relationship": relationship.value,
            "sections": [current_by_selector[key].model_dump(mode="json") for key in changed],
            "delta_version": AMENDMENT_DELTA_VERSION,
        }
    )
    return AmendmentDeltaDecision(
        disposition=AmendmentDeltaDisposition.DELTA_READY,
        relationship=relationship,
        prior_accession_number=prior.accession_number,
        current_accession_number=current.accession_number,
        prior_manifest_sha256=prior.manifest_sha256,
        current_manifest_sha256=current.manifest_sha256,
        changed_selectors=changed,
        delta_manifest_sha256=delta_sha256,
        delta_characters=delta_characters,
        reason=AmendmentDeltaReason.RELIABLE_SECTION_DELTA,
    )


def _boundary_fingerprint(boundary: AnalysisCacheBoundary) -> str:
    return _canonical_sha256(boundary.model_dump(mode="json"))


def _section_manifest_fingerprint(
    sections: tuple[AmendmentSectionFingerprint, ...],
    *,
    event_novelty_ruleset_version: str,
    evidence_budget_version: str,
    extraction_ruleset_version: str,
) -> str:
    return _canonical_sha256(
        {
            "event_novelty_ruleset_version": event_novelty_ruleset_version,
            "evidence_budget_version": evidence_budget_version,
            "extraction_ruleset_version": extraction_ruleset_version,
            "manifest_version": AMENDMENT_DELTA_VERSION,
            "sections": [section.model_dump(mode="json") for section in sections],
        }
    )


def _amendment_manifest_fingerprint(
    *,
    accession_number: str,
    cik: str,
    filing_form: str,
    source_content_sha256: str,
    evidence_manifest_sha256: str,
    available_at: UtcDatetime,
    retrieved_at: UtcDatetime,
    event_novelty_ruleset_version: str,
    evidence_budget_version: str,
    extraction_ruleset_version: str,
) -> str:
    return _canonical_sha256(
        {
            "accession_number": accession_number,
            "available_at": normalize_utc(available_at).isoformat(),
            "cik": cik,
            "event_novelty_ruleset_version": event_novelty_ruleset_version,
            "evidence_budget_version": evidence_budget_version,
            "evidence_manifest_sha256": evidence_manifest_sha256,
            "extraction_ruleset_version": extraction_ruleset_version,
            "filing_form": filing_form,
            "manifest_version": AMENDMENT_DELTA_VERSION,
            "retrieved_at": normalize_utc(retrieved_at).isoformat(),
            "source_content_sha256": source_content_sha256,
        }
    )


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(payload.encode()).hexdigest()


def _boundary_miss_reasons(
    current: AnalysisCacheBoundary,
    cached: AnalysisCacheBoundary,
) -> tuple[CacheMissReason, ...]:
    groups: tuple[tuple[CacheMissReason, tuple[str, ...]], ...] = (
        (CacheMissReason.ACCESSION_CHANGED, ("accession_number",)),
        (CacheMissReason.SOURCE_CHANGED, ("source_content_sha256",)),
        (CacheMissReason.EVIDENCE_CHANGED, ("evidence_sha256", "evidence_characters")),
        (CacheMissReason.EVIDENCE_MANIFEST_CHANGED, ("evidence_manifest_sha256",)),
        (
            CacheMissReason.EVENT_FINGERPRINT_CHANGED,
            ("event_fingerprint_manifest_sha256",),
        ),
        (CacheMissReason.TIER_DECISION_CHANGED, ("tier_decision_sha256",)),
        (
            CacheMissReason.RULESET_CHANGED,
            (
                "event_novelty_ruleset_version",
                "evidence_budget_version",
                "extraction_ruleset_version",
                "fingerprint_version",
            ),
        ),
        (CacheMissReason.PROMPT_CHANGED, ("prompt_version", "analyst_roles")),
        (CacheMissReason.SCHEMA_CHANGED, ("output_schema_version",)),
        (CacheMissReason.VALIDATOR_CHANGED, ("validation_version",)),
        (CacheMissReason.MODEL_CHANGED, ("provider", "model", "model_digest")),
        (
            CacheMissReason.RESOURCE_ENVELOPE_CHANGED,
            (
                "maximum_context_tokens",
                "maximum_output_tokens",
                "maximum_concurrent_inference",
            ),
        ),
    )
    return tuple(
        reason
        for reason, fields in groups
        if any(getattr(current, field) != getattr(cached, field) for field in fields)
    )


def _full_delta_decision(
    prior: AmendmentEvidenceManifest,
    current: AmendmentEvidenceManifest,
    reason: AmendmentDeltaReason,
    *,
    relationship: FilingDeltaRelationship,
) -> AmendmentDeltaDecision:
    return AmendmentDeltaDecision(
        disposition=AmendmentDeltaDisposition.FULL_REANALYSIS,
        relationship=relationship,
        prior_accession_number=prior.accession_number,
        current_accession_number=current.accession_number,
        prior_manifest_sha256=prior.manifest_sha256,
        current_manifest_sha256=current.manifest_sha256,
        reason=reason,
    )


def _manifest_rules(manifest: AmendmentEvidenceManifest) -> tuple[str, str, str, str]:
    return (
        manifest.event_novelty_ruleset_version,
        manifest.evidence_budget_version,
        manifest.extraction_ruleset_version,
        manifest.manifest_version,
    )
