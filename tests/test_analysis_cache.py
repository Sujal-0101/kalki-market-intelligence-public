"""Fail-closed analysis cache and amendment-delta tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from kalki_market_intelligence.radar.analysis_cache import (
    AcceptedAnalysisCacheReceipt,
    AmendmentDeltaDisposition,
    AmendmentDeltaReason,
    AmendmentEvidenceManifest,
    AmendmentSectionFingerprint,
    AnalysisCacheBoundary,
    CacheMissReason,
    CacheReuseDisposition,
    FilingDeltaRelationship,
    build_accepted_cache_receipt,
    build_amendment_manifest,
    build_analysis_cache_key,
    decide_amendment_delta,
    decide_cache_reuse,
)

NOW = datetime(2026, 8, 31, 9, tzinfo=UTC)


def boundary(**updates: object) -> AnalysisCacheBoundary:
    values: dict[str, object] = {
        "accession_number": "0000789019-26-000042",
        "source_content_sha256": "a" * 64,
        "evidence_sha256": "b" * 64,
        "evidence_manifest_sha256": "c" * 64,
        "event_fingerprint_manifest_sha256": "9" * 64,
        "evidence_characters": 1_200,
        "tier_decision_sha256": "d" * 64,
        "event_novelty_ruleset_version": "1.0.0",
        "evidence_budget_version": "1.0.0",
        "extraction_ruleset_version": "radar-v1",
    }
    values.update(updates)
    return AnalysisCacheBoundary.model_validate(values)


def receipt_for(
    value: AnalysisCacheBoundary | None = None,
) -> AcceptedAnalysisCacheReceipt:
    if value is None:
        value = boundary()
    key = build_analysis_cache_key(value)
    return build_accepted_cache_receipt(
        key,
        output_sha256="e" * 64,
        knowledge_cutoff_at=NOW,
        validated_at=NOW + timedelta(minutes=2),
    )


def section(selector: str, digest: str, size: int = 500) -> AmendmentSectionFingerprint:
    return AmendmentSectionFingerprint(
        selector=selector, evidence_sha256=digest * 64, evidence_characters=size
    )


def manifest(
    *,
    accession: str,
    form: str,
    when: datetime,
    sections: tuple[AmendmentSectionFingerprint, ...],
    cik: str = "789019",
    event_novelty_ruleset_version: str = "event-novelty-v1",
    evidence_budget_version: str = "1.0.0",
    extraction_ruleset_version: str = "radar-v1",
) -> AmendmentEvidenceManifest:
    return build_amendment_manifest(
        accession_number=accession,
        cik=cik,
        filing_form=form,
        source_content_sha256=("1" if form.endswith("/A") else "0") * 64,
        available_at=when,
        retrieved_at=when + timedelta(minutes=1),
        sections=sections,
        event_novelty_ruleset_version=event_novelty_ruleset_version,
        evidence_budget_version=evidence_budget_version,
        extraction_ruleset_version=extraction_ruleset_version,
    )


def test_exact_validated_boundary_is_the_only_reusable_output() -> None:
    key = build_analysis_cache_key(boundary())
    cached = receipt_for()

    decision = decide_cache_reuse(
        key, knowledge_cutoff_at=NOW + timedelta(hours=1), candidate=cached
    )

    assert decision.disposition is CacheReuseDisposition.EXACT_REUSE
    assert decision.reusable_output_sha256 == "e" * 64
    assert decision.miss_reasons == ()


@pytest.mark.parametrize(
    ("update", "reason"),
    [
        ({"source_content_sha256": "f" * 64}, CacheMissReason.SOURCE_CHANGED),
        ({"evidence_sha256": "f" * 64}, CacheMissReason.EVIDENCE_CHANGED),
        (
            {"evidence_manifest_sha256": "f" * 64},
            CacheMissReason.EVIDENCE_MANIFEST_CHANGED,
        ),
        (
            {"event_fingerprint_manifest_sha256": "f" * 64},
            CacheMissReason.EVENT_FINGERPRINT_CHANGED,
        ),
        (
            {"event_novelty_ruleset_version": "1.0.1"},
            CacheMissReason.RULESET_CHANGED,
        ),
        ({"evidence_budget_version": "1.0.1"}, CacheMissReason.RULESET_CHANGED),
        ({"extraction_ruleset_version": "radar-v2"}, CacheMissReason.RULESET_CHANGED),
        ({"tier_decision_sha256": "f" * 64}, CacheMissReason.TIER_DECISION_CHANGED),
    ],
)
def test_any_supported_boundary_change_fails_cache_reuse(
    update: dict[str, object], reason: CacheMissReason
) -> None:
    current = build_analysis_cache_key(boundary(**update))

    decision = decide_cache_reuse(
        current,
        knowledge_cutoff_at=NOW + timedelta(hours=1),
        candidate=receipt_for(),
    )

    assert decision.disposition is CacheReuseDisposition.MISS_BOUNDARY_CHANGED
    assert reason in decision.miss_reasons
    assert decision.reusable_output_sha256 is None


def test_candidate_validated_after_cutoff_is_never_reused() -> None:
    decision = decide_cache_reuse(
        build_analysis_cache_key(boundary()),
        knowledge_cutoff_at=NOW + timedelta(minutes=1),
        candidate=receipt_for(),
    )

    assert decision.disposition is CacheReuseDisposition.MISS_FUTURE_RESULT
    assert decision.miss_reasons == (CacheMissReason.CACHED_AFTER_CUTOFF,)


def test_mutated_receipt_identity_and_fingerprint_fail_validation() -> None:
    cached = receipt_for()
    with pytest.raises(ValidationError, match="fingerprint"):
        cached.model_copy(update={"fingerprint": "f" * 64}, deep=True).__class__.model_validate(
            {**cached.model_dump(), "fingerprint": "f" * 64}
        )
    with pytest.raises(ValidationError, match="identity"):
        cached.__class__.model_validate({**cached.model_dump(), "output_sha256": "f" * 64})


def test_reliable_amendment_selects_only_added_or_modified_current_sections() -> None:
    prior = manifest(
        accession="0000789019-26-000040",
        form="10-Q",
        when=NOW,
        sections=(section("item:1", "a"), section("item:2", "b")),
    )
    current = manifest(
        accession="0000789019-26-000041",
        form="10-Q/A",
        when=NOW + timedelta(hours=1),
        sections=(
            section("item:1", "a"),
            section("item:2", "c", 700),
            section("item:4", "d", 400),
        ),
    )

    decision = decide_amendment_delta(prior, current)

    assert decision.disposition is AmendmentDeltaDisposition.DELTA_READY
    assert decision.changed_selectors == ("item:2", "item:4")
    assert decision.delta_characters == 1_100
    assert decision.delta_manifest_sha256 is not None


def test_removed_relevant_section_requires_full_reanalysis() -> None:
    prior = manifest(
        accession="0000789019-26-000040",
        form="8-K",
        when=NOW,
        sections=(section("item:1.01", "a"), section("item:3.01", "b")),
    )
    current = manifest(
        accession="0000789019-26-000041",
        form="8-K/A",
        when=NOW + timedelta(hours=1),
        sections=(section("item:1.01", "c"),),
    )

    decision = decide_amendment_delta(prior, current)

    assert decision.disposition is AmendmentDeltaDisposition.FULL_REANALYSIS
    assert decision.reason is AmendmentDeltaReason.REMOVED_RELEVANT_SECTION
    assert decision.removed_selectors == ("item:3.01",)
    assert decision.delta_manifest_sha256 is None


def test_missing_alignment_or_oversized_delta_requires_full_reanalysis() -> None:
    prior_missing = manifest(accession="0000789019-26-000040", form="10-Q", when=NOW, sections=())
    current = manifest(
        accession="0000789019-26-000041",
        form="10-Q/A",
        when=NOW + timedelta(hours=1),
        sections=(section("item:2", "b"),),
    )
    missing = decide_amendment_delta(prior_missing, current)
    assert missing.disposition is AmendmentDeltaDisposition.FULL_REANALYSIS
    assert missing.reason is AmendmentDeltaReason.MISSING_SECTION_MANIFEST

    prior = manifest(
        accession="0000789019-26-000040",
        form="10-Q",
        when=NOW,
        sections=(section("item:1", "a"), section("item:2", "b")),
    )
    oversized = manifest(
        accession="0000789019-26-000041",
        form="10-Q/A",
        when=NOW + timedelta(hours=1),
        sections=(section("item:1", "c", 2_000), section("item:2", "d", 2_000)),
    )
    too_large = decide_amendment_delta(prior, oversized)
    assert too_large.disposition is AmendmentDeltaDisposition.FULL_REANALYSIS
    assert too_large.reason is AmendmentDeltaReason.DELTA_EXCEEDS_BUDGET


def test_changed_ruleset_forces_full_reanalysis() -> None:
    prior = manifest(
        accession="0000789019-26-000040",
        form="10-Q",
        when=NOW,
        sections=(section("item:2", "a"),),
    )
    current = manifest(
        accession="0000789019-26-000041",
        form="10-Q/A",
        when=NOW + timedelta(hours=1),
        sections=(section("item:2", "b"),),
        evidence_budget_version="1.0.1",
    )

    decision = decide_amendment_delta(prior, current)

    assert decision.disposition is AmendmentDeltaDisposition.FULL_REANALYSIS
    assert decision.reason is AmendmentDeltaReason.RULESET_CHANGED
    assert decision.prior_manifest_sha256 == prior.manifest_sha256
    assert decision.current_manifest_sha256 == current.manifest_sha256


def test_successive_periodic_filing_can_select_a_reliable_delta() -> None:
    prior = manifest(
        accession="0000789019-26-000040",
        form="10-Q",
        when=NOW,
        sections=(section("item:1", "a"), section("item:2", "b")),
    )
    current = manifest(
        accession="0000789019-26-000041",
        form="10-Q",
        when=NOW + timedelta(days=90),
        sections=(section("item:1", "a"), section("item:2", "c", 700)),
    )

    decision = decide_amendment_delta(
        prior,
        current,
        relationship=FilingDeltaRelationship.SUCCESSIVE_PERIODIC_REPORT,
    )

    assert decision.disposition is AmendmentDeltaDisposition.DELTA_READY
    assert decision.relationship is FilingDeltaRelationship.SUCCESSIVE_PERIODIC_REPORT
    assert decision.changed_selectors == ("item:2",)
    assert decision.delta_characters == 700


def test_supported_prospectus_forms_can_share_a_conservative_delta_manifest() -> None:
    prior = manifest(
        accession="0000789019-26-000040",
        form="424B5",
        when=NOW,
        sections=(section("risks", "a"), section("issuance.dilution", "b")),
    )
    current = manifest(
        accession="0000789019-26-000041",
        form="424B3",
        when=NOW + timedelta(hours=1),
        sections=(section("risks", "c", 700), section("issuance.dilution", "b")),
    )

    decision = decide_amendment_delta(
        prior,
        current,
        relationship=FilingDeltaRelationship.PROSPECTUS_UPDATE,
    )

    assert decision.disposition is AmendmentDeltaDisposition.DELTA_READY
    assert decision.changed_selectors == ("risks",)
    assert decision.delta_characters == 700


def test_unchanged_selected_evidence_does_not_reuse_across_changed_source_boundary() -> None:
    sections = (section("item:1.01", "a"),)
    prior = manifest(accession="0000789019-26-000040", form="8-K", when=NOW, sections=sections)
    current = manifest(
        accession="0000789019-26-000041",
        form="8-K/A",
        when=NOW + timedelta(hours=1),
        sections=sections,
    )

    decision = decide_amendment_delta(prior, current)

    assert decision.disposition is AmendmentDeltaDisposition.NO_SELECTED_DELTA
    assert decision.reason is AmendmentDeltaReason.SELECTED_EVIDENCE_UNCHANGED
    assert decision.delta_manifest_sha256 is None


def test_unrelated_or_non_amendment_manifests_are_rejected() -> None:
    prior = manifest(
        accession="0000789019-26-000040",
        form="10-Q",
        when=NOW,
        sections=(section("item:2", "a"),),
    )
    unrelated = manifest(
        accession="0000000001-26-000041",
        form="10-Q/A",
        when=NOW + timedelta(hours=1),
        sections=(section("item:2", "b"),),
        cik="1",
    )
    with pytest.raises(ValueError, match="same canonical CIK"):
        decide_amendment_delta(prior, unrelated)

    not_amendment = manifest(
        accession="0000789019-26-000041",
        form="10-Q",
        when=NOW + timedelta(hours=1),
        sections=(section("item:2", "b"),),
    )
    with pytest.raises(ValueError, match="must be an amendment"):
        decide_amendment_delta(prior, not_amendment)
