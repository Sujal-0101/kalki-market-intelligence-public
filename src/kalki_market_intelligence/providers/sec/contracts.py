"""External and normalized contracts for the SEC public JSON APIs."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import (
    AliasChoices,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    model_validator,
)

from kalki_market_intelligence.contracts.common import (
    ContractModel,
    NonEmptyText,
    Sha256Hex,
    ShortText,
    UtcDatetime,
)
from kalki_market_intelligence.contracts.domain import TickerSymbol

type SecEndpoint = Literal["submissions", "companyfacts"]


def normalize_cik(value: object) -> object:
    """Represent every SEC Central Index Key as ten digits."""

    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        value = str(value)
    if isinstance(value, str) and value.isdigit() and 1 <= len(value) <= 10:
        return value.zfill(10)
    return value


type Cik = Annotated[
    str,
    BeforeValidator(normalize_cik),
    StringConstraints(pattern=r"^\d{10}$"),
]
type AccessionNumber = Annotated[
    str,
    StringConstraints(pattern=r"^\d{10}-\d{2}-\d{6}$"),
]
type SecDocumentName = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=255,
        pattern=r"^(?:[A-Za-z0-9][A-Za-z0-9._-]*/)?[A-Za-z0-9][A-Za-z0-9._-]*$",
    ),
]


class SecExternalModel(BaseModel):
    """Tolerant model for an SEC-owned schema that can add fields over time."""

    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)


class SecRecentFilings(SecExternalModel):
    """Parallel arrays in the submissions API's recent filing object."""

    accession_numbers: tuple[AccessionNumber, ...] = Field(alias="accessionNumber")
    filing_dates: tuple[date, ...] = Field(alias="filingDate")
    report_dates: tuple[str, ...] = Field(alias="reportDate")
    acceptance_datetimes: tuple[UtcDatetime, ...] = Field(alias="acceptanceDateTime")
    forms: tuple[ShortText, ...] = Field(alias="form")
    file_numbers: tuple[str, ...] = Field(alias="fileNumber")
    primary_documents: tuple[SecDocumentName, ...] = Field(alias="primaryDocument")
    primary_document_descriptions: tuple[str, ...] = Field(alias="primaryDocDescription")

    @model_validator(mode="after")
    def required_columns_have_equal_lengths(self) -> Self:
        """Reject column shifts rather than silently joining unrelated values."""

        lengths = {
            len(self.accession_numbers),
            len(self.filing_dates),
            len(self.report_dates),
            len(self.acceptance_datetimes),
            len(self.forms),
            len(self.file_numbers),
            len(self.primary_documents),
            len(self.primary_document_descriptions),
        }
        if len(lengths) != 1:
            raise ValueError("SEC recent filing columns must have equal lengths")
        return self


class SecHistoricalSubmissionFile(SecExternalModel):
    """Descriptor for older filing-history JSON referenced by submissions."""

    name: SecDocumentName
    filing_count: int = Field(alias="filingCount", ge=0)
    filing_from: date = Field(alias="filingFrom")
    filing_to: date = Field(alias="filingTo")


class SecExternalFilings(SecExternalModel):
    recent: SecRecentFilings
    files: tuple[SecHistoricalSubmissionFile, ...] = ()


class SecExternalSubmissions(SecExternalModel):
    """Supported subset of one filer response from `/submissions`."""

    cik: Cik
    name: ShortText
    sic: str = ""
    sic_description: str = Field(default="", alias="sicDescription")
    entity_type: str = Field(default="", alias="entityType")
    tickers: tuple[str, ...] = ()
    exchanges: tuple[str, ...] = ()
    filings: SecExternalFilings

    @model_validator(mode="after")
    def ticker_and_exchange_columns_align(self) -> Self:
        if len(self.tickers) != len(self.exchanges):
            raise ValueError("SEC ticker and exchange columns must have equal lengths")
        return self


class SecExternalFactUnit(SecExternalModel):
    """One reported XBRL fact context from companyfacts."""

    end: date
    value: Decimal = Field(validation_alias=AliasChoices("val", "value"))
    accession_number: AccessionNumber = Field(alias="accn")
    form: ShortText
    filed: date
    start: date | None = None
    fiscal_year: int | None = Field(default=None, alias="fy")
    fiscal_period: str | None = Field(default=None, alias="fp")
    frame: str | None = None


class SecExternalConcept(SecExternalModel):
    label: ShortText
    description: str = ""
    units: dict[str, tuple[SecExternalFactUnit, ...]]


class SecExternalCompanyFacts(SecExternalModel):
    """Supported subset of one filer response from `/companyfacts`."""

    cik: Cik
    entity_name: ShortText = Field(alias="entityName")
    facts: dict[str, dict[str, SecExternalConcept]]


class SecSecurityIdentifier(ContractModel):
    symbol: TickerSymbol
    exchange_name: ShortText | None


class SecIssuerRecord(ContractModel):
    """Provider-neutral-shaped issuer metadata sourced from SEC submissions."""

    record_id: Sha256Hex
    cik: Cik
    name: ShortText
    sic: str | None
    sic_description: str | None
    entity_type: str | None
    securities: tuple[SecSecurityIdentifier, ...]
    available_at: UtcDatetime
    retrieved_at: UtcDatetime
    source_content_sha256: Sha256Hex


class SecFilingRecord(ContractModel):
    """Normalized filing metadata; the filing document itself is not yet fetched."""

    record_id: Sha256Hex
    cik: Cik
    accession_number: AccessionNumber
    form: ShortText
    filing_date: date
    report_date: date | None
    accepted_at: UtcDatetime
    available_at: UtcDatetime
    retrieved_at: UtcDatetime
    file_number: str | None
    primary_document: SecDocumentName
    primary_document_description: str | None
    filing_url: HttpUrl
    source_content_sha256: Sha256Hex

    @model_validator(mode="after")
    def availability_is_conservative(self) -> Self:
        if self.available_at < self.accepted_at:
            raise ValueError("available_at must not precede SEC acceptance")
        if self.retrieved_at < self.available_at:
            raise ValueError("retrieved_at must not precede availability")
        return self


class SecFactRecord(ContractModel):
    """One normalized company fact with unit, context, and source lineage."""

    record_id: Sha256Hex
    cik: Cik
    entity_name: ShortText
    taxonomy: ShortText
    tag: ShortText
    label: ShortText
    description: NonEmptyText | None
    unit: ShortText
    value: Decimal
    period_start: date | None
    period_end: date
    filed_date: date
    accession_number: AccessionNumber
    form: ShortText
    fiscal_year: int | None
    fiscal_period: str | None
    frame: str | None
    available_at: UtcDatetime
    retrieved_at: UtcDatetime
    source_content_sha256: Sha256Hex


class SecRawArtifact(ContractModel):
    """Immutable metadata for one successful raw SEC response."""

    artifact_id: Sha256Hex
    endpoint: SecEndpoint
    cik: Cik
    url: HttpUrl
    status_code: Literal[200]
    media_type: ShortText
    byte_length: int = Field(ge=1)
    content_sha256: Sha256Hex
    retrieved_at: UtcDatetime
    etag: str | None = None
    last_modified: str | None = None


class StoredSecArtifact(SecRawArtifact):
    """Raw response plus repository-data-root-relative storage locations."""

    blob_path: NonEmptyText
    manifest_path: NonEmptyText


class SecIngestionBatch(ContractModel):
    """Complete normalized result for one issuer ingestion attempt."""

    cik: Cik
    issuer: SecIssuerRecord
    filings: tuple[SecFilingRecord, ...]
    facts: tuple[SecFactRecord, ...]
    artifacts: tuple[StoredSecArtifact, ...]
    logical_fingerprint: Sha256Hex
