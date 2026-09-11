"""Disabled-by-default, secret-preserving Discord webhook adapter."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from http.client import HTTPException
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

from kalki_market_intelligence.notifications.contracts import (
    DeliveryErrorCode,
    DeliveryStatus,
    DiscordPayload,
    NotificationDelivery,
)
from kalki_market_intelligence.notifications.templates import (
    RadarNotification,
    ResearchNotification,
    render_connection_test,
    render_radar_notification,
    render_research_notification,
)
from kalki_market_intelligence.notifications.webhook_url import validate_discord_webhook_url


class DiscordTransportError(RuntimeError):
    """An ambiguous transport failure occurred without exposing its secret URL."""


@dataclass(frozen=True, slots=True)
class WebhookHttpResult:
    """Bounded response metadata returned by the injectable transport."""

    status_code: int
    headers: Mapping[str, str]
    body: bytes


class WebhookTransport(Protocol):
    """Injectable POST transport used by deterministic tests."""

    def post(
        self,
        url: str,
        *,
        body: bytes,
        headers: Mapping[str, str],
        timeout: float,
        maximum_bytes: int,
    ) -> WebhookHttpResult: ...


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        """Never forward a webhook token to another location."""

        return None


class UrllibWebhookTransport:
    """Standard-library HTTPS transport that rejects redirects and bounds output."""

    def __init__(self) -> None:
        self._opener = build_opener(_NoRedirectHandler())

    def post(
        self,
        url: str,
        *,
        body: bytes,
        headers: Mapping[str, str],
        timeout: float,
        maximum_bytes: int,
    ) -> WebhookHttpResult:
        request = Request(  # noqa: S310 - caller supplies a strictly validated Discord URL
            url,
            data=body,
            headers=dict(headers),
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=timeout) as response:  # noqa: S310
                response_body = response.read(maximum_bytes + 1)
                result = WebhookHttpResult(
                    status_code=response.status,
                    headers={key.lower(): value for key, value in response.headers.items()},
                    body=response_body,
                )
        except HTTPError as error:
            response_body = error.read(maximum_bytes + 1)
            result = WebhookHttpResult(
                status_code=error.code,
                headers={key.lower(): value for key, value in error.headers.items()},
                body=response_body,
            )
        except (HTTPException, TimeoutError, URLError, OSError) as error:
            raise DiscordTransportError(
                f"Discord transport failed ambiguously: {type(error).__name__}"
            ) from error
        if len(result.body) > maximum_bytes:
            raise DiscordTransportError("Discord response exceeded the configured size limit")
        return result


class DiscordRateLimiter:
    """Thread-safe local spacing plus server-directed deferral."""

    def __init__(
        self,
        requests_per_second: float,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not 0 < requests_per_second <= 2:
            raise ValueError(
                "Discord local request rate must be greater than 0 and at most 2/second"
            )
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

    def defer(self, seconds: float) -> None:
        if seconds < 0 or seconds > 300:
            raise ValueError("Discord retry delay is outside the safe bound")
        with self._lock:
            self._next_request_at = max(
                self._next_request_at,
                self._monotonic() + seconds,
            )


class DiscordNotifier:
    """Send bounded research alerts with deduplication and secret-free audits."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        webhook_url: str | None = None,
        requests_per_second: float = 0.5,
        timeout_seconds: float = 10,
        maximum_response_bytes: int = 100_000,
        maximum_attempts: int = 3,
        public_hostname: str = "localhost",
        transport: WebhookTransport | None = None,
        limiter: DiscordRateLimiter | None = None,
        retry_sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 30:
            raise ValueError("Discord timeout must be between 0 and 30 seconds")
        if not 1_000 <= maximum_response_bytes <= 1_000_000:
            raise ValueError("Discord response limit is outside the safe bound")
        if not 1 <= maximum_attempts <= 3:
            raise ValueError("Discord maximum attempts must be between 1 and 3")
        endpoint = None
        if enabled:
            if webhook_url is None:
                raise ValueError("enabled Discord notifications require a webhook secret")
            endpoint = validate_discord_webhook_url(webhook_url)
        self._enabled = enabled
        self._execution_url = endpoint.execution_url if endpoint else None
        self._destination_sha256 = endpoint.destination_sha256 if endpoint else None
        self._timeout_seconds = timeout_seconds
        self._maximum_response_bytes = maximum_response_bytes
        self._maximum_attempts = maximum_attempts
        self._public_hostname = public_hostname
        self._transport = transport or UrllibWebhookTransport()
        self._limiter = limiter or DiscordRateLimiter(requests_per_second)
        self._retry_sleep = retry_sleep
        self._now = now or (lambda: datetime.now(UTC))
        self._records: list[NotificationDelivery] = []
        self._suppressed_keys: set[str] = set()
        self._send_lock = threading.Lock()

    @property
    def records(self) -> tuple[NotificationDelivery, ...]:
        """Return immutable audit snapshots without webhook credentials."""

        return tuple(self._records)

    def send_research(self, notification: ResearchNotification) -> NotificationDelivery:
        """Send one published-research alert or return a safe suppression result."""

        return self._send(
            payload=render_research_notification(notification),
            notification_key=notification.notification_key,
            prediction_id=notification.prediction_id,
        )

    def send_radar(self, notification: RadarNotification) -> NotificationDelivery:
        """Send one evidence-backed filing-radar update."""

        return self._send(
            payload=render_radar_notification(
                notification,
                public_hostname=self._public_hostname,
            ),
            notification_key=notification.notification_key,
            prediction_id=None,
        )

    def send_connection_test(self) -> NotificationDelivery:
        """Send a synthetic, market-data-free connectivity message."""

        payload = render_connection_test()
        key = sha256(b"discord-connection-test-v1").hexdigest()
        return self._send(payload=payload, notification_key=key, prediction_id=None)

    def _send(
        self,
        *,
        payload: DiscordPayload,
        notification_key: str,
        prediction_id: UUID | None,
    ) -> NotificationDelivery:
        payload_bytes = payload.model_dump_json().encode("utf-8")
        payload_sha256 = sha256(payload_bytes).hexdigest()
        with self._send_lock:
            requested_at = self._now()
            if not self._enabled:
                return self._record(
                    notification_key=notification_key,
                    prediction_id=prediction_id,
                    requested_at=requested_at,
                    status=DeliveryStatus.DISABLED,
                    attempts=0,
                    payload_sha256=payload_sha256,
                )
            if notification_key in self._suppressed_keys:
                return self._record(
                    notification_key=notification_key,
                    prediction_id=prediction_id,
                    requested_at=requested_at,
                    status=DeliveryStatus.DUPLICATE,
                    attempts=0,
                    payload_sha256=payload_sha256,
                    prior_notification_key=notification_key,
                )
            return self._deliver(
                payload_bytes=payload_bytes,
                payload_sha256=payload_sha256,
                notification_key=notification_key,
                prediction_id=prediction_id,
                requested_at=requested_at,
            )

    def _deliver(
        self,
        *,
        payload_bytes: bytes,
        payload_sha256: str,
        notification_key: str,
        prediction_id: UUID | None,
        requested_at: datetime,
    ) -> NotificationDelivery:
        assert self._execution_url is not None
        attempts = 0
        while attempts < self._maximum_attempts:
            attempts += 1
            self._limiter.wait()
            try:
                response = self._transport.post(
                    self._execution_url,
                    body=payload_bytes,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "User-Agent": "Kalki-Market-Intelligence/0.1 (+local-research)",
                    },
                    timeout=self._timeout_seconds,
                    maximum_bytes=self._maximum_response_bytes,
                )
            except DiscordTransportError:
                return self._terminal_uncertain(
                    notification_key,
                    prediction_id,
                    requested_at,
                    attempts,
                    payload_sha256,
                    DeliveryErrorCode.TRANSPORT_AMBIGUOUS,
                )
            if response.status_code == 200:
                message_id = _discord_message_id(response.body)
                if message_id is None:
                    return self._terminal_uncertain(
                        notification_key,
                        prediction_id,
                        requested_at,
                        attempts,
                        payload_sha256,
                        DeliveryErrorCode.RESPONSE_INVALID,
                    )
                self._apply_rate_limit_headers(response.headers)
                self._suppressed_keys.add(notification_key)
                return self._record(
                    notification_key=notification_key,
                    prediction_id=prediction_id,
                    requested_at=requested_at,
                    status=DeliveryStatus.SENT,
                    attempts=attempts,
                    payload_sha256=payload_sha256,
                    discord_message_id=message_id,
                )
            if response.status_code == 429:
                retry_after = _retry_after_seconds(response)
                if retry_after is None or attempts == self._maximum_attempts:
                    return self._record(
                        notification_key=notification_key,
                        prediction_id=prediction_id,
                        requested_at=requested_at,
                        status=DeliveryStatus.RATE_LIMITED,
                        attempts=attempts,
                        payload_sha256=payload_sha256,
                        error_code=DeliveryErrorCode.RATE_LIMIT_EXHAUSTED,
                    )
                self._limiter.defer(retry_after)
                self._retry_sleep(retry_after)
                continue
            if 400 <= response.status_code < 500:
                return self._record(
                    notification_key=notification_key,
                    prediction_id=prediction_id,
                    requested_at=requested_at,
                    status=DeliveryStatus.REJECTED,
                    attempts=attempts,
                    payload_sha256=payload_sha256,
                    error_code=DeliveryErrorCode.HTTP_REJECTED,
                )
            return self._terminal_uncertain(
                notification_key,
                prediction_id,
                requested_at,
                attempts,
                payload_sha256,
                DeliveryErrorCode.SERVER_AMBIGUOUS,
            )
        raise AssertionError("bounded Discord delivery loop exhausted unexpectedly")

    def _terminal_uncertain(
        self,
        notification_key: str,
        prediction_id: UUID | None,
        requested_at: datetime,
        attempts: int,
        payload_sha256: str,
        error_code: DeliveryErrorCode,
    ) -> NotificationDelivery:
        self._suppressed_keys.add(notification_key)
        return self._record(
            notification_key=notification_key,
            prediction_id=prediction_id,
            requested_at=requested_at,
            status=DeliveryStatus.DELIVERY_UNCERTAIN,
            attempts=attempts,
            payload_sha256=payload_sha256,
            error_code=error_code,
        )

    def _record(
        self,
        *,
        notification_key: str,
        prediction_id: UUID | None,
        requested_at: datetime,
        status: DeliveryStatus,
        attempts: int,
        payload_sha256: str,
        discord_message_id: str | None = None,
        prior_notification_key: str | None = None,
        error_code: DeliveryErrorCode | None = None,
    ) -> NotificationDelivery:
        record = NotificationDelivery(
            notification_key=notification_key,
            prediction_id=prediction_id,
            requested_at=requested_at,
            completed_at=self._now(),
            status=status,
            attempts=attempts,
            payload_sha256=payload_sha256,
            destination_sha256=self._destination_sha256,
            discord_message_id=discord_message_id,
            prior_notification_key=prior_notification_key,
            error_code=error_code,
        )
        self._records.append(record)
        return record

    def _apply_rate_limit_headers(self, headers: Mapping[str, str]) -> None:
        if headers.get("x-ratelimit-remaining") != "0":
            return
        reset_after = _bounded_decimal(headers.get("x-ratelimit-reset-after"))
        if reset_after is not None:
            self._limiter.defer(reset_after)


def _discord_message_id(body: bytes) -> str | None:
    try:
        decoded: object = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(decoded, dict):
        return None
    message_id = decoded.get("id")
    if (
        not isinstance(message_id, str)
        or not message_id.isdigit()
        or not 17 <= len(message_id) <= 20
    ):
        return None
    return message_id


def _retry_after_seconds(response: WebhookHttpResult) -> float | None:
    header = _bounded_decimal(response.headers.get("retry-after"))
    if header is not None:
        return header
    try:
        decoded: object = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(decoded, dict):
        return None
    value = decoded.get("retry_after")
    if not isinstance(value, (int, float, str)) or isinstance(value, bool):
        return None
    return _bounded_decimal(str(value))


def _bounded_decimal(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        return None
    if not parsed.is_finite() or parsed < 0 or parsed > 300:
        return None
    return float(parsed)
