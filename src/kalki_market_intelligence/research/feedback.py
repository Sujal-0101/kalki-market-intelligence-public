"""Append-only, bounded human feedback contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import Field, StringConstraints, field_validator

from kalki_market_intelligence.contracts.common import ContractModel

type Snowflake = Annotated[
    str, StringConstraints(min_length=17, max_length=20, pattern=r"^[0-9]+$")
]


class FeedbackType(StrEnum):
    USEFUL = "useful"
    NOT_USEFUL = "not_useful"
    FALSE_POSITIVE = "false_positive"
    MISSED_EVIDENCE = "missed_evidence"
    INCORRECT_FACT = "incorrect_fact"
    TOO_LATE = "too_late"
    OTHER = "other"


class HumanResearchFeedback(ContractModel):
    """An observation about immutable research, never a mutation command."""

    feedback_id: UUID = Field(default_factory=uuid4)
    research_reference: str = Field(min_length=1, max_length=120)
    submitter_user_id: Snowflake
    submitted_at: datetime
    feedback_type: FeedbackType
    note: str | None = Field(default=None, max_length=1_000)
    version: str = Field(default="feedback-v1", min_length=1, max_length=40)

    @field_validator("submitted_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("submitted_at must include a UTC offset")
        return value.astimezone(UTC)

    @field_validator("research_reference", "note")
    @classmethod
    def trim_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None
