"""Explicit live connectivity gate for an approved private Discord destination."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from kalki_market_intelligence.config import Settings
from kalki_market_intelligence.notifications.contracts import DeliveryStatus
from kalki_market_intelligence.notifications.discord import DiscordNotifier


def main(argv: Sequence[str] | None = None) -> int:
    """Send one synthetic test only after an explicit command-line confirmation."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-live-send",
        action="store_true",
        help="confirm one real message to the locally configured private destination",
    )
    arguments = parser.parse_args(argv)
    if not arguments.confirm_live_send:
        parser.error("live Discord test requires --confirm-live-send")
    settings = Settings.load()
    if not settings.discord_enabled or settings.discord_webhook_url is None:
        print("Discord is disabled or its local webhook secret is absent.", file=sys.stderr)
        return 2
    notifier = DiscordNotifier(
        enabled=True,
        webhook_url=settings.discord_webhook_url.get_secret_value(),
        requests_per_second=settings.discord_requests_per_second,
        timeout_seconds=settings.discord_timeout_seconds,
        maximum_response_bytes=settings.discord_maximum_response_bytes,
        maximum_attempts=settings.discord_maximum_attempts,
    )
    result = notifier.send_connection_test()
    print(result.model_dump_json(indent=2))
    return 0 if result.status is DeliveryStatus.SENT else 1


if __name__ == "__main__":
    raise SystemExit(main())
