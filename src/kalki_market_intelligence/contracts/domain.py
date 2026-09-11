"""Initial issuer and security domain contracts."""

from datetime import date
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BeforeValidator, StringConstraints, model_validator

from kalki_market_intelligence.contracts.common import ContractModel, ShortText


class CountryCode(StrEnum):
    """Initial supported issuer countries."""

    UNITED_STATES = "US"
    CANADA = "CA"


class CurrencyCode(StrEnum):
    """Initial supported quote and reporting currencies."""

    US_DOLLAR = "USD"
    CANADIAN_DOLLAR = "CAD"


class SecurityType(StrEnum):
    """Initial equity security types."""

    COMMON_STOCK = "common_stock"
    PREFERRED_STOCK = "preferred_stock"


def normalize_market_code(value: object) -> object:
    """Normalize string identifiers before their patterns are evaluated."""

    if isinstance(value, str):
        return value.strip().upper()
    return value


type TickerSymbol = Annotated[
    str,
    BeforeValidator(normalize_market_code),
    StringConstraints(
        min_length=1,
        max_length=15,
        pattern=r"^[A-Z0-9][A-Z0-9.-]*$",
    ),
]
type ExchangeCode = Annotated[
    str,
    BeforeValidator(normalize_market_code),
    StringConstraints(
        min_length=2,
        max_length=12,
        pattern=r"^[A-Z0-9.-]+$",
    ),
]


class Issuer(ContractModel):
    """A legal company entity independent of any particular listing."""

    issuer_id: UUID
    legal_name: ShortText
    country: CountryCode


class Security(ContractModel):
    """A listed equity associated with an issuer."""

    security_id: UUID
    issuer_id: UUID
    symbol: TickerSymbol
    exchange: ExchangeCode
    currency: CurrencyCode
    security_type: SecurityType = SecurityType.COMMON_STOCK
    active_from: date
    active_to: date | None = None

    @model_validator(mode="after")
    def active_period_must_be_ordered(self) -> Self:
        """Prevent an inactive date from preceding the listing date."""

        if self.active_to is not None and self.active_to < self.active_from:
            raise ValueError("active_to must be on or after active_from")
        return self
