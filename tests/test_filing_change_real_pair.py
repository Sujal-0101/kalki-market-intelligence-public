"""Hash-anchored same-issuer Phase 42 prospectus-diff regression."""

from __future__ import annotations

import base64
import gzip
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

from kalki_market_intelligence.forensics.filing_change import (
    MAXIMUM_SELECTED_CHARACTERS,
    FilingChangeForm,
    FilingChangeKind,
    FilingChangeRelationship,
    FilingChangeSelectionReceipt,
    FilingChangeSnapshot,
    compare_and_select_filing_changes,
)
from kalki_market_intelligence.forensics.novelty import EVENT_NOVELTY_RULE_VERSION
from kalki_market_intelligence.providers.sec.filing_change import (
    build_amendment_manifest_from_filing_change_snapshot,
    build_snapshot_from_filing_change_extraction,
    extract_filing_change_sections,
)
from kalki_market_intelligence.radar.analysis_cache import (
    AmendmentDeltaDisposition,
    AmendmentDeltaReason,
    FilingDeltaRelationship,
    decide_amendment_delta,
)
from kalki_market_intelligence.radar.evidence_budget import EVIDENCE_BUDGET_VERSION

FIXTURES = Path(__file__).parent / "fixtures" / "financing"


@dataclass(frozen=True, slots=True)
class OfficialProspectus:
    fixture: str
    accession_number: str
    form: FilingChangeForm
    primary_document: str
    accepted_at: datetime
    source_sha256: str


CASES = (
    OfficialProspectus(
        fixture="kazia-2026-08-28-424b5-full.html.gz.b64",
        accession_number="0001213900-26-094600",
        form=FilingChangeForm.FORM_424_B_5,
        primary_document="ea0303789-424b5_kazia.htm",
        accepted_at=datetime(2026, 8, 28, 10, 8, 23, tzinfo=UTC),
        source_sha256="8b76cae442d93e1b36fe6132065e588a9a55d2e78bbc9560832e0f50e8e5bc93",
    ),
    OfficialProspectus(
        fixture="kazia-2026-08-31-424b5-full.html.gz.b64",
        accession_number="0001213900-26-095303",
        form=FilingChangeForm.FORM_424_B_5,
        primary_document="ea0303882-424b5_kazia.htm",
        accepted_at=datetime(2026, 8, 31, 10, 9, 18, tzinfo=UTC),
        source_sha256="798912e5b1bcab82503c85b752bc8d8196b03660f3395541b931fc9bc2d70032",
    ),
    OfficialProspectus(
        fixture="kazia-2026-08-31-424b3-02-full.html.gz.b64",
        accession_number="0001213900-26-095349",
        form=FilingChangeForm.FORM_424_B_3,
        primary_document="ea030397602-424b3_kazia.htm",
        accepted_at=datetime(2026, 8, 31, 11, 31, 11, tzinfo=UTC),
        source_sha256="f263598f902b4f38b79dab3468de7491b4fa122209aeef70aa3c65a3864a1660",
    ),
    OfficialProspectus(
        fixture="kazia-2026-08-31-424b3-03-full.html.gz.b64",
        accession_number="0001213900-26-095351",
        form=FilingChangeForm.FORM_424_B_3,
        primary_document="ea030397603-424b3_kazia.htm",
        accepted_at=datetime(2026, 8, 31, 11, 32, 11, tzinfo=UTC),
        source_sha256="34cc53fbbe17b853eed65d94080ec64257ea5306edc00421ff3ac43264749902",
    ),
)


def _snapshot(case: OfficialProspectus) -> FilingChangeSnapshot:
    body = gzip.decompress(base64.b64decode((FIXTURES / case.fixture).read_bytes()))
    assert sha256(body).hexdigest() == case.source_sha256
    extraction = extract_filing_change_sections(body, filing_form=case.form)
    accession_directory = case.accession_number.replace("-", "")
    return build_snapshot_from_filing_change_extraction(
        extraction,
        accession_number=case.accession_number,
        cik="1075880",
        filed_at=case.accepted_at.replace(hour=0, minute=0, second=0),
        available_at=case.accepted_at,
        retrieved_at=case.accepted_at + timedelta(minutes=1),
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/1075880/"
            f"{accession_directory}/{case.primary_document}"
        ),
    )


def _assert_exact_package_ranges(
    receipt: FilingChangeSelectionReceipt,
    previous: FilingChangeSnapshot,
    current: FilingChangeSnapshot,
) -> None:
    previous_sections = {section.selector: section for section in previous.sections}
    current_sections = {section.selector: section for section in current.sections}
    assert receipt.selected_characters <= MAXIMUM_SELECTED_CHARACTERS
    for excerpt in receipt.selected_excerpts:
        if excerpt.previous_text:
            section = previous_sections[excerpt.selector]
            assert excerpt.previous_start is not None
            assert excerpt.previous_end is not None
            assert section.text[excerpt.previous_start : excerpt.previous_end] == (
                excerpt.previous_text
            )
            assert sha256(excerpt.previous_text.encode()).hexdigest() == (
                excerpt.previous_text_sha256
            )
        if excerpt.current_text:
            section = current_sections[excerpt.selector]
            assert excerpt.current_start is not None
            assert excerpt.current_end is not None
            assert section.text[excerpt.current_start : excerpt.current_end] == excerpt.current_text
            assert sha256(excerpt.current_text.encode()).hexdigest() == excerpt.current_text_sha256


def test_real_prospectus_sequence_preserves_added_removed_modified_and_unchanged_truth() -> None:
    initial, expanded, reduced, unchanged = tuple(_snapshot(case) for case in CASES)

    expansion = compare_and_select_filing_changes(
        initial,
        expanded,
        relationship=FilingChangeRelationship.PROSPECTUS_UPDATE,
    )
    assert [(item.selector, item.kind) for item in expansion.changes] == [
        ("issuance.dilution", FilingChangeKind.ADDED),
        ("issuance.securities", FilingChangeKind.ADDED),
        ("issuance.use-of-proceeds", FilingChangeKind.ADDED),
        ("risks", FilingChangeKind.MODIFIED),
    ]
    _assert_exact_package_ranges(expansion, initial, expanded)

    reduction = compare_and_select_filing_changes(
        expanded,
        reduced,
        relationship=FilingChangeRelationship.PROSPECTUS_UPDATE,
    )
    assert [(item.selector, item.kind) for item in reduction.changes] == [
        ("issuance.dilution", FilingChangeKind.REMOVED),
        ("issuance.securities", FilingChangeKind.REMOVED),
        ("issuance.use-of-proceeds", FilingChangeKind.REMOVED),
        ("risks", FilingChangeKind.MODIFIED),
    ]
    _assert_exact_package_ranges(reduction, expanded, reduced)

    no_selected_change = compare_and_select_filing_changes(
        reduced,
        unchanged,
        relationship=FilingChangeRelationship.PROSPECTUS_UPDATE,
    )
    assert reduced.source_content_sha256 != unchanged.source_content_sha256
    assert reduced.sections[0].text_sha256 == unchanged.sections[0].text_sha256
    assert no_selected_change.changes == ()
    assert no_selected_change.selected_excerpts == ()
    assert no_selected_change.selected_characters == 0

    manifests = tuple(
        build_amendment_manifest_from_filing_change_snapshot(snapshot)
        for snapshot in (initial, expanded, reduced, unchanged)
    )
    for snapshot, manifest in zip((initial, expanded, reduced, unchanged), manifests, strict=True):
        assert manifest.event_novelty_ruleset_version == EVENT_NOVELTY_RULE_VERSION
        assert manifest.evidence_budget_version == EVIDENCE_BUDGET_VERSION
        assert manifest.extraction_ruleset_version == snapshot.extraction_version
        assert [
            (section.selector, section.evidence_sha256, section.evidence_characters)
            for section in manifest.sections
        ] == [
            (section.selector, section.text_sha256, len(section.text))
            for section in snapshot.sections
        ]
    conservative_expansion = decide_amendment_delta(
        manifests[0],
        manifests[1],
        relationship=FilingDeltaRelationship.PROSPECTUS_UPDATE,
    )
    assert conservative_expansion.disposition is AmendmentDeltaDisposition.FULL_REANALYSIS
    assert conservative_expansion.reason is AmendmentDeltaReason.DELTA_EXCEEDS_BUDGET

    conservative_reduction = decide_amendment_delta(
        manifests[1],
        manifests[2],
        relationship=FilingDeltaRelationship.PROSPECTUS_UPDATE,
    )
    assert conservative_reduction.disposition is AmendmentDeltaDisposition.FULL_REANALYSIS
    assert conservative_reduction.reason is AmendmentDeltaReason.REMOVED_RELEVANT_SECTION

    conservative_unchanged = decide_amendment_delta(
        manifests[2],
        manifests[3],
        relationship=FilingDeltaRelationship.PROSPECTUS_UPDATE,
    )
    assert conservative_unchanged.disposition is AmendmentDeltaDisposition.NO_SELECTED_DELTA
