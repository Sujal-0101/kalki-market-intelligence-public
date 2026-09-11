"""Tests for disabled-by-default, deduplicated Discord research alerts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from kalki_market_intelligence.notifications.cli import main as discord_cli_main
from kalki_market_intelligence.notifications.contracts import (
    DeliveryErrorCode,
    DeliveryStatus,
    DiscordPayload,
    NotificationDelivery,
)
from kalki_market_intelligence.notifications.discord import (
    DiscordNotifier,
    DiscordRateLimiter,
    DiscordTransportError,
    WebhookHttpResult,
)
from kalki_market_intelligence.notifications.templates import (
    DISCLAIMER,
    ResearchNotification,
    render_connection_test,
    render_research_notification,
)
from kalki_market_intelligence.notifications.webhook_url import validate_discord_webhook_url
from kalki_market_intelligence.signals.contracts import RiskProfile, SignalLabel

WEBHOOK_TOKEN = "synthetic_test_token_1234567890"
WEBHOOK_URL = f"https://discord.com/api/webhooks/123456789012345678/{WEBHOOK_TOKEN}"
NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)


class QueueTransport:
    def __init__(self, responses: list[WebhookHttpResult | DiscordTransportError]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, bytes, Mapping[str, str]]] = []

    def post(
        self,
        url: str,
        *,
        body: bytes,
        headers: Mapping[str, str],
        timeout: float,
        maximum_bytes: int,
    ) -> WebhookHttpResult:
        assert timeout == 10
        assert maximum_bytes == 100_000
        self.calls.append((url, body, headers))
        response = self.responses.pop(0)
        if isinstance(response, DiscordTransportError):
            raise response
        return response


class FakeClock:
    def __init__(self) -> None:
        self.value = 100.0
        self.delays: list[float] = []

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.delays.append(seconds)
        self.value += seconds


def notification(
    *, prediction_id: str = "10000000-0000-4000-8000-000000000001"
) -> ResearchNotification:
    return ResearchNotification(
        prediction_id=UUID(prediction_id),
        published_at=NOW,
        label=SignalLabel.SPECULATIVE_OPPORTUNITY,
        risk_profile=RiskProfile.AGGRESSIVE_SPECULATIVE,
        opportunity_points=77,
        risk_points=81,
        research_confidence_points=62,
        horizon_days=90,
        evaluation_due_on=date(2026, 11, 22),
        evidence_count=3,
        signal_fingerprint="a" * 64,
    )


def result(
    status_code: int = 200,
    *,
    headers: Mapping[str, str] | None = None,
    body: bytes = b'{"id":"987654321098765432"}',
) -> WebhookHttpResult:
    return WebhookHttpResult(status_code=status_code, headers=headers or {}, body=body)


def notifier(
    transport: QueueTransport,
    *,
    enabled: bool = True,
    maximum_attempts: int = 3,
    clock: FakeClock | None = None,
) -> DiscordNotifier:
    selected_clock = clock or FakeClock()
    limiter = DiscordRateLimiter(
        2,
        monotonic=selected_clock.monotonic,
        sleep=selected_clock.sleep,
    )
    return DiscordNotifier(
        enabled=enabled,
        webhook_url=WEBHOOK_URL if enabled else None,
        transport=transport,
        limiter=limiter,
        retry_sleep=selected_clock.sleep,
        maximum_attempts=maximum_attempts,
        now=lambda: NOW,
    )


def test_template_is_bounded_factual_and_cannot_ping_anyone() -> None:
    payload = render_research_notification(notification())
    serialized = payload.model_dump(mode="json")

    assert len(payload.content) <= 2_000
    assert DISCLAIMER in payload.content
    assert "81/100" in payload.content
    assert "not a probability" in payload.content
    assert "buy" not in payload.content.lower()
    assert "sell" not in payload.content.lower()
    assert serialized["allowed_mentions"] == {"parse": []}
    assert "@" not in payload.content
    assert "market data" in render_connection_test().content


def test_disabled_switch_prevents_secret_requirement_and_network_access() -> None:
    transport = QueueTransport([])
    delivery = notifier(transport, enabled=False).send_research(notification())

    assert delivery.status is DeliveryStatus.DISABLED
    assert delivery.attempts == 0
    assert delivery.destination_sha256 is None
    assert transport.calls == []


def test_success_is_confirmed_audited_and_deduplicated() -> None:
    transport = QueueTransport([result()])
    client = notifier(transport)

    sent = client.send_research(notification())
    duplicate = client.send_research(notification())

    assert sent.status is DeliveryStatus.SENT
    assert sent.discord_message_id == "987654321098765432"
    assert sent.destination_sha256 is not None
    assert duplicate.status is DeliveryStatus.DUPLICATE
    assert duplicate.prior_notification_key == sent.notification_key
    assert len(transport.calls) == 1
    url, body, headers = transport.calls[0]
    assert url.endswith("?wait=true")
    assert json.loads(body)["allowed_mentions"] == {"parse": []}
    assert headers["Content-Type"] == "application/json"
    audit_json = "\n".join(item.model_dump_json() for item in client.records)
    assert WEBHOOK_TOKEN not in audit_json
    assert WEBHOOK_URL not in audit_json


def test_429_honors_discord_retry_after_then_confirms_success() -> None:
    clock = FakeClock()
    transport = QueueTransport(
        [
            result(429, headers={"retry-after": "2.5"}, body=b'{"retry_after":2.5}'),
            result(),
        ]
    )
    client = notifier(transport, clock=clock)

    delivery = client.send_research(notification())

    assert delivery.status is DeliveryStatus.SENT
    assert delivery.attempts == 2
    assert sum(clock.delays) == 2.5
    assert len(transport.calls) == 2


def test_exhausted_or_invalid_rate_limit_fails_without_unbounded_sleep() -> None:
    clock = FakeClock()
    transport = QueueTransport([result(429, headers={"retry-after": "9999"})])
    delivery = notifier(transport, maximum_attempts=1, clock=clock).send_research(notification())

    assert delivery.status is DeliveryStatus.RATE_LIMITED
    assert delivery.error_code is DeliveryErrorCode.RATE_LIMIT_EXHAUSTED
    assert clock.delays == []


def test_definitive_rejection_can_be_corrected_and_retried() -> None:
    transport = QueueTransport([result(400, body=b'{"message":"bad request"}'), result()])
    client = notifier(transport)

    rejected = client.send_research(notification())
    sent = client.send_research(notification())

    assert rejected.status is DeliveryStatus.REJECTED
    assert rejected.error_code is DeliveryErrorCode.HTTP_REJECTED
    assert sent.status is DeliveryStatus.SENT
    assert len(transport.calls) == 2


@pytest.mark.parametrize(
    ("response", "error_code"),
    [
        (result(503), DeliveryErrorCode.SERVER_AMBIGUOUS),
        (result(200, body=b"not-json"), DeliveryErrorCode.RESPONSE_INVALID),
        (DiscordTransportError("synthetic timeout"), DeliveryErrorCode.TRANSPORT_AMBIGUOUS),
    ],
)
def test_ambiguous_delivery_is_not_retried_or_duplicated(
    response: WebhookHttpResult | DiscordTransportError,
    error_code: DeliveryErrorCode,
) -> None:
    transport = QueueTransport([response])
    client = notifier(transport)

    uncertain = client.send_research(notification())
    duplicate = client.send_research(notification())

    assert uncertain.status is DeliveryStatus.DELIVERY_UNCERTAIN
    assert uncertain.error_code is error_code
    assert duplicate.status is DeliveryStatus.DUPLICATE
    assert len(transport.calls) == 1


def test_local_rate_limiter_spaces_distinct_notifications() -> None:
    clock = FakeClock()
    transport = QueueTransport([result(), result()])
    client = notifier(transport, clock=clock)

    client.send_research(notification())
    client.send_research(notification(prediction_id="10000000-0000-4000-8000-000000000002"))

    assert clock.delays == [0.5]


def test_success_rate_headers_defer_the_next_distinct_notification() -> None:
    clock = FakeClock()
    transport = QueueTransport(
        [
            result(headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset-after": "3"}),
            result(),
        ]
    )
    client = notifier(transport, clock=clock)

    client.send_research(notification())
    client.send_research(notification(prediction_id="10000000-0000-4000-8000-000000000002"))

    assert clock.delays == [3]


def test_redirect_response_is_not_followed_or_retried() -> None:
    transport = QueueTransport([result(302, headers={"location": "https://example.com"})])
    client = notifier(transport)

    delivery = client.send_research(notification())

    assert delivery.status is DeliveryStatus.DELIVERY_UNCERTAIN
    assert delivery.error_code is DeliveryErrorCode.SERVER_AMBIGUOUS
    assert len(transport.calls) == 1


def test_url_validation_returns_only_non_secret_destination_metadata() -> None:
    validated = validate_discord_webhook_url(WEBHOOK_URL)

    assert validated.execution_url.endswith("?wait=true")
    assert validated.destination_sha256 != WEBHOOK_TOKEN
    assert WEBHOOK_TOKEN not in repr(validated.destination_sha256)


def test_delivery_and_payload_contracts_are_closed() -> None:
    assert DiscordPayload.model_json_schema()["additionalProperties"] is False
    assert NotificationDelivery.model_json_schema()["additionalProperties"] is False


def test_live_cli_requires_explicit_confirmation_before_loading_configuration() -> None:
    with pytest.raises(SystemExit) as failure:
        discord_cli_main([])

    assert failure.value.code == 2
