"""Secret-preserving Discord webhook URL validation."""

import re
from dataclasses import dataclass
from hashlib import sha256
from urllib.parse import urlsplit, urlunsplit

_WEBHOOK_PATH = re.compile(
    r"^/api/webhooks/(?P<webhook_id>[0-9]{17,20})/(?P<token>[A-Za-z0-9._-]{20,})$"
)


@dataclass(frozen=True, slots=True)
class ValidatedWebhookUrl:
    """Execution URL plus a non-secret destination identifier."""

    execution_url: str
    destination_sha256: str


def validate_discord_webhook_url(value: str) -> ValidatedWebhookUrl:
    """Restrict secrets to Discord's HTTPS execute-webhook origin and path."""

    parsed = urlsplit(value.strip())
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("Discord webhook URL has an invalid port") from error
    match = _WEBHOOK_PATH.fullmatch(parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "discord.com"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.query
        or parsed.fragment
        or match is None
    ):
        raise ValueError("Discord webhook URL must use the approved Discord HTTPS endpoint")
    webhook_id = match.group("webhook_id")
    destination = sha256(f"discord-webhook:{webhook_id}".encode()).hexdigest()
    execution_url = urlunsplit(("https", "discord.com", parsed.path, "wait=true", ""))
    return ValidatedWebhookUrl(
        execution_url=execution_url,
        destination_sha256=destination,
    )
