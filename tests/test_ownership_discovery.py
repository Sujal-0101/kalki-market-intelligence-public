"""Bounded ownership discovery remains separate from the deep-analysis queue."""

from datetime import UTC, datetime

import pytest

from kalki_market_intelligence.providers.sec.ownership import OwnershipForm
from kalki_market_intelligence.radar.ownership_source import (
    MAXIMUM_OWNERSHIP_INDEX_ROWS,
    parse_ownership_master_index,
)
from kalki_market_intelligence.radar.sec_source import SecRadarDocument

NOW = datetime(2026, 8, 29, 17, tzinfo=UTC)


def _document(body: bytes) -> SecRadarDocument:
    return SecRadarDocument(
        url="https://www.sec.gov/Archives/edgar/daily-index/2026/QTR3/master.20260829.idx",
        body=body,
        content_sha256="a" * 64,
        retrieved_at=NOW,
        media_type="text/plain",
    )


def test_master_index_selects_closed_ownership_forms_without_ticker_dependency() -> None:
    rows = b"\n".join(
        (
            b"CIK|Company Name|Form Type|Date Filed|Filename",
            b"1001385|NWPX Infrastructure|4|2026-08-29|edgar/data/1001385/0001437749-26-029167.txt",
            b"1922394|Wray Michael|4|2026-08-29|edgar/data/1922394/0001437749-26-029167.txt",
            b"1000694|Novavax|SC 13D/A|2026-08-29|edgar/data/1000694/0001104659-26-063172.txt",
            b"320193|Apple|8-K|2026-08-29|edgar/data/320193/0000320193-26-000001.txt",
        )
    )

    candidates = parse_ownership_master_index(_document(rows))

    assert {item.form for item in candidates} == {
        OwnershipForm.FORM_4,
        OwnershipForm.SCHEDULE_13D_A,
    }
    form4 = next(item for item in candidates if item.form is OwnershipForm.FORM_4)
    assert form4.index_ciks == ("0001001385", "0001922394")
    assert form4.index_names == ("NWPX Infrastructure", "Wray Michael")
    assert form4.source_index_sha256 == "a" * 64


def test_master_index_rejects_bad_identity_and_caps_selected_rows() -> None:
    valid = b"1001385|Issuer|4|2026-08-29|edgar/data/1001385/0001437749-26-029167.txt"
    mismatched = b"1001385|Issuer|4|2026-08-29|edgar/data/9999999/0001437749-26-029168.txt"
    rows = b"\n".join((mismatched, *(valid for _ in range(MAXIMUM_OWNERSHIP_INDEX_ROWS + 2))))

    with pytest.raises(ValueError, match="exceed the safety boundary"):
        parse_ownership_master_index(_document(rows))


def test_master_index_skips_invalid_empty_company_without_failing_poll() -> None:
    row = b"1001385||4|2026-08-29|edgar/data/1001385/0001437749-26-029167.txt"

    assert parse_ownership_master_index(_document(row)) == ()
