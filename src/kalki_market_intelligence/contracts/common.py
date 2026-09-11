"""Primitive types and validation shared by all contracts."""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints


def normalize_utc(value: datetime) -> datetime:
    """Require a timezone-aware datetime and normalize it to UTC."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone offset")
    return value.astimezone(UTC)


type UtcDatetime = Annotated[datetime, AfterValidator(normalize_utc)]
type NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=10_000),
]
type ShortText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
type Sha256Hex = Annotated[
    str,
    StringConstraints(to_lower=True, pattern=r"^[0-9a-f]{64}$"),
]


class ContractModel(BaseModel):
    """Safe defaults for immutable boundary contracts."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_assignment=True,
    )
