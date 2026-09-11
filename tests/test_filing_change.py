"""Phase 42 deterministic filing-change contract tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from pydantic import ValidationError

from kalki_market_intelligence.forensics.filing_change import (
    MAXIMUM_SELECTED_CHANGES,
    MAXIMUM_SELECTED_CHARACTERS,
    FilingChangeCategory,
    FilingChangeForm,
    FilingChangeKind,
    FilingChangeRelationship,
    FilingChangeSnapshot,
    build_filing_change_section,
    build_filing_change_snapshot,
    compare_and_select_filing_changes,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _snapshot(
    accession: str,
    *,
    form: FilingChangeForm,
    cik: str = "1234567",
    hours: int,
    sections: tuple[tuple[str, FilingChangeCategory, str], ...],
) -> FilingChangeSnapshot:
    built_sections = tuple(
        build_filing_change_section(
            selector=selector,
            heading=selector.replace(".", " ").title(),
            category=category,
            text=text,
            normalized_start=index * 25_000,
        )
        for index, (selector, category, text) in enumerate(sections)
    )
    return build_filing_change_snapshot(
        accession_number=accession,
        cik=cik,
        filing_form=form,
        filed_at=T0 + timedelta(hours=hours),
        available_at=T0 + timedelta(hours=hours, minutes=1),
        retrieved_at=T0 + timedelta(hours=hours, minutes=2),
        source_url=(
            f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
            f"{accession.replace('-', '')}/{accession}.txt"
        ),
        source_content_sha256=sha256(accession.encode()).hexdigest(),
        normalized_visible_sha256=sha256(
            "\n".join(item.text for item in built_sections).encode()
        ).hexdigest(),
        sections=built_sections,
    )


def test_periodic_diff_retains_provenance_and_bounds_exact_changed_evidence() -> None:
    prior_text = "Opening narrative. " + "stable context " * 40 + "Cash was $20 million."
    current_text = "Opening narrative. " + "stable context " * 40 + "Cash was $8 million."
    previous = _snapshot(
        "0001234567-25-000001",
        form=FilingChangeForm.FORM_10_Q,
        hours=0,
        sections=(("mdna.liquidity", FilingChangeCategory.LIQUIDITY, prior_text),),
    )
    current = _snapshot(
        "0001234567-26-000001",
        form=FilingChangeForm.FORM_10_Q,
        hours=2,
        sections=(("mdna.liquidity", FilingChangeCategory.LIQUIDITY, current_text),),
    )

    receipt = compare_and_select_filing_changes(
        previous,
        current,
        relationship=FilingChangeRelationship.SUCCESSIVE_PERIODIC_REPORT,
    )

    assert receipt.previous_manifest_sha256 == previous.manifest_sha256
    assert receipt.current_manifest_sha256 == current.manifest_sha256
    assert receipt.changes[0].kind is FilingChangeKind.MODIFIED
    excerpt = receipt.selected_excerpts[0]
    assert "$20 million" in excerpt.previous_text
    assert "$8 million" in excerpt.current_text
    assert previous.sections[0].text[excerpt.previous_start : excerpt.previous_end] == (
        excerpt.previous_text
    )
    assert current.sections[0].text[excerpt.current_start : excerpt.current_end] == (
        excerpt.current_text
    )
    assert receipt.selected_characters <= MAXIMUM_SELECTED_CHARACTERS
    assert (
        receipt.receipt_id
        == compare_and_select_filing_changes(
            previous,
            current,
            relationship=FilingChangeRelationship.SUCCESSIVE_PERIODIC_REPORT,
        ).receipt_id
    )


def test_amendment_added_removed_and_unchanged_sections_are_truthful() -> None:
    previous = _snapshot(
        "0001234567-26-000002",
        form=FilingChangeForm.FORM_S_1,
        hours=0,
        sections=(
            ("risk", FilingChangeCategory.RISKS, "The supply risk remains material."),
            ("debt", FilingChangeCategory.DEBT, "The facility matures in 2028."),
        ),
    )
    current = _snapshot(
        "0001234567-26-000003",
        form=FilingChangeForm.FORM_S_1_AMENDMENT,
        hours=1,
        sections=(
            ("risk", FilingChangeCategory.RISKS, "The supply risk remains material."),
            ("issuance", FilingChangeCategory.ISSUANCE, "The issuer offers 4,000,000 shares."),
        ),
    )

    receipt = compare_and_select_filing_changes(
        previous,
        current,
        relationship=FilingChangeRelationship.AMENDMENT_OF,
    )

    assert [(item.selector, item.kind) for item in receipt.changes] == [
        ("debt", FilingChangeKind.REMOVED),
        ("issuance", FilingChangeKind.ADDED),
    ]
    assert {item.selector for item in receipt.selected_excerpts} == {"debt", "issuance"}
    assert "risk" not in {item.selector for item in receipt.changes}


def test_closed_category_order_and_caps_are_deterministic() -> None:
    categories = tuple(FilingChangeCategory)
    previous_sections = tuple(
        (f"section.{index}", category, f"old {category.value}")
        for index, category in enumerate(reversed(categories))
    )
    current_sections = tuple(
        (f"section.{index}", category, f"new {category.value}")
        for index, category in enumerate(reversed(categories))
    )
    previous = _snapshot(
        "0001234567-26-000004",
        form=FilingChangeForm.FORM_424_B_5,
        hours=0,
        sections=previous_sections,
    )
    current = _snapshot(
        "0001234567-26-000005",
        form=FilingChangeForm.FORM_424_B_5,
        hours=1,
        sections=current_sections,
    )

    receipt = compare_and_select_filing_changes(
        previous,
        current,
        relationship=FilingChangeRelationship.PROSPECTUS_UPDATE,
    )

    assert len(receipt.selected_excerpts) == MAXIMUM_SELECTED_CHANGES
    assert [item.category for item in receipt.selected_excerpts] == list(categories)[:6]
    assert len(receipt.omitted_selectors) == 2
    assert receipt.selected_characters <= MAXIMUM_SELECTED_CHARACTERS


def test_comparison_rejects_issuer_form_and_future_knowledge_mismatches() -> None:
    previous = _snapshot(
        "0001234567-26-000006",
        form=FilingChangeForm.FORM_10_K,
        hours=0,
        sections=(("controls", FilingChangeCategory.CONTROLS, "Controls were effective."),),
    )
    other_issuer = _snapshot(
        "0001234567-26-000007",
        form=FilingChangeForm.FORM_10_K,
        cik="7654321",
        hours=1,
        sections=(("controls", FilingChangeCategory.CONTROLS, "Controls were ineffective."),),
    )
    amendment = _snapshot(
        "0001234567-26-000008",
        form=FilingChangeForm.FORM_10_K_AMENDMENT,
        hours=1,
        sections=(("controls", FilingChangeCategory.CONTROLS, "Controls were ineffective."),),
    )

    with pytest.raises(ValueError, match="same canonical CIK"):
        compare_and_select_filing_changes(
            previous,
            other_issuer,
            relationship=FilingChangeRelationship.SUCCESSIVE_PERIODIC_REPORT,
        )
    with pytest.raises(ValueError, match="matching 10-K or 10-Q"):
        compare_and_select_filing_changes(
            previous,
            amendment,
            relationship=FilingChangeRelationship.SUCCESSIVE_PERIODIC_REPORT,
        )

    late_prior = build_filing_change_snapshot(
        accession_number=previous.accession_number,
        cik=previous.cik,
        filing_form=previous.filing_form,
        filed_at=previous.filed_at,
        available_at=previous.available_at,
        retrieved_at=T0 + timedelta(hours=3),
        source_url=previous.source_url,
        source_content_sha256=previous.source_content_sha256,
        normalized_visible_sha256=previous.normalized_visible_sha256,
        sections=previous.sections,
    )
    current = _snapshot(
        "0001234567-26-000009",
        form=FilingChangeForm.FORM_10_K,
        hours=2,
        sections=(("controls", FilingChangeCategory.CONTROLS, "Controls changed."),),
    )
    with pytest.raises(ValueError, match="retrieved after the current cutoff"):
        compare_and_select_filing_changes(
            late_prior,
            current,
            relationship=FilingChangeRelationship.SUCCESSIVE_PERIODIC_REPORT,
        )


def test_section_hash_and_canonical_whitespace_fail_closed() -> None:
    with pytest.raises(ValidationError, match="canonical whitespace"):
        from kalki_market_intelligence.forensics.filing_change import FilingChangeSection

        FilingChangeSection(
            selector="risk",
            heading="Risk factors",
            category=FilingChangeCategory.RISKS,
            normalized_start=0,
            normalized_end=len("Risk   changed."),
            text="Risk   changed.",
            text_sha256=sha256(b"Risk   changed.").hexdigest(),
        )


def test_snapshot_rejects_a_cross_filing_sec_url() -> None:
    section = build_filing_change_section(
        selector="risk",
        heading="Risk factors",
        category=FilingChangeCategory.RISKS,
        text="The exact risk section is available.",
    )
    with pytest.raises(ValidationError, match="does not match its accession"):
        build_filing_change_snapshot(
            accession_number="0001234567-26-000010",
            cik="1234567",
            filing_form=FilingChangeForm.FORM_10_Q,
            filed_at=T0,
            available_at=T0 + timedelta(minutes=1),
            retrieved_at=T0 + timedelta(minutes=2),
            source_url=(
                "https://www.sec.gov/Archives/edgar/data/1234567/000123456726999999/wrong.htm"
            ),
            source_content_sha256="a" * 64,
            normalized_visible_sha256="b" * 64,
            sections=(section,),
        )
