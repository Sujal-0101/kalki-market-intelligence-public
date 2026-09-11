"""Bounded filing section extraction fixtures."""

from kalki_market_intelligence.providers.sec.sections import extract_filing_sections


def test_section_mapping_is_heading_bounded_and_deterministic() -> None:
    sections = extract_filing_sections(
        b"<h1>Liquidity</h1><p>Cash is 10.</p><h2>Risk Factors</h2><p>Going concern.</p>"
    )
    assert [(item.name, item.text) for item in sections] == [
        ("Liquidity", "Cash is 10."),
        ("Risk Factors", "Going concern."),
    ]


def test_section_mapping_ignores_unheaded_preamble() -> None:
    sections = extract_filing_sections(b"Preamble<h1>Overview</h1><p>Contract award.</p>")
    assert len(sections) == 1
    assert sections[0].name == "Overview"
