"""Equivalence fixtures for the optional EdgarTools interpretation boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from kalki_market_intelligence.providers.sec.client import SecFetchedDocument
from kalki_market_intelligence.providers.sec.edgartools_adapter import EdgarToolsAdapter
from kalki_market_intelligence.providers.sec.normalization import normalize_submissions

FIXTURE_ROOT = Path(__file__).parents[1] / "data/fixtures/sec"
RETRIEVED_AT = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


@dataclass(frozen=True)
class FixtureEdgarFiling:
    cik: str
    accession_number: str
    form: str
    filing_date: date
    report_date: date | None
    accepted_at: datetime
    file_number: str | None
    primary_document: str
    primary_document_description: str | None
    filing_url: str


def test_edgartools_adapter_matches_existing_normalized_filing_fixture() -> None:
    raw = (FIXTURE_ROOT / "synthetic-alpha-submissions.json").read_bytes()
    document = SecFetchedDocument(
        endpoint="submissions",
        cik="0000000001",
        url="https://data.sec.gov/submissions/CIK0000000001.json",
        status_code=200,
        headers={},
        body=raw,
        content_sha256="a" * 64,
        retrieved_at=RETRIEVED_AT,
    )
    _, expected = normalize_submissions(document)
    baseline = expected[0]
    adapted = EdgarToolsAdapter().adapt(
        FixtureEdgarFiling(
            cik=baseline.cik,
            accession_number=baseline.accession_number,
            form=baseline.form,
            filing_date=baseline.filing_date,
            report_date=baseline.report_date,
            accepted_at=baseline.accepted_at,
            file_number=baseline.file_number,
            primary_document=baseline.primary_document,
            primary_document_description=baseline.primary_document_description,
            filing_url=str(baseline.filing_url),
        ),
        source_content_sha256=baseline.source_content_sha256,
        available_at=baseline.available_at,
        retrieved_at=baseline.retrieved_at,
    )
    assert adapted == baseline


def test_edgartools_adapter_preserves_retrieval_lineage() -> None:
    filing = FixtureEdgarFiling(
        cik="0000000001",
        accession_number="0000000001-26-000001",
        form="8-K",
        filing_date=date(2026, 8, 20),
        report_date=None,
        accepted_at=RETRIEVED_AT,
        file_number=None,
        primary_document="event.htm",
        primary_document_description=None,
        filing_url="https://www.sec.gov/Archives/edgar/data/1/000000000126000001/event.htm",
    )
    adapted = EdgarToolsAdapter().adapt(
        filing,
        source_content_sha256="b" * 64,
        available_at=RETRIEVED_AT,
        retrieved_at=RETRIEVED_AT,
    )
    assert adapted.source_content_sha256 == "b" * 64
    assert adapted.available_at == RETRIEVED_AT
    assert adapted.retrieved_at == RETRIEVED_AT
