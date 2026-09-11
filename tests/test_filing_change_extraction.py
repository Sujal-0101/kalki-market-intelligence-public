"""Phase 42 deterministic SEC section-extraction tests."""

from __future__ import annotations

import base64
import gzip
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest

from kalki_market_intelligence.forensics.filing_change import (
    FilingChangeCategory,
    FilingChangeForm,
    FilingChangeRelationship,
    compare_and_select_filing_changes,
)
from kalki_market_intelligence.providers.sec.filing_change import (
    MAXIMUM_FILING_CHANGE_HTML_BYTES,
    FilingChangeExtractionError,
    build_snapshot_from_filing_change_extraction,
    extract_filing_change_sections,
    normalized_filing_change_visible_text,
)

FIXTURES = Path(__file__).parent / "fixtures" / "accounting"
FINANCING_FIXTURES = Path(__file__).parent / "fixtures" / "financing"


def _official_fixture(name: str) -> bytes:
    return gzip.decompress(base64.b64decode((FIXTURES / name).read_bytes()))


@pytest.mark.parametrize(
    ("fixture", "form", "expected_hash", "expected_categories"),
    (
        (
            "aqua-metals-2026-10-q.html.gz.b64",
            FilingChangeForm.FORM_10_Q,
            "6fa6c6a0700cae032558409762fc47f15c7b31fb52fbd01a3d3a18633da97bd1",
            {
                FilingChangeCategory.LIQUIDITY,
                FilingChangeCategory.RISKS,
                FilingChangeCategory.GOING_CONCERN,
                FilingChangeCategory.CONTROLS,
            },
        ),
        (
            "cs-diagnostics-2026-10-k.html.gz.b64",
            FilingChangeForm.FORM_10_K,
            "520212c4fb97b8717e563457e405a54b4a2cbe0634eba13c4058ea4eb6cad9f3",
            {
                FilingChangeCategory.LIQUIDITY,
                FilingChangeCategory.RISKS,
                FilingChangeCategory.GOING_CONCERN,
                FilingChangeCategory.LITIGATION,
                FilingChangeCategory.CONTROLS,
                FilingChangeCategory.OUTLOOK,
            },
        ),
    ),
)
def test_complete_official_periodic_documents_keep_exact_ranges_and_hashes(
    fixture: str,
    form: FilingChangeForm,
    expected_hash: str,
    expected_categories: set[FilingChangeCategory],
) -> None:
    body = _official_fixture(fixture)
    assert sha256(body).hexdigest() == expected_hash

    result = extract_filing_change_sections(body, filing_form=form)
    visible = normalized_filing_change_visible_text(body)

    assert result.source_content_sha256 == expected_hash
    assert result.normalized_visible_sha256 == sha256(visible.encode()).hexdigest()
    assert {item.category for item in result.sections} >= expected_categories
    for section in result.sections:
        assert visible[section.normalized_start : section.normalized_end] == section.text
        assert sha256(section.text.encode()).hexdigest() == section.text_sha256


def test_hidden_content_and_table_of_contents_cannot_displace_real_sections() -> None:
    body = b"""
    <html><body>
      <div hidden>ITEM 1A. Risk Factors Fabricated hidden risk language.</div>
      <div style="display:none">Liquidity and Capital Resources Hidden liquidity.</div>
      ITEM 1A. Risk Factors 12 ITEM 3. Legal Proceedings 18 ITEM 9A. Controls and Procedures 42
      ITEM 1A. Risk Factors
      The issuer depends on one supplier and the concentration risk could disrupt production.
      Additional exact discussion makes this the substantive section rather than a page reference.
      ITEM 3. Legal Proceedings
      The complaint remains pending and no outcome or amount is asserted by this fixture.
      ITEM 9A. Controls and Procedures
      Management identified a material weakness and describes its remediation plan here.
    </body></html>
    """

    result = extract_filing_change_sections(body, filing_form=FilingChangeForm.FORM_10_K)

    by_category = {item.category: item.text for item in result.sections}
    assert "Fabricated hidden" not in " ".join(by_category.values())
    assert "concentration risk" in by_category[FilingChangeCategory.RISKS]
    assert "complaint remains pending" in by_category[FilingChangeCategory.LITIGATION]
    assert "material weakness" in by_category[FilingChangeCategory.CONTROLS]


def test_prospectus_headings_map_to_closed_categories_without_materiality_claim() -> None:
    body = b"""
    <html><body>
      RISK FACTORS The offering involves substantial risks described in this bounded section.
      USE OF PROCEEDS We expect to use the stated proceeds for working capital;
      no closing is inferred.
      DILUTION The table describes historical net tangible book value and the offered shares.
      DEBT FINANCING The credit facility has a stated maturity in 2029 and defined covenants.
      LEGAL PROCEEDINGS One complaint is pending; the source states no supported outcome.
      BUSINESS OUTLOOK Management describes expected operating priorities without
      guaranteeing results.
    </body></html>
    """

    result = extract_filing_change_sections(body, filing_form=FilingChangeForm.FORM_S_3)

    assert {item.category for item in result.sections} >= {
        FilingChangeCategory.RISKS,
        FilingChangeCategory.DEBT,
        FilingChangeCategory.ISSUANCE,
        FilingChangeCategory.LITIGATION,
        FilingChangeCategory.OUTLOOK,
    }


def test_complete_official_prospectus_retains_distinct_issuance_sections() -> None:
    body = gzip.decompress(
        base64.b64decode(
            (FINANCING_FIXTURES / "wellchange-2026-424b4-full.html.gz.b64").read_bytes()
        )
    )
    expected_hash = "33b4016a0a57c52d6fb03650eb5489d7f0aa3e804096eb70213960d5721dca39"
    assert sha256(body).hexdigest() == expected_hash

    result = extract_filing_change_sections(body, filing_form=FilingChangeForm.FORM_424_B_4)
    selectors = {item.selector for item in result.sections}

    assert result.source_content_sha256 == expected_hash
    assert {item.category for item in result.sections} >= {
        FilingChangeCategory.LIQUIDITY,
        FilingChangeCategory.RISKS,
        FilingChangeCategory.DEBT,
        FilingChangeCategory.ISSUANCE,
        FilingChangeCategory.LITIGATION,
    }
    assert selectors >= {
        "issuance.use-of-proceeds",
        "issuance.dilution",
        "issuance.securities",
    }


def test_extraction_fails_closed_for_empty_and_oversized_sources() -> None:
    with pytest.raises(FilingChangeExtractionError, match="empty"):
        extract_filing_change_sections(b"", filing_form=FilingChangeForm.FORM_10_Q)
    with pytest.raises(FilingChangeExtractionError, match="parser boundary"):
        extract_filing_change_sections(
            b"x" * (MAXIMUM_FILING_CHANGE_HTML_BYTES + 1),
            filing_form=FilingChangeForm.FORM_10_Q,
        )


def test_extraction_to_snapshot_to_diff_keeps_one_source_bound_path() -> None:
    prior_body = b"""
    <body>Liquidity and Capital Resources
    Cash and cash equivalents were $20 million and the credit facility matures in 2029.
    Controls and Procedures Management concluded disclosure controls were effective.</body>
    """
    current_body = b"""
    <body>Liquidity and Capital Resources
    Cash and cash equivalents were $8 million and the credit facility matures in 2029.
    Controls and Procedures Management concluded disclosure controls were effective.</body>
    """
    prior_extraction = extract_filing_change_sections(
        prior_body, filing_form=FilingChangeForm.FORM_10_Q
    )
    current_extraction = extract_filing_change_sections(
        current_body, filing_form=FilingChangeForm.FORM_10_Q
    )
    accepted_at = datetime(2026, 1, 1, tzinfo=UTC)
    prior = build_snapshot_from_filing_change_extraction(
        prior_extraction,
        accession_number="0001234567-25-000001",
        cik="1234567",
        filed_at=accepted_at,
        available_at=accepted_at + timedelta(minutes=1),
        retrieved_at=accepted_at + timedelta(minutes=2),
        source_url=("https://www.sec.gov/Archives/edgar/data/1234567/000123456725000001/prior.htm"),
    )
    current = build_snapshot_from_filing_change_extraction(
        current_extraction,
        accession_number="0001234567-26-000001",
        cik="1234567",
        filed_at=accepted_at + timedelta(hours=1),
        available_at=accepted_at + timedelta(hours=1, minutes=1),
        retrieved_at=accepted_at + timedelta(hours=1, minutes=2),
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/1234567/000123456726000001/current.htm"
        ),
    )

    receipt = compare_and_select_filing_changes(
        prior,
        current,
        relationship=FilingChangeRelationship.SUCCESSIVE_PERIODIC_REPORT,
    )

    assert prior.source_content_sha256 == sha256(prior_body).hexdigest()
    assert current.source_content_sha256 == sha256(current_body).hexdigest()
    assert [item.selector for item in receipt.changes] == ["liquidity"]
    assert "$20 million" in receipt.selected_excerpts[0].previous_text
    assert "$8 million" in receipt.selected_excerpts[0].current_text
