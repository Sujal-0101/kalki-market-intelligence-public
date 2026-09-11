"""Closed contracts for auditable notification delivery."""

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from kalki_market_intelligence.contracts.common import (
    ContractModel,
    Sha256Hex,
    ShortText,
    UtcDatetime,
)


class DeliveryStatus(StrEnum):
    """Terminal result of one notification request."""

    SENT = "sent"
    DUPLICATE = "duplicate"
    DISABLED = "disabled"
    REJECTED = "rejected"
    RATE_LIMITED = "rate_limited"
    DELIVERY_UNCERTAIN = "delivery_uncertain"


class DeliveryErrorCode(StrEnum):
    """Bounded failure reasons that never contain a webhook secret."""

    HTTP_REJECTED = "http_rejected"
    RATE_LIMIT_EXHAUSTED = "rate_limit_exhausted"
    RESPONSE_INVALID = "response_invalid"
    TRANSPORT_AMBIGUOUS = "transport_ambiguous"
    SERVER_AMBIGUOUS = "server_ambiguous"


class AllowedMentions(ContractModel):
    """Discord mention policy that permits no automatic parsing."""

    parse: tuple[()] = ()


class DiscordPayload(ContractModel):
    """Small Discord execute-webhook payload with mentions disabled."""

    content: str = Field(min_length=1, max_length=2_000)
    username: Literal["Kalki Market Intelligence"] = "Kalki Market Intelligence"
    allowed_mentions: AllowedMentions = Field(default_factory=AllowedMentions)


class NotificationDelivery(ContractModel):
    """Secret-free audit result for one requested delivery."""

    notification_key: Sha256Hex
    prediction_id: UUID | None
    requested_at: UtcDatetime
    completed_at: UtcDatetime
    status: DeliveryStatus
    attempts: int = Field(ge=0, le=3)
    payload_sha256: Sha256Hex
    destination_sha256: Sha256Hex | None
    discord_message_id: ShortText | None = None
    prior_notification_key: Sha256Hex | None = None
    error_code: DeliveryErrorCode | None = None

    @model_validator(mode="after")
    def result_is_internally_consistent(self) -> "NotificationDelivery":
        if self.completed_at < self.requested_at:
            raise ValueError("notification completion cannot predate its request")
        if self.status is DeliveryStatus.SENT:
            if self.discord_message_id is None or self.attempts < 1:
                raise ValueError("sent notification requires a message ID and attempt")
        elif self.discord_message_id is not None:
            raise ValueError("only a sent notification may contain a message ID")
        if self.status is DeliveryStatus.DUPLICATE:
            if self.prior_notification_key is None or self.attempts != 0:
                raise ValueError("duplicate notification must identify its prior key")
        elif self.prior_notification_key is not None:
            raise ValueError("only a duplicate may identify a prior notification")
        failed = {
            DeliveryStatus.REJECTED,
            DeliveryStatus.RATE_LIMITED,
            DeliveryStatus.DELIVERY_UNCERTAIN,
        }
        if (self.status in failed) != (self.error_code is not None):
            raise ValueError("notification failure status and error code must agree")
        return self
