"""Canonical SEC filing links fail closed before website or Discord projection."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256

import pytest
from pydantic import ValidationError

from kalki_market_intelligence.providers.sec.client import (
    HttpResult,
    RateLimiter,
    SecTransportError,
    validate_sec_url,
)
from kalki_market_intelligence.radar.sec_links import (
    SecLinkValidationError,
    ValidatedSecFilingLinks,
    extract_primary_document_name,
    public_sec_filing_links,
    validate_sec_filing_links,
)
from kalki_market_intelligence.radar.sec_source import SecRadarClient, SecRadarDocument

CIK = "0001045810"
ACCESSION = "0001045810-26-000073"
BASE = "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000073"
COMPLETE_URL = f"https://www.sec.gov/Archives/edgar/data/1045810/{ACCESSION}.txt"
NESTED_COMPLETE_URL = f"{BASE}/{ACCESSION}.txt"
INDEX_URL = f"{BASE}/{ACCESSION}-index.html"
PRIMARY_URL = f"{BASE}/q2fy27pr.htm"
INLINE_URL = (
    "https://www.sec.gov/ixviewer/doc/action?doc="
    "/Archives/edgar/data/1045810/000104581026000073/q2fy27pr.htm"
)
NOW = datetime(2026, 8, 30, 20, tzinfo=UTC)


def complete_body(filename: str = "q2fy27pr.htm") -> bytes:
    return (
        b"<SEC-DOCUMENT>\n<DOCUMENT>\n<TYPE>8-K\n<SEQUENCE>1\n<FILENAME>"
        + filename.encode()
        + b"\n<DESCRIPTION>Primary filing\n<TEXT>bounded</TEXT>\n</DOCUMENT>\n"
    )


class LinkTransport:
    def __init__(
        self,
        *,
        inline: bool = True,
        redirect_primary: bool = False,
        viewer_status: int = 200,
    ) -> None:
        self.inline = inline
        self.redirect_primary = redirect_primary
        self.viewer_status = viewer_status
        self.calls: list[str] = []

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        maximum_bytes: int,
    ) -> HttpResult:
        self.calls.append(url)
        assert headers["User-Agent"] == "Kalki tests test@example.com"
        assert timeout == 30
        assert maximum_bytes == 50_000_000
        if url == INDEX_URL:
            body = b'<html><a href="q2fy27pr.htm">Primary document</a></html>'
        elif url == PRIMARY_URL:
            body = (
                b'<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"><ix:nonNumeric>'
                if self.inline
                else b"<html><p>Non-inline filing</p>"
            )
        elif url == INLINE_URL:
            body = b"<html><p>SEC Inline XBRL Viewer</p></html>"
        else:
            raise AssertionError(f"unexpected URL: {url}")
        response_url = f"{BASE}/other.htm" if self.redirect_primary and url == PRIMARY_URL else url
        return HttpResult(
            url=response_url,
            status_code=self.viewer_status if url == INLINE_URL else 200,
            headers={"content-type": "text/html"},
            body=body,
        )


def document() -> SecRadarDocument:
    body = complete_body()
    return SecRadarDocument(
        url=COMPLETE_URL,
        body=body,
        content_sha256=sha256(body).hexdigest(),
        retrieved_at=NOW,
        media_type="text/plain",
    )


def client(transport: LinkTransport) -> SecRadarClient:
    return SecRadarClient(
        user_agent="Kalki tests test@example.com",
        transport=transport,
        limiter=RateLimiter(10, monotonic=lambda: 0.0, sleep=lambda _: None),
        now=lambda: NOW,
    )


def test_exact_archive_primary_and_inline_links_validate() -> None:
    transport = LinkTransport()
    links = validate_sec_filing_links(
        client=client(transport),
        canonical_cik=CIK,
        accession_number=ACCESSION,
        filing_form="8-K",
        complete_submission=document(),
    )

    assert links.archive_index_url == INDEX_URL
    assert links.primary_document_url == PRIMARY_URL
    assert links.inline_xbrl_url == INLINE_URL
    assert transport.calls == [INDEX_URL, PRIMARY_URL, INLINE_URL]
    assert links.complete_submission_url == COMPLETE_URL

    public = public_sec_filing_links(links)
    assert public.primary_document_url == PRIMARY_URL
    assert set(public.model_dump()) == {
        "accession_number",
        "complete_submission_url",
        "archive_index_url",
        "primary_document_url",
        "inline_xbrl_url",
    }
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        public.model_validate(public.model_dump() | {"raw_model_output": "private"})


def test_nested_complete_submission_path_also_validates_but_cross_filing_path_fails() -> None:
    nested = document()
    nested = SecRadarDocument(
        url=NESTED_COMPLETE_URL,
        body=nested.body,
        content_sha256=nested.content_sha256,
        retrieved_at=nested.retrieved_at,
        media_type=nested.media_type,
    )
    links = validate_sec_filing_links(
        client=client(LinkTransport(inline=False)),
        canonical_cik=CIK,
        accession_number=ACCESSION,
        filing_form="8-K",
        complete_submission=nested,
    )
    assert links.complete_submission_url == NESTED_COMPLETE_URL

    wrong = SecRadarDocument(
        url=NESTED_COMPLETE_URL.replace(ACCESSION, "0001045810-26-000074"),
        body=nested.body,
        content_sha256=nested.content_sha256,
        retrieved_at=nested.retrieved_at,
        media_type=nested.media_type,
    )
    with pytest.raises(SecLinkValidationError, match="identity"):
        validate_sec_filing_links(
            client=client(LinkTransport(inline=False)),
            canonical_cik=CIK,
            accession_number=ACCESSION,
            filing_form="8-K",
            complete_submission=wrong,
        )


def test_non_inline_filing_never_manufactures_viewer_link() -> None:
    transport = LinkTransport(inline=False)
    links = validate_sec_filing_links(
        client=client(transport),
        canonical_cik=CIK,
        accession_number=ACCESSION,
        filing_form="8-K",
        complete_submission=document(),
    )

    assert links.inline_xbrl_url is None
    assert not links.inline_xbrl_validated
    assert transport.calls == [INDEX_URL, PRIMARY_URL]


def test_unavailable_inline_viewer_is_omitted_without_erasing_valid_links() -> None:
    transport = LinkTransport(viewer_status=404)
    links = validate_sec_filing_links(
        client=client(transport),
        canonical_cik=CIK,
        accession_number=ACCESSION,
        filing_form="8-K",
        complete_submission=document(),
    )

    assert links.archive_index_url == INDEX_URL
    assert links.primary_document_url == PRIMARY_URL
    assert links.inline_xbrl_url is None
    assert not links.inline_xbrl_validated


def test_redirect_or_identity_mismatch_fails_closed() -> None:
    with pytest.raises(SecLinkValidationError, match="redirected"):
        validate_sec_filing_links(
            client=client(LinkTransport(redirect_primary=True)),
            canonical_cik=CIK,
            accession_number=ACCESSION,
            filing_form="8-K",
            complete_submission=document(),
        )

    wrong = document()
    wrong = SecRadarDocument(
        url=wrong.url.replace("1045810/", "9999999/"),
        body=wrong.body,
        content_sha256=wrong.content_sha256,
        retrieved_at=wrong.retrieved_at,
        media_type=wrong.media_type,
    )
    with pytest.raises(SecLinkValidationError, match="identity"):
        validate_sec_filing_links(
            client=client(LinkTransport()),
            canonical_cik=CIK,
            accession_number=ACCESSION,
            filing_form="8-K",
            complete_submission=wrong,
        )


def test_primary_document_extraction_rejects_path_and_wrong_form() -> None:
    assert extract_primary_document_name(complete_body(), filing_form="8-K") == "q2fy27pr.htm"
    with pytest.raises(SecLinkValidationError, match="safe direct HTML"):
        extract_primary_document_name(complete_body("../q2fy27pr.htm"), filing_form="8-K")
    with pytest.raises(SecLinkValidationError, match="no exact"):
        extract_primary_document_name(complete_body(), filing_form="10-Q")


def test_closed_projection_cannot_swap_urls_or_claim_unvalidated_inline() -> None:
    transport = LinkTransport(inline=False)
    links = validate_sec_filing_links(
        client=client(transport),
        canonical_cik=CIK,
        accession_number=ACCESSION,
        filing_form="8-K",
        complete_submission=document(),
    )
    with pytest.raises(ValidationError, match="archive-index URL"):
        links.model_copy(update={"archive_index_url": f"{BASE}/other-index.html"}).model_validate(
            links.model_copy(update={"archive_index_url": f"{BASE}/other-index.html"})
        )
    with pytest.raises(ValidationError, match="validation flag"):
        ValidatedSecFilingLinks.model_validate(links.model_dump() | {"inline_xbrl_validated": True})


def test_sec_transport_allows_only_the_exact_inline_viewer_query() -> None:
    validate_sec_url(INLINE_URL)
    for url in (
        "https://www.sec.gov/ixviewer/doc/action",
        INLINE_URL + "&redirect=https://example.com",
        "https://www.sec.gov/ixviewer/doc/action?doc=https://example.com",
        "https://www.sec.gov/ixviewer/doc/action?doc=/Archives/edgar/data/1/2/../x.htm",
    ):
        with pytest.raises(SecTransportError):
            validate_sec_url(url)
