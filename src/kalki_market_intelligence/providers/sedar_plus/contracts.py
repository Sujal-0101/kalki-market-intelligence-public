"""Rights-aware contracts for a future authorized SEDAR+ distribution feed."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BeforeValidator, Field, StringConstraints, model_validator

from kalki_market_intelligence.contracts.common import (
    ContractModel,
    NonEmptyText,
    Sha256Hex,
    ShortText,
    UtcDatetime,
)
from kalki_market_intelligence.contracts.domain import TickerSymbol


def normalize_upper(value: object) -> object:
    if isinstance(value, str):
        return value.strip().upper()
    return value


def validate_lei_checksum(value: str) -> str:
    """Apply the ISO 17442/ISO 7064 mod-97 checksum carried by an LEI."""

    numeric = "".join(str(int(character, 36)) for character in value)
    if int(numeric) % 97 != 1:
        raise ValueError("LEI checksum is invalid")
    return value


type CanadianProfileId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]
type Lei = Annotated[
    str,
    BeforeValidator(normalize_upper),
    StringConstraints(pattern=r"^[0-9A-Z]{20}$"),
    AfterValidator(validate_lei_checksum),
]


class CanadianJurisdiction(StrEnum):
    AB = "AB"
    BC = "BC"
    MB = "MB"
    NB = "NB"
    NL = "NL"
    NS = "NS"
    NT = "NT"
    NU = "NU"
    ON = "ON"
    PE = "PE"
    QC = "QC"
    SK = "SK"
    YT = "YT"


class AuthorizedAccessMode(StrEnum):
    """Official access paths that could permit automated local ingestion."""

    LICENSED_DISTRIBUTION = "licensed_distribution"
    APPROVED_AD_HOC = "approved_ad_hoc"


class IdentifierNamespace(StrEnum):
    SEDAR_PLUS_PROFILE = "sedar_plus_profile"
    LEI = "lei"


class DisclosureLanguage(StrEnum):
    ENGLISH = "en"
    FRENCH = "fr"
    BILINGUAL = "en-fr"
    OTHER = "other"


class AuthorizedRights(ContractModel):
    """Explicit grant recorded from a future agreement, never inferred."""

    agreement_reference: NonEmptyText
    automated_processing_allowed: bool
    database_storage_allowed: bool
    public_redistribution_allowed: bool
    expires_on: date | None = None


class LicensedListing(ContractModel):
    symbol: TickerSymbol
    exchange_name: ShortText


class LicensedIssuerProfile(ContractModel):
    provider_profile_id: CanadianProfileId
    legal_name: ShortText
    lei: Lei | None = None
    reporting_jurisdictions: tuple[CanadianJurisdiction, ...]
    listings: tuple[LicensedListing, ...]


class LicensedDisclosureEnvelope(ContractModel):
    """Source-neutral shape expected from a future licensed/approved feed."""

    schema_version: Literal["1"]
    access_mode: AuthorizedAccessMode
    rights: AuthorizedRights
    issuer: LicensedIssuerProfile
    provider_document_id: CanadianProfileId
    filing_category: ShortText
    document_type: ShortText
    title: ShortText
    filed_at: UtcDatetime
    became_public_at: UtcDatetime | None = None
    language: DisclosureLanguage
    media_type: ShortText
    byte_length: int = Field(ge=1)
    content_sha256: Sha256Hex
    source_record_sha256: Sha256Hex
    authorized_locator: NonEmptyText | None = None

    @model_validator(mode="after")
    def public_time_cannot_precede_filing(self) -> Self:
        if self.became_public_at is not None and self.became_public_at < self.filed_at:
            raise ValueError("became_public_at must not precede filed_at")
        return self


class CanadianIdentifier(ContractModel):
    namespace: IdentifierNamespace
    value: NonEmptyText


class CanadianIssuerMapping(ContractModel):
    """Mapping candidate that still requires explicit entity-resolution review."""

    record_id: Sha256Hex
    provider_profile_id: CanadianProfileId
    legal_name: ShortText
    country: Literal["CA"] = "CA"
    identifiers: tuple[CanadianIdentifier, ...]
    listings: tuple[LicensedListing, ...]
    reporting_jurisdictions: tuple[CanadianJurisdiction, ...]
    retrieved_at: UtcDatetime
    source_record_sha256: Sha256Hex


class CanadianDisclosureRecord(ContractModel):
    """Normalized disclosure metadata from explicitly authorized source material."""

    record_id: Sha256Hex
    issuer_record_id: Sha256Hex
    provider_document_id: CanadianProfileId
    provider_profile_id: CanadianProfileId
    filing_category: ShortText
    document_type: ShortText
    title: ShortText
    filed_at: UtcDatetime
    available_at: UtcDatetime
    retrieved_at: UtcDatetime
    language: DisclosureLanguage
    media_type: ShortText
    byte_length: int = Field(ge=1)
    content_sha256: Sha256Hex
    source_record_sha256: Sha256Hex
    access_mode: AuthorizedAccessMode
    agreement_reference: NonEmptyText
    public_redistribution_allowed: bool
    authorized_locator: NonEmptyText | None

    @model_validator(mode="after")
    def timestamps_follow_information_flow(self) -> Self:
        if self.available_at < self.filed_at:
            raise ValueError("available_at must not precede filed_at")
        if self.retrieved_at < self.available_at:
            raise ValueError("retrieved_at must not precede available_at")
        return self


class CanadianIngestionRecord(ContractModel):
    issuer: CanadianIssuerMapping
    disclosure: CanadianDisclosureRecord
