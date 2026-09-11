"""Deterministic parsing for SEC insider and beneficial-ownership XML filings."""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Protocol

from pydantic import Field, HttpUrl, StringConstraints, model_validator

from kalki_market_intelligence.contracts.common import (
    ContractModel,
    NonEmptyText,
    Sha256Hex,
    ShortText,
    UtcDatetime,
)
from kalki_market_intelligence.providers.sec.client import (
    SecFetchedDocument,
    SecFetchedPrimaryDocument,
)
from kalki_market_intelligence.providers.sec.contracts import (
    AccessionNumber,
    Cik,
    SecFilingRecord,
    normalize_cik,
)

MAXIMUM_OWNERSHIP_XML_BYTES = 2_000_000
type TransactionCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]$")]


class OwnershipParseError(ValueError):
    """A primary SEC ownership document cannot be parsed without guessing."""


class OwnershipIdentityMismatch(OwnershipParseError):
    """A duplicate SEC index identity is not the authoritative issuer row."""


class OwnershipForm(StrEnum):
    FORM_3 = "3"
    FORM_3_A = "3/A"
    FORM_4 = "4"
    FORM_4_A = "4/A"
    FORM_5 = "5"
    FORM_5_A = "5/A"
    FORM_144 = "144"
    FORM_144_A = "144/A"
    SCHEDULE_13D = "SCHEDULE 13D"
    SCHEDULE_13D_A = "SCHEDULE 13D/A"
    SCHEDULE_13G = "SCHEDULE 13G"
    SCHEDULE_13G_A = "SCHEDULE 13G/A"

    @property
    def is_schedule_13d(self) -> bool:
        return self in {self.SCHEDULE_13D, self.SCHEDULE_13D_A}

    @property
    def is_schedule_13g(self) -> bool:
        return self in {self.SCHEDULE_13G, self.SCHEDULE_13G_A}


class OwnershipDiscoveryCandidate(ContractModel):
    """One bounded daily-index row awaiting exact primary-document acquisition."""

    accession_number: AccessionNumber
    index_ciks: tuple[Cik, ...] = Field(min_length=1, max_length=16)
    index_names: tuple[ShortText, ...] = Field(min_length=1, max_length=16)
    form: OwnershipForm
    filed_on: date
    discovered_at: UtcDatetime
    source_index_url: HttpUrl
    source_index_sha256: Sha256Hex

    @model_validator(mode="after")
    def discovery_cannot_precede_filing(self) -> OwnershipDiscoveryCandidate:
        if self.discovered_at.date() < self.filed_on:
            raise ValueError("ownership discovery cannot precede filing date")
        if len(self.index_ciks) != len(self.index_names):
            raise ValueError("ownership index CIK and name rows must remain paired")
        if self.index_ciks != tuple(sorted(set(self.index_ciks))):
            raise ValueError("ownership index CIK rows must be sorted and unique")
        return self


class OwnershipNature(StrEnum):
    DIRECT = "DIRECT"
    INDIRECT = "INDIRECT"
    UNKNOWN = "UNKNOWN"


class OwnershipPercentageStatus(StrEnum):
    REPORTED = "REPORTED"
    CALCULATED = "CALCULATED"
    UNKNOWN = "UNKNOWN"


class ActivistControlIntentStatus(StrEnum):
    DISCLOSED_TEXT_REQUIRES_REVIEW = "DISCLOSED_TEXT_REQUIRES_REVIEW"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ScheduleTransition(StrEnum):
    INITIAL_13D = "INITIAL_13D"
    INITIAL_13G = "INITIAL_13G"
    AMENDED_13D = "AMENDED_13D"
    AMENDED_13G = "AMENDED_13G"
    THIRTEEN_G_TO_THIRTEEN_D = "13G_TO_13D"
    THIRTEEN_D_TO_THIRTEEN_G = "13D_TO_13G"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ReportingRelationship(ContractModel):
    is_director: bool | None = None
    is_officer: bool | None = None
    is_ten_percent_owner: bool | None = None
    is_other: bool | None = None
    officer_title: ShortText | None = None
    other_text: ShortText | None = None


class ReportingOwner(ContractModel):
    cik: Cik | None
    name: ShortText
    relationship: ReportingRelationship | None = None


class InsiderTransaction(ContractModel):
    security_title: ShortText
    transaction_date: date
    transaction_code: TransactionCode
    shares: Decimal = Field(ge=0)
    price_per_share: Decimal | None = Field(default=None, ge=0)
    acquired_or_disposed: Annotated[str, StringConstraints(pattern=r"^[AD]$")]
    shares_owned_after: Decimal | None = Field(default=None, ge=0)
    post_transaction_percent_of_class: Decimal | None = Field(default=None, ge=0, le=100)
    post_transaction_percent_status: OwnershipPercentageStatus = OwnershipPercentageStatus.UNKNOWN
    ownership_nature: OwnershipNature
    derivative: bool
    late_reported: bool | None = None

    @model_validator(mode="after")
    def percentage_value_matches_status(self) -> InsiderTransaction:
        reported = self.post_transaction_percent_of_class is not None
        known = self.post_transaction_percent_status is not OwnershipPercentageStatus.UNKNOWN
        if reported != known:
            raise ValueError("post-transaction percentage status must match its value")
        return self


class InsiderHolding(ContractModel):
    security_title: ShortText
    shares_owned: Decimal = Field(ge=0)
    ownership_nature: OwnershipNature
    derivative: bool


class Form144Notice(ContractModel):
    seller_name: ShortText
    relationship_to_issuer: tuple[ShortText, ...]
    security_title: ShortText
    units_to_be_sold: Decimal = Field(ge=0)
    aggregate_market_value: Decimal | None = Field(default=None, ge=0)
    units_outstanding: Decimal | None = Field(default=None, ge=0)
    approximate_sale_date: date
    exchange_name: ShortText | None = None


class BeneficialOwner(ContractModel):
    cik: Cik | None
    name: ShortText
    aggregate_shares_owned: Decimal = Field(ge=0)
    percent_of_class: Decimal | None = Field(default=None, ge=0, le=100)
    sole_voting_power: Decimal | None = Field(default=None, ge=0)
    shared_voting_power: Decimal | None = Field(default=None, ge=0)
    sole_dispositive_power: Decimal | None = Field(default=None, ge=0)
    shared_dispositive_power: Decimal | None = Field(default=None, ge=0)
    reporting_person_types: tuple[ShortText, ...] = ()


class OwnershipFilingReceipt(ContractModel):
    accession_number: AccessionNumber
    form: OwnershipForm
    issuer_cik: Cik
    issuer_name: ShortText
    issuer_trading_symbol: ShortText | None = None
    period_or_event_date: date
    reporting_owners: tuple[ReportingOwner, ...] = ()
    insider_transactions: tuple[InsiderTransaction, ...] = ()
    insider_holdings: tuple[InsiderHolding, ...] = ()
    form_144_notice: Form144Notice | None = None
    beneficial_owners: tuple[BeneficialOwner, ...] = ()
    amendment_number: int | None = Field(default=None, ge=1)
    previous_accession_number: AccessionNumber | None = None
    disclosed_transaction_purpose: NonEmptyText | None = None
    activist_control_intent_status: ActivistControlIntentStatus
    source_url: HttpUrl
    source_content_sha256: Sha256Hex
    accepted_at: UtcDatetime
    retrieved_at: UtcDatetime
    parser_version: str = "sec-ownership-v1"

    @model_validator(mode="after")
    def form_specific_content_is_consistent(self) -> OwnershipFilingReceipt:
        if self.retrieved_at < self.accepted_at:
            raise ValueError("retrieval cannot precede SEC acceptance")
        if self.form in {OwnershipForm.FORM_144, OwnershipForm.FORM_144_A}:
            if self.form_144_notice is None:
                raise ValueError("Form 144 requires a sale notice")
            if (
                self.activist_control_intent_status
                is not ActivistControlIntentStatus.NOT_APPLICABLE
            ):
                raise ValueError("Form 144 has no Schedule 13D control-intent assessment")
        elif self.form.is_schedule_13d or self.form.is_schedule_13g:
            if not self.beneficial_owners:
                raise ValueError("Schedule 13D/G requires beneficial-owner rows")
            expected = (
                ActivistControlIntentStatus.DISCLOSED_TEXT_REQUIRES_REVIEW
                if self.form.is_schedule_13d and self.disclosed_transaction_purpose is not None
                else ActivistControlIntentStatus.UNKNOWN
                if self.form.is_schedule_13d
                else ActivistControlIntentStatus.NOT_APPLICABLE
            )
            if self.activist_control_intent_status is not expected:
                raise ValueError("control-intent status must match primary Schedule content")
        elif self.form_144_notice is not None or self.beneficial_owners:
            raise ValueError("Section 16 forms cannot contain Schedule/144 rows")
        elif self.activist_control_intent_status is not ActivistControlIntentStatus.NOT_APPLICABLE:
            raise ValueError("Section 16 forms have no Schedule 13D control-intent assessment")
        return self


@dataclass(frozen=True)
class _SourceContext:
    accession_number: str
    source_url: HttpUrl
    source_content_sha256: str
    accepted_at: datetime
    retrieved_at: datetime


class OwnershipDocumentClient(Protocol):
    def fetch_primary_document(
        self,
        *,
        cik: str | int,
        accession_number: str,
        document_name: str,
    ) -> SecFetchedPrimaryDocument: ...


class SecOwnershipIngestionService:
    """Fetch and parse one ownership filing from validated SEC metadata."""

    def __init__(self, client: OwnershipDocumentClient) -> None:
        self._client = client

    def ingest(self, filing: SecFilingRecord) -> OwnershipFilingReceipt:
        metadata_form = normalize_ownership_form(filing.form)
        document = self._client.fetch_primary_document(
            cik=filing.cik,
            accession_number=filing.accession_number,
            document_name=filing.primary_document,
        )
        if document.url != str(filing.filing_url):
            raise OwnershipIdentityMismatch("fetched ownership URL does not match filing metadata")
        receipt = parse_ownership_xml(
            document.body,
            accession_number=filing.accession_number,
            source_url=document.url,
            accepted_at=filing.accepted_at,
            retrieved_at=document.retrieved_at,
        )
        if receipt.form is not metadata_form:
            raise OwnershipParseError("ownership document form does not match filing metadata")
        if receipt.issuer_cik != filing.cik:
            raise OwnershipIdentityMismatch(
                "ownership document issuer does not match filing metadata"
            )
        if receipt.source_content_sha256 != document.content_sha256:
            raise OwnershipParseError("ownership document hash changed during parsing")
        return receipt


def parse_ownership_xml(
    body: bytes,
    *,
    accession_number: str,
    source_url: str,
    accepted_at: datetime,
    retrieved_at: datetime,
) -> OwnershipFilingReceipt:
    """Parse one SEC primary XML document under bounded, fail-closed rules."""

    if not body or len(body) > MAXIMUM_OWNERSHIP_XML_BYTES:
        raise OwnershipParseError("ownership XML is empty or exceeds the size boundary")
    upper = body.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise OwnershipParseError("ownership XML declarations are not permitted")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as error:
        raise OwnershipParseError("ownership document is not well-formed XML") from error
    _strip_namespaces(root)
    form = _form(root)
    source = _SourceContext(
        accession_number=accession_number,
        source_url=HttpUrl(source_url),
        source_content_sha256=hashlib.sha256(body).hexdigest(),
        accepted_at=accepted_at,
        retrieved_at=retrieved_at,
    )
    try:
        if form in {
            OwnershipForm.FORM_3,
            OwnershipForm.FORM_3_A,
            OwnershipForm.FORM_4,
            OwnershipForm.FORM_4_A,
            OwnershipForm.FORM_5,
            OwnershipForm.FORM_5_A,
        }:
            return _parse_section_16(root, form=form, source=source)
        if form in {OwnershipForm.FORM_144, OwnershipForm.FORM_144_A}:
            return _parse_form_144(root, form=form, source=source)
        return _parse_schedule(root, form=form, source=source)
    except (ValueError, TypeError) as error:
        if isinstance(error, OwnershipParseError):
            raise
        raise OwnershipParseError(f"ownership XML violates the closed contract: {error}") from error


def classify_schedule_transition(
    previous: OwnershipForm | None, current: OwnershipForm
) -> ScheduleTransition:
    """Classify a 13D/13G transition without inferring intent from identity."""

    if not (current.is_schedule_13d or current.is_schedule_13g):
        return ScheduleTransition.NOT_APPLICABLE
    if previous is None:
        return (
            ScheduleTransition.INITIAL_13D
            if current.is_schedule_13d
            else ScheduleTransition.INITIAL_13G
        )
    if previous.is_schedule_13g and current.is_schedule_13d:
        return ScheduleTransition.THIRTEEN_G_TO_THIRTEEN_D
    if previous.is_schedule_13d and current.is_schedule_13g:
        return ScheduleTransition.THIRTEEN_D_TO_THIRTEEN_G
    return (
        ScheduleTransition.AMENDED_13D
        if current.is_schedule_13d
        else ScheduleTransition.AMENDED_13G
    )


def normalize_ownership_form(value: str) -> OwnershipForm:
    """Normalize only the SEC's closed ownership-form names."""

    normalized = value.strip().upper().replace("SC 13", "SCHEDULE 13")
    try:
        return OwnershipForm(normalized)
    except ValueError as error:
        raise OwnershipParseError(f"unsupported ownership form metadata: {normalized}") from error


def ownership_filing_from_submissions(
    document: SecFetchedDocument,
    *,
    accession_number: str,
) -> SecFilingRecord | None:
    """Validate only one ownership row without trusting unrelated document names.

    SEC submissions may retain older primary-document paths that are outside the
    current normalized filing contract. Required parallel-array alignment still
    fails closed, but an unrelated historical filename cannot hide the requested
    current ownership accession.
    """

    try:
        payload: object = json.loads(document.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OwnershipParseError("SEC submissions metadata is not valid JSON") from error
    if not isinstance(payload, Mapping):
        raise OwnershipParseError("SEC submissions metadata is not an object")
    normalized_cik = normalize_cik(payload.get("cik"))
    if normalized_cik != document.cik or not isinstance(normalized_cik, str):
        raise OwnershipParseError("SEC submissions CIK does not match its retrieval identity")
    filings = payload.get("filings")
    recent = filings.get("recent") if isinstance(filings, Mapping) else None
    if not isinstance(recent, Mapping):
        raise OwnershipParseError("SEC submissions recent filing metadata is unavailable")
    columns = (
        "accessionNumber",
        "filingDate",
        "reportDate",
        "acceptanceDateTime",
        "form",
        "fileNumber",
        "primaryDocument",
        "primaryDocDescription",
    )
    values = {key: recent.get(key) for key in columns}
    if any(not isinstance(value, list) for value in values.values()):
        raise OwnershipParseError("SEC submissions filing columns are malformed")
    lengths = {len(value) for value in values.values() if isinstance(value, list)}
    if len(lengths) != 1:
        raise OwnershipParseError("SEC submissions filing columns are misaligned")
    accession_values = values["accessionNumber"]
    assert isinstance(accession_values, list)
    matches = [index for index, value in enumerate(accession_values) if value == accession_number]
    if not matches:
        return None
    if len(matches) != 1:
        raise OwnershipParseError("SEC submissions repeats the requested accession")
    index = matches[0]

    def selected(key: str) -> object:
        column = values[key]
        assert isinstance(column, list)
        return column[index]

    primary_document = selected("primaryDocument")
    filing_date = selected("filingDate")
    report_date = selected("reportDate")
    accepted_at = selected("acceptanceDateTime")
    form = selected("form")
    file_number = selected("fileNumber")
    description = selected("primaryDocDescription")
    if (
        not isinstance(primary_document, str)
        or not isinstance(filing_date, str)
        or not isinstance(report_date, str)
        or not isinstance(accepted_at, str)
        or not isinstance(form, str)
        or not isinstance(file_number, str)
        or not isinstance(description, str)
    ):
        raise OwnershipParseError("requested SEC ownership metadata has invalid primitives")
    raw_primary_document = primary_document
    if re.fullmatch(r"xslF[A-Za-z0-9]+/[A-Za-z0-9][A-Za-z0-9._-]*", primary_document):
        # SEC submissions identifies ownership renderings through a one-level
        # XSL route while the accession directory retains the authoritative raw
        # XML under the same basename. No other path form is rewritten.
        raw_primary_document = primary_document.rsplit("/", maxsplit=1)[1]
    record_id = hashlib.sha256(f"sec:ownership-filing:{accession_number}".encode()).hexdigest()
    try:
        return SecFilingRecord.model_validate(
            {
                "record_id": record_id,
                "cik": normalized_cik,
                "accession_number": accession_number,
                "form": form,
                "filing_date": filing_date,
                "report_date": report_date or None,
                "accepted_at": accepted_at,
                "available_at": document.retrieved_at,
                "retrieved_at": document.retrieved_at,
                "file_number": file_number.strip() or None,
                "primary_document": raw_primary_document,
                "primary_document_description": description.strip() or None,
                "filing_url": (
                    "https://www.sec.gov/Archives/edgar/data/"
                    f"{int(normalized_cik)}/{accession_number.replace('-', '')}/"
                    f"{raw_primary_document}"
                ),
                "source_content_sha256": document.content_sha256,
            }
        )
    except ValueError as error:
        raise OwnershipParseError(
            "requested SEC ownership metadata violates the closed filing contract"
        ) from error


def _parse_section_16(
    root: ET.Element, *, form: OwnershipForm, source: _SourceContext
) -> OwnershipFilingReceipt:
    issuer = _required(root, "issuer")
    owners = tuple(
        ReportingOwner(
            cik=_optional_text(owner, "reportingOwnerId/rptOwnerCik"),
            name=_required_text(owner, "reportingOwnerId/rptOwnerName"),
            relationship=_relationship(owner.find("reportingOwnerRelationship")),
        )
        for owner in root.findall("reportingOwner")
    )
    transactions: list[InsiderTransaction] = []
    holdings: list[InsiderHolding] = []
    for derivative, path in (
        (False, "nonDerivativeTable/nonDerivativeTransaction"),
        (True, "derivativeTable/derivativeTransaction"),
    ):
        for row in root.findall(path):
            transactions.append(
                InsiderTransaction(
                    security_title=_required_text(row, "securityTitle/value"),
                    transaction_date=_iso_date(_required_text(row, "transactionDate/value")),
                    transaction_code=_required_text(row, "transactionCoding/transactionCode"),
                    shares=_decimal(
                        _required_text(row, "transactionAmounts/transactionShares/value")
                    ),
                    price_per_share=_optional_decimal(
                        row, "transactionAmounts/transactionPricePerShare/value"
                    ),
                    acquired_or_disposed=_required_text(
                        row, "transactionAmounts/transactionAcquiredDisposedCode/value"
                    ),
                    shares_owned_after=_optional_decimal(
                        row, "postTransactionAmounts/sharesOwnedFollowingTransaction/value"
                    ),
                    ownership_nature=_ownership_nature(
                        _optional_text(row, "ownershipNature/directOrIndirectOwnership/value")
                    ),
                    derivative=derivative,
                    late_reported=_late_flag(_optional_text(row, "transactionTimeliness/value")),
                )
            )
    for derivative, path in (
        (False, "nonDerivativeTable/nonDerivativeHolding"),
        (True, "derivativeTable/derivativeHolding"),
    ):
        for row in root.findall(path):
            holdings.append(
                InsiderHolding(
                    security_title=_required_text(row, "securityTitle/value"),
                    shares_owned=_decimal(
                        _required_text(
                            row, "postTransactionAmounts/sharesOwnedFollowingTransaction/value"
                        )
                    ),
                    ownership_nature=_ownership_nature(
                        _optional_text(row, "ownershipNature/directOrIndirectOwnership/value")
                    ),
                    derivative=derivative,
                )
            )
    return OwnershipFilingReceipt(
        form=form,
        issuer_cik=_required_text(issuer, "issuerCik"),
        issuer_name=_required_text(issuer, "issuerName"),
        issuer_trading_symbol=_optional_text(issuer, "issuerTradingSymbol"),
        period_or_event_date=_iso_date(_required_text(root, "periodOfReport")),
        reporting_owners=owners,
        insider_transactions=tuple(transactions),
        insider_holdings=tuple(holdings),
        activist_control_intent_status=ActivistControlIntentStatus.NOT_APPLICABLE,
        accession_number=source.accession_number,
        source_url=source.source_url,
        source_content_sha256=source.source_content_sha256,
        accepted_at=source.accepted_at,
        retrieved_at=source.retrieved_at,
    )


def _parse_form_144(
    root: ET.Element, *, form: OwnershipForm, source: _SourceContext
) -> OwnershipFilingReceipt:
    data = _required(root, "formData")
    issuer = _required(data, "issuerInfo")
    security = _required(data, "securitiesInformation")
    sale_date = _us_date(_required_text(security, "approxSaleDate"))
    notice = Form144Notice(
        seller_name=_required_text(issuer, "nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold"),
        relationship_to_issuer=tuple(
            text
            for node in issuer.findall("relationshipsToIssuer/relationshipToIssuer")
            if (text := _clean(node.text)) is not None
        ),
        security_title=_required_text(security, "securitiesClassTitle"),
        units_to_be_sold=_decimal(_required_text(security, "noOfUnitsSold")),
        aggregate_market_value=_optional_decimal(security, "aggregateMarketValue"),
        units_outstanding=_optional_decimal(security, "noOfUnitsOutstanding"),
        approximate_sale_date=sale_date,
        exchange_name=_optional_text(security, "securitiesExchangeName"),
    )
    return OwnershipFilingReceipt(
        form=form,
        issuer_cik=_required_text(issuer, "issuerCik"),
        issuer_name=_required_text(issuer, "issuerName"),
        period_or_event_date=sale_date,
        form_144_notice=notice,
        activist_control_intent_status=ActivistControlIntentStatus.NOT_APPLICABLE,
        accession_number=source.accession_number,
        source_url=source.source_url,
        source_content_sha256=source.source_content_sha256,
        accepted_at=source.accepted_at,
        retrieved_at=source.retrieved_at,
    )


def _parse_schedule(
    root: ET.Element, *, form: OwnershipForm, source: _SourceContext
) -> OwnershipFilingReceipt:
    data = _required(root, "formData")
    header = _required(data, "coverPageHeader")
    issuer = _required(header, "issuerInfo")
    owner_nodes = (
        data.findall("reportingPersons/reportingPersonInfo")
        if form.is_schedule_13d
        else data.findall("coverPageHeaderReportingPersonDetails")
    )
    owners = tuple(
        _beneficial_owner(node, schedule_13d=form.is_schedule_13d) for node in owner_nodes
    )
    event_text = _optional_text(header, "dateOfEvent") or _required_text(
        header, "eventDateRequiresFilingThisStatement"
    )
    purpose = _optional_text(data, "items1To7/item4/transactionPurpose")
    return OwnershipFilingReceipt(
        form=form,
        issuer_cik=_required_text(issuer, "issuerCIK")
        if form.is_schedule_13d
        else _required_text(issuer, "issuerCik"),
        issuer_name=_required_text(issuer, "issuerName"),
        period_or_event_date=_us_date(event_text),
        beneficial_owners=owners,
        amendment_number=_optional_int(header, "amendmentNo"),
        previous_accession_number=_optional_text(root, "headerData/previousAccessionNumber"),
        disclosed_transaction_purpose=purpose,
        activist_control_intent_status=(
            ActivistControlIntentStatus.DISCLOSED_TEXT_REQUIRES_REVIEW
            if form.is_schedule_13d and purpose is not None
            else ActivistControlIntentStatus.UNKNOWN
            if form.is_schedule_13d
            else ActivistControlIntentStatus.NOT_APPLICABLE
        ),
        accession_number=source.accession_number,
        source_url=source.source_url,
        source_content_sha256=source.source_content_sha256,
        accepted_at=source.accepted_at,
        retrieved_at=source.retrieved_at,
    )


def _beneficial_owner(node: ET.Element, *, schedule_13d: bool) -> BeneficialOwner:
    prefix = "" if schedule_13d else "reportingPersonBeneficiallyOwnedNumberOfShares/"
    return BeneficialOwner(
        cik=_optional_text(node, "reportingPersonCIK"),
        name=_required_text(node, "reportingPersonName"),
        aggregate_shares_owned=_decimal(
            _required_text(
                node,
                "aggregateAmountOwned"
                if schedule_13d
                else "reportingPersonBeneficiallyOwnedAggregateNumberOfShares",
            )
        ),
        percent_of_class=_optional_decimal(
            node, "percentOfClass" if schedule_13d else "classPercent"
        ),
        sole_voting_power=_optional_decimal(node, f"{prefix}soleVotingPower"),
        shared_voting_power=_optional_decimal(node, f"{prefix}sharedVotingPower"),
        sole_dispositive_power=_optional_decimal(node, f"{prefix}soleDispositivePower"),
        shared_dispositive_power=_optional_decimal(node, f"{prefix}sharedDispositivePower"),
        reporting_person_types=tuple(
            text
            for item in node.findall("typeOfReportingPerson")
            if (text := _clean(item.text)) is not None
        ),
    )


def _form(root: ET.Element) -> OwnershipForm:
    raw = _optional_text(root, "documentType") or _required_text(root, "headerData/submissionType")
    normalized = raw.strip().upper().replace("SC 13", "SCHEDULE 13")
    try:
        return OwnershipForm(normalized)
    except ValueError as error:
        raise OwnershipParseError(f"unsupported ownership form: {normalized}") from error


def _relationship(node: ET.Element | None) -> ReportingRelationship | None:
    if node is None:
        return None
    return ReportingRelationship(
        is_director=_optional_bool(node, "isDirector"),
        is_officer=_optional_bool(node, "isOfficer"),
        is_ten_percent_owner=_optional_bool(node, "isTenPercentOwner"),
        is_other=_optional_bool(node, "isOther"),
        officer_title=_optional_text(node, "officerTitle"),
        other_text=_optional_text(node, "otherText"),
    )


def _strip_namespaces(root: ET.Element) -> None:
    for node in root.iter():
        node.tag = node.tag.rsplit("}", 1)[-1]


def _required(node: ET.Element, path: str) -> ET.Element:
    found = node.find(path)
    if found is None:
        raise OwnershipParseError(f"missing required ownership path: {path}")
    return found


def _required_text(node: ET.Element, path: str) -> str:
    value = _optional_text(node, path)
    if value is None:
        raise OwnershipParseError(f"missing required ownership value: {path}")
    return value


def _optional_text(node: ET.Element, path: str) -> str | None:
    found = node.find(path)
    return None if found is None else _clean(found.text)


def _clean(value: str | None) -> str | None:
    normalized = " ".join((value or "").split())
    return normalized or None


def _decimal(value: str) -> Decimal:
    try:
        return Decimal(value.replace(",", ""))
    except InvalidOperation as error:
        raise OwnershipParseError("ownership numeric value is invalid") from error


def _optional_decimal(node: ET.Element, path: str) -> Decimal | None:
    value = _optional_text(node, path)
    return None if value is None else _decimal(value)


def _optional_int(node: ET.Element, path: str) -> int | None:
    value = _optional_text(node, path)
    return None if value is None else int(value)


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise OwnershipParseError("ownership date is not ISO formatted") from error


def _us_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%m/%d/%Y").date()
    except ValueError as error:
        raise OwnershipParseError("ownership date is not MM/DD/YYYY") from error


def _optional_bool(node: ET.Element, path: str) -> bool | None:
    value = _optional_text(node, path)
    if value is None:
        return None
    if value.casefold() in {"1", "true", "y", "yes"}:
        return True
    if value.casefold() in {"0", "false", "n", "no"}:
        return False
    raise OwnershipParseError(f"ownership boolean is invalid: {path}")


def _ownership_nature(value: str | None) -> OwnershipNature:
    if value == "D":
        return OwnershipNature.DIRECT
    if value == "I":
        return OwnershipNature.INDIRECT
    return OwnershipNature.UNKNOWN


def _late_flag(value: str | None) -> bool | None:
    if value is None:
        return None
    return value == "L"
