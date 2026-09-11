"""Tests for SEC identification, request boundaries, rate limiting, and retries."""

from __future__ import annotations

import gzip
import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime

import pytest

from kalki_market_intelligence.providers.sec.client import (
    MAXIMUM_FINANCING_PRIMARY_DOCUMENT_BYTES,
    MAXIMUM_PRIMARY_DOCUMENT_BYTES,
    HttpResult,
    RateLimiter,
    SecClient,
    SecHttpError,
    SecResponseError,
    SecTransportError,
    _decode_body,
    validate_sec_url,
)


class QueueTransport:
    def __init__(self, responses: list[HttpResult]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, Mapping[str, str]]] = []

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        maximum_bytes: int,
    ) -> HttpResult:
        assert timeout == 30.0
        assert maximum_bytes == 50_000_000
        self.calls.append((url, headers))
        return self.responses.pop(0)


def response(status: int = 200, *, retry_after: str | None = None) -> HttpResult:
    headers = {"content-type": "application/json"}
    if retry_after is not None:
        headers["retry-after"] = retry_after
    return HttpResult(
        url="https://data.sec.gov/submissions/CIK0000320193.json",
        status_code=status,
        headers=headers,
        body=b'{"cik":"0000320193"}',
    )


def test_client_declares_identity_and_normalizes_cik() -> None:
    transport = QueueTransport([response()])
    client = SecClient(
        user_agent="Kalki tests test@example.com",
        transport=transport,
        limiter=RateLimiter(10, monotonic=lambda: 0.0, sleep=lambda _: None),
        now=lambda: datetime(2026, 8, 21, tzinfo=UTC),
    )

    document = client.fetch_submissions(320193)

    url, headers = transport.calls[0]
    assert url == "https://data.sec.gov/submissions/CIK0000320193.json"
    assert headers["User-Agent"] == "Kalki tests test@example.com"
    assert headers["Accept"] == "application/json"
    assert document.cik == "0000320193"
    assert document.retrieved_at.tzinfo is UTC


def test_client_rejects_header_injection_in_identity() -> None:
    with pytest.raises(ValueError, match="contact email"):
        SecClient(user_agent="Kalki a@b.test\r\nInjected: yes")


def test_client_fetches_only_exact_bounded_primary_document_path() -> None:
    calls: list[tuple[str, Mapping[str, str], int]] = []

    class PrimaryTransport:
        def get(
            self,
            url: str,
            *,
            headers: Mapping[str, str],
            timeout: float,
            maximum_bytes: int,
        ) -> HttpResult:
            calls.append((url, headers, maximum_bytes))
            return HttpResult(
                url=url,
                status_code=200,
                headers={"content-type": "text/xml"},
                body=b"<ownershipDocument/>",
            )

    client = SecClient(
        user_agent="Kalki tests test@example.com",
        transport=PrimaryTransport(),
        limiter=RateLimiter(10, monotonic=lambda: 0.0, sleep=lambda _: None),
        now=lambda: datetime(2026, 8, 29, tzinfo=UTC),
    )
    document = client.fetch_primary_document(
        cik="0001001385",
        accession_number="0001437749-26-029167",
        document_name="xslF345X06/rdgdoc.xml",
    )

    assert calls[0][0] == (
        "https://www.sec.gov/Archives/edgar/data/1001385/000143774926029167/xslF345X06/rdgdoc.xml"
    )
    assert calls[0][1]["Accept"].startswith("application/xml")
    assert calls[0][2] == MAXIMUM_PRIMARY_DOCUMENT_BYTES
    assert document.content_sha256 == hashlib.sha256(document.body).hexdigest()


def test_client_fetches_financing_html_under_separate_media_and_size_boundary() -> None:
    calls: list[tuple[str, Mapping[str, str], int]] = []

    class HtmlTransport:
        def get(
            self,
            url: str,
            *,
            headers: Mapping[str, str],
            timeout: float,
            maximum_bytes: int,
        ) -> HttpResult:
            calls.append((url, headers, maximum_bytes))
            return HttpResult(
                url=url,
                status_code=200,
                headers={"content-type": "text/html; charset=utf-8"},
                body=b"<html><p>Primary filing.</p></html>",
            )

    client = SecClient(
        user_agent="Kalki tests test@example.com",
        transport=HtmlTransport(),
        limiter=RateLimiter(10, monotonic=lambda: 0.0, sleep=lambda _: None),
        now=lambda: datetime(2026, 8, 30, tzinfo=UTC),
    )
    document = client.fetch_primary_html_document(
        cik="0001990251",
        accession_number="0001213900-26-094944",
        document_name="ea0303809-424b4_wellchange.htm",
    )
    assert calls[0][1]["Accept"].startswith("text/html")
    assert calls[0][2] == MAXIMUM_FINANCING_PRIMARY_DOCUMENT_BYTES
    assert document.content_sha256 == hashlib.sha256(document.body).hexdigest()


@pytest.mark.parametrize(
    ("accession", "document_name"),
    [
        ("invalid", "primary.xml"),
        ("0001437749-26-029167", "../primary.xml"),
        ("0001437749-26-029167", "xsl/../primary.xml"),
        ("0001437749-26-029167", "xsl/second/primary.xml"),
        ("0001437749-26-029167", "primary.xml?download=1"),
    ],
)
def test_client_rejects_unvalidated_primary_document_identity(
    accession: str, document_name: str
) -> None:
    client = SecClient(user_agent="Kalki tests test@example.com")
    with pytest.raises(ValueError):
        client.fetch_primary_document(
            cik="0001001385",
            accession_number=accession,
            document_name=document_name,
        )


def test_client_retries_throttling_with_retry_after() -> None:
    transport = QueueTransport([response(429, retry_after="3"), response()])
    delays: list[float] = []
    client = SecClient(
        user_agent="Kalki tests test@example.com",
        transport=transport,
        limiter=RateLimiter(10, monotonic=lambda: 0.0, sleep=lambda _: None),
        retry_sleep=delays.append,
    )

    client.fetch_submissions("0000320193")

    assert len(transport.calls) == 2
    assert delays == [3.0]


def test_client_fails_safely_after_retry_limit() -> None:
    client = SecClient(
        user_agent="Kalki tests test@example.com",
        transport=QueueTransport([response(503)]),
        limiter=RateLimiter(10, monotonic=lambda: 0.0, sleep=lambda _: None),
        maximum_attempts=1,
    )

    with pytest.raises(SecHttpError) as failure:
        client.fetch_submissions("320193")

    assert failure.value.status_code == 503


def test_client_rejects_naive_retrieval_clock() -> None:
    client = SecClient(
        user_agent="Kalki tests test@example.com",
        transport=QueueTransport([response()]),
        limiter=RateLimiter(10, monotonic=lambda: 0.0, sleep=lambda _: None),
        now=lambda: datetime(2026, 8, 21),
    )

    with pytest.raises(SecResponseError, match="timezone-aware"):
        client.fetch_submissions(320193)


def test_rate_limiter_spaces_requests() -> None:
    current = [100.0]
    delays: list[float] = []

    def sleep(seconds: float) -> None:
        delays.append(seconds)
        current[0] += seconds

    limiter = RateLimiter(2, monotonic=lambda: current[0], sleep=sleep)
    limiter.wait()
    limiter.wait()
    limiter.wait()

    assert delays == [0.5, 0.5]


def test_compressed_response_cannot_expand_past_limit() -> None:
    compressed = gzip.compress(b"x" * 101)

    with pytest.raises(SecResponseError, match="size limit"):
        _decode_body(compressed, "gzip", 100)


@pytest.mark.parametrize(
    "url",
    [
        "http://data.sec.gov/submissions/example.json",
        "https://example.com/submissions/example.json",
        "https://user:password@data.sec.gov/example.json",
        "https://data.sec.gov:8443/example.json",
        "https://data.sec.gov:not-a-port/example.json",
        "https://data.sec.gov/example.json?redirect=https://example.com",
    ],
)
def test_sec_url_boundary_rejects_unapproved_origins(url: str) -> None:
    with pytest.raises(SecTransportError):
        validate_sec_url(url)
