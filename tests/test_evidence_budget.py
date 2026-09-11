"""Form-aware deterministic evidence-budget selection tests."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from kalki_market_intelligence.radar.evidence_budget import (
    MAXIMUM_EVIDENCE_CHARACTERS,
    MAXIMUM_WINDOWS,
    EvidenceFormFamily,
    EvidenceSectionKind,
    EvidenceSelectionReason,
    normalized_visible_text,
)
from kalki_market_intelligence.radar.extraction import (
    exclude_exact_event_evidence,
    extract_form_aware_research_excerpt,
    extract_research_excerpt,
)

FIXTURES = Path(__file__).parent / "fixtures" / "financing"


def test_8k_budget_preserves_material_item_facts_and_deprioritizes_boilerplate() -> None:
    filing = b"""
    <html><body>
    ITEM 1.01 Entry into a Material Definitive Agreement
    On August 28, 2026, Example Corp entered a strategic agreement with Apollo Global
    Management and Brookfield Asset Management for a $525 million financing commitment.
    The agreement permits issuance of 12,500,000 shares at $4.20 per share.
    ITEM 3.01 Notice of Delisting or Failure to Satisfy a Continued Listing Rule
    Nasdaq notified the company that it was not in compliance with the $1.00 bid-price rule.
    ITEM 5.02 Departure of Directors or Certain Officers
    Jane Example resigned as Chief Financial Officer effective September 2, 2026.
    ITEM 9.01 Financial Statements and Exhibits
    This report contains forward-looking statements and an exhibit index incorporated by
    reference. This language is ordinary repeated legal boilerplate.
    </body></html>
    """

    result = extract_form_aware_research_excerpt(filing, filing_form="8-K")

    assert "August 28, 2026" in result.text
    assert "$525 million" in result.text
    assert "12,500,000 shares" in result.text
    assert "Apollo Global Management" in result.text
    assert "$1.00 bid-price rule" in result.text
    assert "Jane Example resigned" in result.text
    assert "ordinary repeated legal boilerplate" not in result.text
    assert result.evidence_budget is not None
    assert result.evidence_budget.form_family is EvidenceFormFamily.CURRENT_REPORT
    assert set(result.evidence_budget.retained_baseline_terms) == set(
        result.evidence_budget.required_baseline_terms
    )
    assert {window.item_number for window in result.evidence_budget.selected_windows} >= {
        "1.01",
        "3.01",
        "5.02",
    }


def test_periodic_budget_selects_md_and_a_risk_going_concern_and_controls() -> None:
    padding = "ordinary quarterly narrative " * 25
    filing = f"""
    <html><body>
    PART I
    ITEM 2. MANAGEMENT’S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS
    OF OPERATIONS
    {padding}
    Liquidity declined after cash used in operations reached $18.4 million for the six
    months ended June 30, 2026. The revolving credit facility matures on March 1, 2027.
    ITEM 1A. RISK FACTORS
    {padding}
    Management concluded that recurring losses raise substantial doubt about the company's
    ability to continue as a going concern for twelve months after issuance.
    ITEM 4. CONTROLS AND PROCEDURES
    {padding}
    The Chief Executive Officer identified a material weakness in internal control over
    financial reporting related to revenue recognition.
    </body></html>
    """.encode()

    result = extract_form_aware_research_excerpt(filing, filing_form="10-Q")

    assert "$18.4 million" in result.text
    assert "March 1, 2027" in result.text
    assert "substantial doubt" in result.text
    assert "material weakness" in result.text
    assert len(result.text) <= MAXIMUM_EVIDENCE_CHARACTERS
    assert result.evidence_budget is not None
    kinds = {window.section_kind for window in result.evidence_budget.selected_windows}
    assert EvidenceSectionKind.GOING_CONCERN in kinds
    assert EvidenceSectionKind.CONTROLS in kinds


def test_changed_amendment_section_is_selected_without_guessing_materiality() -> None:
    filing = b"""
    <html><body>
    MANAGEMENT'S DISCUSSION AND ANALYSIS
    This amended section corrects the presentation of an earlier table. No other conclusion
    is supplied by this test fixture.
    RISK FACTORS
    Forward-looking statements are incorporated by reference.
    </body></html>
    """

    result = extract_form_aware_research_excerpt(
        filing,
        filing_form="10-Q/A",
        changed_section_names=("Management discussion and analysis",),
    )

    assert "corrects the presentation" in result.text
    assert result.evidence_budget is not None
    assert result.evidence_budget.changed_section_names == ("Management discussion and analysis",)
    assert any(
        window.reason is EvidenceSelectionReason.CHANGED_SECTION
        for window in result.evidence_budget.selected_windows
    )


def test_non_target_form_retains_accepted_baseline_and_truthful_unavailable_actual_tokens() -> None:
    filing = b"<body>The company announced a contract award and a material weakness.</body>"
    baseline = extract_research_excerpt(filing)

    result = extract_form_aware_research_excerpt(filing, filing_form="6-K")

    assert result.text == baseline.text
    assert result.evidence_budget is not None
    assert result.evidence_budget.form_family is EvidenceFormFamily.FALLBACK
    assert result.evidence_budget.actual_prompt_tokens is None
    assert result.evidence_budget.baseline_characters == len(baseline.text)
    assert result.evidence_budget.selected_characters == len(result.text)


def test_receipt_windows_reconcile_exact_normalized_ranges_hashes_and_caps() -> None:
    filing = (FIXTURES / "wellchange-2026-424b4-priced-offering-excerpt.html").read_bytes()
    # The genuine 424B4 fixture remains on the accepted keyword fallback because item-aware
    # selection is deliberately limited to 8-K and periodic reports in this slice.
    fallback = extract_form_aware_research_excerpt(filing, filing_form="424B4")
    assert fallback.evidence_budget is not None
    assert fallback.evidence_budget.source_content_sha256 == sha256(filing).hexdigest()

    current_report = b"<body>ITEM 2.03 " + (b"context " * 500) + b"debt covenant $25 million</body>"
    selected = extract_form_aware_research_excerpt(current_report, filing_form="8-K")
    receipt = selected.evidence_budget
    assert receipt is not None
    visible = normalized_visible_text(current_report)
    assert len(receipt.selected_windows) <= MAXIMUM_WINDOWS
    assert len(selected.text) <= MAXIMUM_EVIDENCE_CHARACTERS
    for window in receipt.selected_windows:
        exact = visible[window.normalized_start : window.normalized_end]
        assert len(exact) == window.text_characters
        assert sha256(exact.encode()).hexdigest() == window.text_sha256


def test_complete_submission_selects_only_exact_form_document_not_exhibits() -> None:
    submission = b"""
    <SEC-DOCUMENT>
    <DOCUMENT><TYPE>EX-99.1<TEXT><body>Unrelated exhibit text.</body></TEXT>
    </DOCUMENT>
    <DOCUMENT><TYPE>8-K<TEXT><body>ITEM 4.02 Non-Reliance on Previously Issued
    Financial Statements. The audit committee concluded that the statements should no
    longer be relied upon due to an accounting error.</body></TEXT></DOCUMENT>
    </SEC-DOCUMENT>
    """

    result = extract_form_aware_research_excerpt(submission, filing_form="8-K")

    assert "accounting error" in result.text
    assert "Unrelated exhibit text" not in result.text
    assert result.evidence_budget is not None
    assert result.evidence_budget.selected_document_type == "8-K"
    assert result.evidence_budget.selected_document_types == ("EX-99.1", "8-K")
    assert {window.item_number for window in result.evidence_budget.selected_windows} == {"4.02"}


def test_8k_budget_retains_material_term_from_authoritative_exhibit() -> None:
    submission = b"""
    <DOCUMENT><TYPE>8-K<TEXT><body>ITEM 9.01 Financial Statements and Exhibits.
    The press release is furnished as Exhibit 99.1.</body></TEXT></DOCUMENT>
    <DOCUMENT><TYPE>EX-99.1<TEXT><body>On August 28, 2026, the company announced a
    contract award with a stated value of $42 million.</body></TEXT></DOCUMENT>
    """

    result = extract_form_aware_research_excerpt(submission, filing_form="8-K")

    assert "contract award" in result.text
    assert "$42 million" in result.text
    assert result.evidence_budget is not None
    assert result.evidence_budget.required_baseline_terms == ("contract", "award")
    assert result.evidence_budget.retained_baseline_terms == ("contract", "award")
    assert result.evidence_budget.selected_document_types == ("EX-99.1", "8-K")


def test_inline_xbrl_wrapper_keeps_visible_filing_and_hides_header_metadata() -> None:
    submission = b"""
    <DOCUMENT><TYPE>8-K<TEXT><XBRL><html><body>
    <ix:header>ITEM 1.01 hidden metadata partnership</ix:header>
    ITEM 3.01 Notice of Delisting. Nasdaq issued a listing deficiency notice.
    </body></html></XBRL></TEXT></DOCUMENT>
    """

    result = extract_form_aware_research_excerpt(submission, filing_form="8-K")

    assert "listing deficiency notice" in result.text
    assert "hidden metadata partnership" not in result.text
    assert result.evidence_budget is not None
    assert {window.item_number for window in result.evidence_budget.selected_windows} == {"3.01"}


def test_periodic_item_boundaries_ignore_toc_and_repeated_heading_words() -> None:
    filing = b"""
    <html><body>
    ITEM 1A. Risk Factors 23 ITEM 4. Controls and Procedures 41
    ITEM 2. MANAGEMENT'S DISCUSSION AND ANALYSIS
    Liquidity was $24.5 million at June 30, 2026 and the credit facility matures in 2028.
    ITEM 4. CONTROLS AND PROCEDURES
    Management evaluated the disclosure controls and procedures. Based on that evaluation,
    the chief executive officer concluded that the disclosure controls and procedures are
    effective at a reasonable assurance level.
    ITEM 5. OTHER INFORMATION
    No unrelated conclusion is supplied.
    </body></html>
    """

    result = extract_form_aware_research_excerpt(filing, filing_form="10-Q")

    assert "Liquidity was $24.5 million" in result.text
    assert "effective at a reasonable assurance level" in result.text
    assert "Risk Factors 23" not in result.text
    assert result.evidence_budget is not None
    assert {window.section_kind for window in result.evidence_budget.selected_windows} >= {
        EvidenceSectionKind.LIQUIDITY_AND_MD_AND_A,
        EvidenceSectionKind.CONTROLS,
    }


def test_event_filter_retains_budget_lineage_and_records_final_package_hash() -> None:
    filing = b"<body>ITEM 1.01 The company announced a strategic agreement with Apollo.</body>"
    selected = extract_form_aware_research_excerpt(filing, filing_form="8-K")

    filtered = exclude_exact_event_evidence(
        selected,
        ("The company announced a strategic agreement with Apollo.",),
    )

    assert filtered.evidence_budget is not None
    assert filtered.evidence_budget.post_filter_excerpt_sha256 == filtered.content_sha256
    assert filtered.evidence_budget.post_filter_characters == len(filtered.text)
    assert filtered.evidence_budget.excluded_event_quote_sha256s == (
        sha256(b"The company announced a strategic agreement with Apollo.").hexdigest(),
    )
