"""Closed, provenance-preserving contracts for trusted human research leads.

Discord content is data only. These contracts deliberately contain no fields
that can alter prompts, rules, model settings, or publication decisions.
"""

from __future__ import annotations

import ipaddress
import re
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Annotated
from urllib.parse import SplitResult, urlsplit, urlunsplit
from uuid import UUID, uuid4

from pydantic import Field, StringConstraints, field_validator

from kalki_market_intelligence.contracts.common import ContractModel, NonEmptyText, ShortText

SNOWFLAKE = re.compile(r"^[0-9]{17,20}$")
TICKER = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,14}$")
CIK = re.compile(r"^[0-9]{1,10}$")
TICKER_LABEL = re.compile(r"(?im)^\s*ticker\s*:\s*\$?([A-Za-z][A-Za-z0-9.\-]{0,14})\s*$")
CASHTAG = re.compile(r"(?<![A-Za-z0-9])\$([A-Za-z][A-Za-z0-9.\-]{0,14})(?![A-Za-z0-9])")
type Snowflake = Annotated[
    str, StringConstraints(min_length=17, max_length=20, pattern=r"^[0-9]+$")
]


class HumanLeadStatus(StrEnum):
    RECEIVED = "received"
    VALIDATING = "validating"
    DUPLICATE = "duplicate"
    QUEUED = "queued"
    RETAINED = "retained"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    INCONCLUSIVE = "inconclusive"
    REJECTED = "rejected"
    FAILED = "failed"
    CANCELLED = "cancelled"


class HumanLeadPriority(StrEnum):
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


def _safe_public_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("research URLs must use HTTP or HTTPS")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("research URLs require a public hostname without credentials")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in {"localhost", "localhost.localdomain", "metadata.google.internal"}:
        raise ValueError("research URLs may not target local or metadata hosts")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
    ):
        raise ValueError("research URLs may not target private or reserved IP addresses")
    normalized = urlunsplit(
        SplitResult(parsed.scheme.lower(), hostname, parsed.path or "/", parsed.query, "")
    )
    if len(normalized) > 2_048:
        raise ValueError("research URL exceeds the configured size limit")
    return normalized


def validate_lead_url(value: str) -> str:
    """Normalize one human-supplied pointer without performing network access."""

    return _safe_public_url(value)


class HumanResearchLead(ContractModel):
    """A bounded human hypothesis awaiting normal Kalki investigation."""

    lead_id: UUID = Field(default_factory=uuid4)
    discord_message_id: Snowflake
    submitter_user_id: Snowflake
    channel_id: Snowflake
    submitted_at: datetime
    ticker: str | None = None
    cik: str | None = None
    hypothesis: NonEmptyText = Field(max_length=2_000)
    urls: tuple[str, ...] = Field(default=(), max_length=8)
    notes: ShortText | None = Field(default=None, max_length=2_000)
    original_submission_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dedupe_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    origin: str = "human"
    status: HumanLeadStatus = HumanLeadStatus.RECEIVED
    priority: HumanLeadPriority = HumanLeadPriority.NORMAL
    attempts: int = Field(default=0, ge=0, le=3)

    @field_validator("submitted_at")
    @classmethod
    def submitted_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("submitted_at must include a UTC offset")
        return value.astimezone(UTC)

    @field_validator("ticker")
    @classmethod
    def ticker_is_normalized(cls, value: str | None) -> str | None:
        if value is not None:
            normalized = value.strip().upper()
            if TICKER.fullmatch(normalized) is None:
                raise ValueError("ticker has an invalid format")
            return normalized
        return None

    @field_validator("cik")
    @classmethod
    def cik_is_normalized(cls, value: str | None) -> str | None:
        if value is not None:
            normalized = value.strip()
            if CIK.fullmatch(normalized) is None:
                raise ValueError("CIK has an invalid format")
            return normalized
        return None

    @field_validator("discord_message_id", "submitter_user_id", "channel_id")
    @classmethod
    def snowflake_is_valid(cls, value: str) -> str:
        if SNOWFLAKE.fullmatch(value) is None:
            raise ValueError("Discord identifiers must be stable snowflake IDs")
        return value

    @field_validator("urls")
    @classmethod
    def urls_are_safe(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_safe_public_url(value) for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("research URLs must be unique")
        return normalized

    @field_validator("origin")
    @classmethod
    def origin_is_human(cls, value: str) -> str:
        if value != "human":
            raise ValueError("human leads must retain human origin")
        return value

    @classmethod
    def from_submission(
        cls,
        *,
        discord_message_id: str,
        submitter_user_id: str,
        channel_id: str,
        submitted_at: datetime,
        hypothesis: str,
        ticker: str | None = None,
        cik: str | None = None,
        urls: tuple[str, ...] = (),
        notes: str | None = None,
        priority: HumanLeadPriority = HumanLeadPriority.NORMAL,
    ) -> HumanResearchLead:
        """Build a lead and bind its exact normalized submission to a digest."""

        normalized_urls = tuple(_safe_public_url(value) for value in urls)
        normalized_ticker = ticker.strip().upper() if ticker else ""
        normalized_cik = cik.strip() if cik else ""
        dedupe_canonical = "\n".join(
            (normalized_ticker, normalized_cik, hypothesis.strip(), *normalized_urls)
        )
        canonical = "\n".join(
            (
                discord_message_id,
                submitter_user_id,
                channel_id,
                hypothesis.strip(),
                *normalized_urls,
            )
        )
        return cls(
            discord_message_id=discord_message_id,
            submitter_user_id=submitter_user_id,
            channel_id=channel_id,
            submitted_at=submitted_at,
            hypothesis=hypothesis.strip(),
            ticker=ticker,
            cik=cik,
            urls=normalized_urls,
            notes=notes.strip() if notes else None,
            original_submission_sha256=sha256(canonical.encode("utf-8")).hexdigest(),
            dedupe_key=sha256(dedupe_canonical.encode("utf-8")).hexdigest(),
            priority=priority,
        )


def parse_discord_submission(
    payload: dict[str, object], *, channel_id: str, allowlist: frozenset[str]
) -> HumanResearchLead:
    """Parse one Discord message as bounded data; never interprets it as commands."""
    author = payload.get("author")
    if not isinstance(author, dict):
        raise ValueError("Discord payload has no author")
    submitter = author.get("id")
    message_id = payload.get("id")
    actual_channel = payload.get("channel_id")
    if not all(isinstance(value, str) for value in (submitter, message_id, actual_channel)):
        raise ValueError("Discord payload identifiers are invalid")
    assert isinstance(submitter, str)
    assert isinstance(message_id, str)
    assert isinstance(actual_channel, str)
    if actual_channel != channel_id or submitter not in allowlist:
        raise PermissionError("Discord research submission is not authorized")
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Discord research submission is empty")
    timestamp_raw = payload.get("timestamp")
    if not isinstance(timestamp_raw, str):
        raise ValueError("Discord payload timestamp is required")
    submitted_at = datetime.fromisoformat(timestamp_raw.replace("Z", "+00:00"))
    ticker = _extract_ticker(content)
    return HumanResearchLead.from_submission(
        discord_message_id=message_id,
        submitter_user_id=submitter,
        channel_id=actual_channel,
        submitted_at=submitted_at,
        hypothesis=content,
        ticker=ticker,
    )


def _extract_ticker(content: str) -> str | None:
    """Extract a ticker only from explicit, bounded notation.

    Free prose is never scanned for capitalized words: a plain ticker is
    accepted only when it is the complete message, while labelled and cash-tag
    forms may appear alongside a hypothesis.
    """

    stripped = content.strip()
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9.\-]{0,14}", stripped):
        return stripped.upper()
    labelled = TICKER_LABEL.search(content)
    if labelled is not None:
        return labelled.group(1).upper()
    cashtag = CASHTAG.search(content)
    return cashtag.group(1).upper() if cashtag is not None else None
