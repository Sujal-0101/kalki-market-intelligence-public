"""Focused deterministic filing diff tests."""

from kalki_market_intelligence.forensics.filing_diff import (
    FilingDiffChangeKind,
    FilingSection,
    FilingSnapshot,
    compare_filings,
)


def snapshot(filing_id: str, accession: str, sections: tuple[FilingSection, ...]) -> FilingSnapshot:
    return FilingSnapshot(
        filing_id=filing_id,
        accession_number=accession,
        source_content_sha256=("a" if filing_id == "old" else "b") * 64,
        sections=sections,
    )


def test_filing_diff_retains_provenance_and_meaningful_changes() -> None:
    result = compare_filings(
        snapshot(
            "old",
            "0000000001-26-000001",
            (
                FilingSection(name="Liquidity", text="Cash was 10 million."),
                FilingSection(name="Risk", text="No material change."),
            ),
        ),
        snapshot(
            "new",
            "0000000001-26-000002",
            (
                FilingSection(name="Liquidity", text="Cash was 7 million."),
                FilingSection(name="New Contract", text="The agreement was signed."),
            ),
        ),
    )
    assert result.calculation_version == "1.0.0"
    assert result.previous_accession_number.endswith("000001")
    assert [change.kind for change in result.changes] == [
        FilingDiffChangeKind.MODIFIED,
        FilingDiffChangeKind.ADDED,
        FilingDiffChangeKind.REMOVED,
    ]


def test_filing_diff_ignores_whitespace_only_changes() -> None:
    result = compare_filings(
        snapshot("old", "old", (FilingSection(name="MD&A", text="Cash   remains stable."),)),
        snapshot("new", "new", (FilingSection(name="MD&A", text="Cash remains stable."),)),
    )
    assert result.changes == ()
