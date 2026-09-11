"""Replaceable provider boundary and disabled-by-default Twelve Data adapter."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import ValidationError

from kalki_market_intelligence.prospective.contracts import (
    SupportingBarBatch,
    SupportingBarRequest,
    SupportingDailyBar,
)

TWELVE_DATA_ORIGIN = "https://api.twelvedata.com"
TWELVE_DATA_TERMS = "https://twelvedata.com/terms"
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
PROVIDER_MIC_ALIASES = {
    "XNAS": frozenset({"XNAS", "XNGS", "XNMS", "XNCM"}),
    "XNYS": frozenset({"XNYS"}),
    "ARCX": frozenset({"ARCX"}),
    "XASE": frozenset({"XASE"}),
}


class ProspectiveMarketDataProvider(Protocol):
    def get_daily_bars(self, request: SupportingBarRequest) -> SupportingBarBatch: ...


class SupportingProviderError(RuntimeError):
    """Bounded base error that never contains credentials or raw response content."""


class ProviderTransportError(SupportingProviderError):
    pass


class ProviderResponseError(SupportingProviderError):
    pass


class ProviderHttpError(SupportingProviderError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"supporting market-data request failed with HTTP {status_code}")
        self.status_code = status_code
        self.retryable = status_code in RETRYABLE_STATUS_CODES


@dataclass(frozen=True, slots=True)
class ProviderHttpResult:
    url: str
    status_code: int
    headers: Mapping[str, str]
    body: bytes


class ProviderTransport(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        maximum_bytes: int,
    ) -> ProviderHttpResult: ...


class ProviderLimiter(Protocol):
    def wait(self) -> None: ...


def validate_twelve_data_url(url: str) -> None:
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError as error:
        raise ProviderTransportError("provider URL has an invalid port") from error
    if (
        parsed.scheme != "https"
        or parsed.hostname != "api.twelvedata.com"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.fragment
        or parsed.path != "/time_series"
    ):
        raise ProviderTransportError("provider URL is outside the approved endpoint")


class _ProviderRedirectHandler(HTTPRedirectHandler):
    def redirect_request(  # type: ignore[no-untyped-def]
        self,
        req,
        fp,
        code,
        msg,
        headers,
        newurl,  # noqa: ANN001
    ):
        validate_twelve_data_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class UrllibProviderTransport:
    def __init__(self) -> None:
        self._opener = build_opener(_ProviderRedirectHandler())

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        maximum_bytes: int,
    ) -> ProviderHttpResult:
        validate_twelve_data_url(url)
        request = Request(  # noqa: S310 - origin and endpoint are closed above
            url, headers=dict(headers), method="GET"
        )
        try:
            with self._opener.open(request, timeout=timeout) as response:  # noqa: S310
                body = response.read(maximum_bytes + 1)
                result = ProviderHttpResult(
                    url=response.geturl(),
                    status_code=response.status,
                    headers={key.lower(): value for key, value in response.headers.items()},
                    body=body,
                )
        except HTTPError as error:
            result = ProviderHttpResult(
                url=error.geturl(),
                status_code=error.code,
                headers={key.lower(): value for key, value in error.headers.items()},
                body=error.read(maximum_bytes + 1),
            )
        except (TimeoutError, URLError, OSError) as error:
            raise ProviderTransportError(
                f"provider transport failed: {type(error).__name__}"
            ) from error
        validate_twelve_data_url(result.url)
        if len(result.body) > maximum_bytes:
            raise ProviderResponseError("provider response exceeded the configured size limit")
        return result


class ProviderRateLimiter:
    """Conservative eight-per-minute and 800-per-rolling-day process guard."""

    def __init__(
        self,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._monotonic = monotonic
        self._sleep = sleep
        self._next_request_at = 0.0
        self._request_times: deque[float] = deque()
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            while True:
                now = self._monotonic()
                while self._request_times and self._request_times[0] <= now - 86_400:
                    self._request_times.popleft()
                minute_delay = max(0.0, self._next_request_at - now)
                daily_delay = (
                    max(0.0, self._request_times[0] + 86_400 - now)
                    if len(self._request_times) >= 800
                    else 0.0
                )
                delay = max(minute_delay, daily_delay)
                if not delay:
                    self._request_times.append(now)
                    self._next_request_at = now + 7.5
                    return
                self._sleep(delay)


class TwelveDataSupportingProvider:
    """Private non-display adapter; constructing it requires an injected API key."""

    provider_name = "twelve_data"
    authority = "SUPPORTING"
    requests_per_minute = 8
    requests_per_day = 800

    def __init__(
        self,
        *,
        api_key: str,
        transport: ProviderTransport | None = None,
        limiter: ProviderLimiter | None = None,
        timeout_seconds: float = 20.0,
        maximum_response_bytes: int = 2_000_000,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        normalized_key = api_key.strip()
        if not 8 <= len(normalized_key) <= 255 or not normalized_key.isprintable():
            raise ValueError("provider API key has an invalid shape")
        if timeout_seconds <= 0 or maximum_response_bytes < 1_000:
            raise ValueError("provider transport limits must be positive and bounded")
        self._headers = {
            "Authorization": f"apikey {normalized_key}",
            "Accept": "application/json",
            "User-Agent": "Kalki-Market-Intelligence/1.0 supporting-outcomes",
        }
        self._transport = transport or UrllibProviderTransport()
        self._limiter = limiter or ProviderRateLimiter()
        self._timeout_seconds = timeout_seconds
        self._maximum_response_bytes = maximum_response_bytes
        self._now = now or (lambda: datetime.now(UTC))

    def get_daily_bars(self, request: SupportingBarRequest) -> SupportingBarBatch:
        query = urlencode(
            {
                "symbol": request.symbol,
                "mic_code": request.mic,
                "interval": "1day",
                "start_date": request.start_date.isoformat(),
                "end_date": request.end_date.isoformat(),
                "order": "asc",
                "adjust": "splits",
                "format": "JSON",
            }
        )
        url = f"{TWELVE_DATA_ORIGIN}/time_series?{query}"
        self._limiter.wait()
        result = self._transport.get(
            url,
            headers=self._headers,
            timeout=self._timeout_seconds,
            maximum_bytes=self._maximum_response_bytes,
        )
        if result.status_code != 200:
            raise ProviderHttpError(result.status_code)
        response_hash = hashlib.sha256(result.body).hexdigest()
        observed_at = self._now()
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("provider retrieval clock must be timezone-aware")
        retrieved_at = observed_at.astimezone(UTC)
        payload = _json_object(result.body)
        if payload.get("status") != "ok":
            raise ProviderResponseError("provider response status was not ok")
        meta = _object(payload.get("meta"), "provider response meta")
        provider_mic = str(meta.get("mic_code", "")).upper()
        if (
            str(meta.get("symbol", "")).upper() != request.symbol
            or provider_mic not in PROVIDER_MIC_ALIASES.get(request.mic, frozenset())
            or str(meta.get("currency", "")).upper() != request.currency.value
            or meta.get("interval") != "1day"
        ):
            raise ProviderResponseError("provider response identity does not match request")
        values = payload.get("values")
        if not isinstance(values, list) or len(values) > 10_000:
            raise ProviderResponseError("provider response values are absent or oversized")
        try:
            bars = tuple(
                _parse_bar(
                    value,
                    request=request,
                    provider_mic=provider_mic,
                    response_hash=response_hash,
                    retrieved_at=retrieved_at,
                )
                for value in values
            )
            return SupportingBarBatch(
                request=request,
                bars=bars,
                response_sha256=response_hash,
                retrieved_at=retrieved_at,
            )
        except ValidationError as error:
            raise ProviderResponseError("provider bar failed the closed contract") from error


def _json_object(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProviderResponseError("provider response was not valid JSON") from error
    return _object(payload, "provider response")


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ProviderResponseError(f"{label} was not an object")
    return value


def _parse_bar(
    value: object,
    *,
    request: SupportingBarRequest,
    provider_mic: str,
    response_hash: str,
    retrieved_at: datetime,
) -> SupportingDailyBar:
    row = _object(value, "provider bar")
    required = {"datetime", "open", "high", "low", "close", "volume"}
    if set(row) != required:
        raise ProviderResponseError("provider bar fields do not match the closed schema")
    try:
        session_date = datetime.strptime(str(row["datetime"]), "%Y-%m-%d").date()
        prices = {name: Decimal(str(row[name])) for name in ("open", "high", "low", "close")}
        volume = int(str(row["volume"]))
    except (ValueError, TypeError, InvalidOperation) as error:
        raise ProviderResponseError("provider bar contains an invalid value") from error
    canonical = json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
    row_hash = hashlib.sha256(response_hash.encode() + b":" + canonical).hexdigest()
    return SupportingDailyBar(
        symbol=request.symbol,
        mic=request.mic,
        provider_mic=provider_mic,
        session_date=session_date,
        open=prices["open"],
        high=prices["high"],
        low=prices["low"],
        close=prices["close"],
        volume=volume,
        currency=request.currency,
        source_record_id=(
            f"twelve_data:{request.symbol}:{provider_mic}:{session_date.isoformat()}"
        ),
        source_content_sha256=row_hash,
        # Twelve Data does not provide a row-level EOD availability timestamp.
        # Conservatively use actual retrieval for both instead of claiming earlier knowledge.
        available_at=retrieved_at,
        retrieved_at=retrieved_at,
    )
