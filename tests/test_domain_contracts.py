"""Tests for initial issuer and security contracts."""

from datetime import date
from uuid import UUID

import pytest
from pydantic import ValidationError

from kalki_market_intelligence.contracts.domain import (
    CountryCode,
    CurrencyCode,
    Issuer,
    Security,
)

ISSUER_ID = UUID("00000000-0000-4000-8000-000000000001")
SECURITY_ID = UUID("00000000-0000-4000-8000-000000000002")


def test_issuer_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        Issuer(
            issuer_id=ISSUER_ID,
            legal_name="Example Corp.",
            country=CountryCode.CANADA,
            invented_metric=42,  # type: ignore[call-arg]
        )


def test_security_normalizes_market_identifiers() -> None:
    security = Security(
        security_id=SECURITY_ID,
        issuer_id=ISSUER_ID,
        symbol=" shop ",
        exchange=" tsx ",
        currency=CurrencyCode.CANADIAN_DOLLAR,
        active_from=date(2015, 5, 21),
    )

    assert security.symbol == "SHOP"
    assert security.exchange == "TSX"


def test_security_rejects_invalid_symbol() -> None:
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        Security(
            security_id=SECURITY_ID,
            issuer_id=ISSUER_ID,
            symbol="NOT A SYMBOL",
            exchange="NASDAQ",
            currency=CurrencyCode.US_DOLLAR,
            active_from=date(2020, 1, 1),
        )


def test_security_rejects_reversed_active_period() -> None:
    with pytest.raises(ValidationError, match="active_to"):
        Security(
            security_id=SECURITY_ID,
            issuer_id=ISSUER_ID,
            symbol="TEST",
            exchange="NYSE",
            currency=CurrencyCode.US_DOLLAR,
            active_from=date(2024, 2, 1),
            active_to=date(2024, 1, 31),
        )


def test_contracts_are_immutable() -> None:
    issuer = Issuer(
        issuer_id=ISSUER_ID,
        legal_name="Example Corp.",
        country=CountryCode.UNITED_STATES,
    )

    with pytest.raises(ValidationError, match="frozen_instance"):
        issuer.legal_name = "Changed Corp."  # type: ignore[misc]


def test_domain_contract_exports_closed_json_schema() -> None:
    schema = Security.model_json_schema()

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "active_from",
        "currency",
        "exchange",
        "issuer_id",
        "security_id",
        "symbol",
    }
