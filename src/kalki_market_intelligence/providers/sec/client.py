"""Rate-limited, identified HTTP client for SEC public JSON endpoints."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import zlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from kalki_market_intelligence.providers.sec.contracts import Cik, SecEndpoint, normalize_cik

SEC_DATA_ORIGIN = "https://data.sec.gov"
SEC_ALLOWED_HOSTS = frozenset({"data.sec.gov", "www.sec.gov"})
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
MAXIMUM_PRIMARY_DOCUMENT_BYTES = 2_000_000
MAXIMUM_FINANCING_PRIMARY_DOCUMENT_BYTES = 8_000_000
PRIMARY_DOCUMENT_PATTERN = re.compile(
    r"^(?:[A-Za-z0-9][A-Za-z0-9._-]*/)?[A-Za-z0-9][A-Za-z0-9._-]*$"
)


class SecProviderError(RuntimeError):
    """Base class for safe SEC provider failures."""


class SecTransportError(SecProviderError):
    """The SEC endpoint could not be reached safely."""


class SecHttpError(SecProviderError):
    """The SEC returned a non-success response."""

    def __init__(self, status_code: int, url: str) -> None:
        super().__init__(f"SEC request failed with HTTP {status_code}: {url}")
        self.status_code = status_code
        self.url = url


class SecResponseError(SecProviderError):
    """The SEC response violated a required size, type, or JSON boundary."""


@dataclass(frozen=True, slots=True)
class HttpResult:
    """Transport response before SEC-specific validation."""

    url: str
    status_code: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True, slots=True)
class SecFetchedDocument:
    """Validated raw bytes and provenance for one successful SEC response."""

    endpoint: SecEndpoint
    cik: Cik
    url: str
    status_code: int
    headers: Mapping[str, str]
    body: bytes
    content_sha256: str
    retrieved_at: datetime


@dataclass(frozen=True, slots=True)
class SecFetchedPrimaryDocument:
    """Validated raw bytes for one exact SEC primary filing document."""

    cik: Cik
    accession_number: str
    document_name: str
    url: str
    status_code: int
    headers: Mapping[str, str]
    body: bytes
    content_sha256: str
    retrieved_at: datetime


class HttpTransport(Protocol):
    """Injectable GET transport used by deterministic tests."""

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        maximum_bytes: int,
    ) -> HttpResult: ...


def validate_sec_url(url: str) -> None:
    """Allow only HTTPS requests to the two documented SEC public data hosts."""

    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError as error:
        raise SecTransportError("SEC URL has an invalid port") from error
    inline_viewer_query = (
        parsed.hostname == "www.sec.gov"
        and parsed.path == "/ixviewer/doc/action"
        and re.fullmatch(
            r"doc=/Archives/edgar/data/\d{1,10}/\d{18}/[A-Za-z0-9][A-Za-z0-9._-]*[.](?:htm|html)",
            parsed.query,
            re.IGNORECASE,
        )
        is not None
    )
    if (
        parsed.scheme != "https"
        or parsed.hostname not in SEC_ALLOWED_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or (parsed.query and not inline_viewer_query)
        or (not parsed.query and parsed.path == "/ixviewer/doc/action")
        or parsed.fragment
    ):
        raise SecTransportError("SEC URL is outside the approved HTTPS origins")


class _SecRedirectHandler(HTTPRedirectHandler):
    def redirect_request(  # type: ignore[no-untyped-def]
        self,
        req,
        fp,
        code,
        msg,
        headers,
        newurl,  # noqa: ANN001
    ):
        validate_sec_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class UrllibHttpTransport:
    """Standard-library transport with redirect and decoded-size boundaries."""

    def __init__(self) -> None:
        self._opener = build_opener(_SecRedirectHandler())

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        maximum_bytes: int,
    ) -> HttpResult:
        validate_sec_url(url)
        request = Request(  # noqa: S310 - URL is restricted to approved SEC HTTPS origins
            url, headers=dict(headers), method="GET"
        )
        try:
            with self._opener.open(request, timeout=timeout) as response:  # noqa: S310
                body = response.read(maximum_bytes + 1)
                result = HttpResult(
                    url=response.geturl(),
                    status_code=response.status,
                    headers={key.lower(): value for key, value in response.headers.items()},
                    body=body,
                )
        except HTTPError as error:
            body = error.read(maximum_bytes + 1)
            result = HttpResult(
                url=error.geturl(),
                status_code=error.code,
                headers={key.lower(): value for key, value in error.headers.items()},
                body=body,
            )
        except (TimeoutError, URLError, OSError) as error:
            raise SecTransportError(f"SEC transport failed: {type(error).__name__}") from error

        validate_sec_url(result.url)
        if len(result.body) > maximum_bytes:
            raise SecResponseError("SEC response exceeded the configured size limit")
        return HttpResult(
            url=result.url,
            status_code=result.status_code,
            headers=result.headers,
            body=_decode_body(result.body, result.headers.get("content-encoding"), maximum_bytes),
        )


def _decode_body(body: bytes, encoding: str | None, maximum_bytes: int) -> bytes:
    if encoding is None or encoding.lower() == "identity":
        decoded = body
    elif encoding.lower() in {"gzip", "deflate"}:
        window_bits = zlib.MAX_WBITS | 16 if encoding.lower() == "gzip" else zlib.MAX_WBITS
        decompressor = zlib.decompressobj(window_bits)
        try:
            decoded = decompressor.decompress(body, maximum_bytes + 1)
            if len(decoded) <= maximum_bytes:
                decoded += decompressor.flush(maximum_bytes + 1 - len(decoded))
        except zlib.error as error:
            raise SecResponseError("SEC response has invalid compressed content") from error
        if decompressor.unconsumed_tail:
            raise SecResponseError("decoded SEC response exceeded the configured size limit")
    else:
        raise SecResponseError(f"unsupported SEC content encoding: {encoding}")
    if len(decoded) > maximum_bytes:
        raise SecResponseError("decoded SEC response exceeded the configured size limit")
    return decoded


class RateLimiter:
    """Thread-safe fixed-interval limiter shared by one SEC client."""

    def __init__(
        self,
        requests_per_second: float,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not 0 < requests_per_second <= 10:
            raise ValueError("SEC request rate must be greater than 0 and no more than 10/second")
        self._interval = 1.0 / requests_per_second
        self._monotonic = monotonic
        self._sleep = sleep
        self._next_request_at = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = self._monotonic()
            delay = max(0.0, self._next_request_at - now)
            if delay:
                self._sleep(delay)
                now = self._monotonic()
            self._next_request_at = max(now, self._next_request_at) + self._interval


class SecClient:
    """Fetch SEC submissions and company facts under an explicit access policy."""

    def __init__(
        self,
        *,
        user_agent: str,
        requests_per_second: float = 2.0,
        timeout_seconds: float = 30.0,
        maximum_response_bytes: int = 50_000_000,
        maximum_attempts: int = 3,
        transport: HttpTransport | None = None,
        limiter: RateLimiter | None = None,
        retry_sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        normalized_agent = user_agent.strip()
        if (
            len(normalized_agent) < 10
            or len(normalized_agent) > 255
            or "@" not in normalized_agent
            or " " not in normalized_agent
            or not normalized_agent.isprintable()
        ):
            raise ValueError("SEC user agent must identify the application and a contact email")
        if not 0 < requests_per_second <= 10:
            raise ValueError("SEC request rate must be greater than 0 and no more than 10/second")
        if timeout_seconds <= 0:
            raise ValueError("SEC timeout must be positive")
        if maximum_response_bytes < 1:
            raise ValueError("SEC maximum response size must be positive")
        if maximum_attempts < 1:
            raise ValueError("SEC maximum attempts must be at least one")
        self._headers = {
            "User-Agent": normalized_agent,
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
        }
        self._timeout_seconds = timeout_seconds
        self._maximum_response_bytes = maximum_response_bytes
        self._maximum_attempts = maximum_attempts
        self._transport = transport or UrllibHttpTransport()
        self._limiter = limiter or RateLimiter(requests_per_second)
        self._retry_sleep = retry_sleep
        self._now = now or (lambda: datetime.now(UTC))

    def fetch_submissions(self, cik: str | int) -> SecFetchedDocument:
        normalized = _validated_cik(cik)
        return self._fetch(
            endpoint="submissions",
            cik=normalized,
            url=f"{SEC_DATA_ORIGIN}/submissions/CIK{normalized}.json",
        )

    def fetch_companyfacts(self, cik: str | int) -> SecFetchedDocument:
        normalized = _validated_cik(cik)
        return self._fetch(
            endpoint="companyfacts",
            cik=normalized,
            url=f"{SEC_DATA_ORIGIN}/api/xbrl/companyfacts/CIK{normalized}.json",
        )

    def fetch_primary_document(
        self,
        *,
        cik: str | int,
        accession_number: str,
        document_name: str,
    ) -> SecFetchedPrimaryDocument:
        """Fetch one exact, metadata-derived SEC primary XML document."""

        normalized_cik = _validated_cik(cik)
        if re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession_number) is None:
            raise ValueError("SEC accession number is invalid")
        if len(document_name) > 255 or PRIMARY_DOCUMENT_PATTERN.fullmatch(document_name) is None:
            raise ValueError("SEC primary document name is invalid")
        url = (
            "https://www.sec.gov/Archives/edgar/data/"
            f"{int(normalized_cik)}/{accession_number.replace('-', '')}/{document_name}"
        )
        response, retrieved_at = self._request(
            url=url,
            accept="application/xml, text/xml, text/plain, application/octet-stream",
            maximum_bytes=min(
                self._maximum_response_bytes,
                MAXIMUM_PRIMARY_DOCUMENT_BYTES,
            ),
        )
        if response.url != url:
            raise SecResponseError("SEC primary document redirected away from its metadata URL")
        media_type = response.headers.get("content-type", "").split(";", maxsplit=1)[0].lower()
        if media_type not in {
            "application/xml",
            "text/xml",
            "text/plain",
            "application/octet-stream",
        }:
            raise SecResponseError(
                f"SEC primary document has unexpected media type: {media_type or 'missing'}"
            )
        if not response.body:
            raise SecResponseError("SEC primary document is empty")
        return SecFetchedPrimaryDocument(
            cik=normalized_cik,
            accession_number=accession_number,
            document_name=document_name,
            url=response.url,
            status_code=response.status_code,
            headers=response.headers,
            body=response.body,
            content_sha256=hashlib.sha256(response.body).hexdigest(),
            retrieved_at=retrieved_at,
        )

    def fetch_primary_html_document(
        self,
        *,
        cik: str | int,
        accession_number: str,
        document_name: str,
    ) -> SecFetchedPrimaryDocument:
        """Fetch one metadata-derived SEC filing HTML without weakening XML limits."""

        normalized_cik = _validated_cik(cik)
        if re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession_number) is None:
            raise ValueError("SEC accession number is invalid")
        if len(document_name) > 255 or PRIMARY_DOCUMENT_PATTERN.fullmatch(document_name) is None:
            raise ValueError("SEC primary document name is invalid")
        url = (
            "https://www.sec.gov/Archives/edgar/data/"
            f"{int(normalized_cik)}/{accession_number.replace('-', '')}/{document_name}"
        )
        response, retrieved_at = self._request(
            url=url,
            accept="text/html, application/xhtml+xml",
            maximum_bytes=min(
                self._maximum_response_bytes,
                MAXIMUM_FINANCING_PRIMARY_DOCUMENT_BYTES,
            ),
        )
        if response.url != url:
            raise SecResponseError("SEC primary HTML redirected away from its metadata URL")
        media_type = response.headers.get("content-type", "").split(";", maxsplit=1)[0].lower()
        if media_type not in {"text/html", "application/xhtml+xml"}:
            raise SecResponseError(
                f"SEC primary HTML has unexpected media type: {media_type or 'missing'}"
            )
        if not response.body:
            raise SecResponseError("SEC primary HTML is empty")
        return SecFetchedPrimaryDocument(
            cik=normalized_cik,
            accession_number=accession_number,
            document_name=document_name,
            url=response.url,
            status_code=response.status_code,
            headers=response.headers,
            body=response.body,
            content_sha256=hashlib.sha256(response.body).hexdigest(),
            retrieved_at=retrieved_at,
        )

    def _fetch(self, *, endpoint: SecEndpoint, cik: Cik, url: str) -> SecFetchedDocument:
        response, retrieved_at = self._request(
            url=url,
            accept="application/json",
            maximum_bytes=self._maximum_response_bytes,
        )
        _validate_json_response(response)
        return SecFetchedDocument(
            endpoint=endpoint,
            cik=cik,
            url=response.url,
            status_code=response.status_code,
            headers=response.headers,
            body=response.body,
            content_sha256=hashlib.sha256(response.body).hexdigest(),
            retrieved_at=retrieved_at,
        )

    def _request(self, *, url: str, accept: str, maximum_bytes: int) -> tuple[HttpResult, datetime]:
        for attempt in range(1, self._maximum_attempts + 1):
            self._limiter.wait()
            headers = dict(self._headers)
            headers["Accept"] = accept
            response = self._transport.get(
                url,
                headers=headers,
                timeout=self._timeout_seconds,
                maximum_bytes=maximum_bytes,
            )
            validate_sec_url(response.url)
            if len(response.body) > maximum_bytes:
                raise SecResponseError("SEC response exceeded the configured size limit")
            response = HttpResult(
                url=response.url,
                status_code=response.status_code,
                headers={key.lower(): value for key, value in response.headers.items()},
                body=response.body,
            )
            if response.status_code == 200:
                observed_at = self._now()
                if observed_at.tzinfo is None or observed_at.utcoffset() is None:
                    raise SecResponseError("SEC retrieval clock must return a timezone-aware value")
                return response, observed_at.astimezone(UTC)
            if (
                response.status_code not in RETRYABLE_STATUS_CODES
                or attempt == self._maximum_attempts
            ):
                raise SecHttpError(response.status_code, url)
            self._retry_sleep(_retry_delay(response.headers.get("retry-after"), attempt))
        raise AssertionError("unreachable SEC retry state")


def _validated_cik(value: str | int) -> Cik:
    normalized = normalize_cik(value)
    if not isinstance(normalized, str) or len(normalized) != 10 or not normalized.isdigit():
        raise ValueError("CIK must contain between one and ten digits")
    return normalized


def _validate_json_response(response: HttpResult) -> None:
    media_type = response.headers.get("content-type", "").split(";", maxsplit=1)[0].lower()
    if media_type not in {"application/json", "text/json"}:
        raise SecResponseError(f"SEC response has unexpected media type: {media_type or 'missing'}")
    try:
        decoded: object = json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SecResponseError("SEC response is not valid UTF-8 JSON") from error
    if not isinstance(decoded, dict):
        raise SecResponseError("SEC response JSON must be an object")


def _retry_delay(retry_after: str | None, attempt: int) -> float:
    if retry_after is not None:
        try:
            return min(60.0, max(0.0, float(retry_after)))
        except ValueError:
            pass
    return min(60.0, float(2 ** (attempt - 1)))
