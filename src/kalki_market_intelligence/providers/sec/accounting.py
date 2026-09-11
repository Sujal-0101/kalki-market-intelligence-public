"""Exact SEC acquisition for bounded accounting and compliance intelligence."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from datetime import date
from typing import Protocol

from pydantic import Field, HttpUrl, model_validator

from kalki_market_intelligence.contracts.common import (
    ContractModel,
    Sha256Hex,
    ShortText,
    UtcDatetime,
)
from kalki_market_intelligence.forensics.accounting import (
    AccountingFilingReceipt,
    AccountingForm,
    AccountingParseError,
    build_accounting_filing_receipt,
    normalize_accounting_form,
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


class AccountingIdentityMismatch(AccountingParseError):
    """The selected SEC index identity does not own the primary filing."""


class AccountingNoSupportedEvents(AccountingParseError):
    """The filing is valid but contains no exact Phase 41 event."""


class AccountingDiscoveryCandidate(ContractModel):
    accession_number: AccessionNumber
    index_ciks: tuple[Cik, ...] = Field(min_length=1, max_length=16)
    index_names: tuple[ShortText, ...] = Field(min_length=1, max_length=16)
    form: AccountingForm
    filed_on: date
    discovered_at: UtcDatetime
    source_index_url: HttpUrl
    source_index_sha256: Sha256Hex

    @model_validator(mode="after")
    def discovery_is_consistent(self) -> AccountingDiscoveryCandidate:
        if len(self.index_ciks) != len(self.index_names):
            raise ValueError("accounting index CIK and name rows must remain paired")
        if self.index_ciks != tuple(sorted(set(self.index_ciks))):
            raise ValueError("accounting index CIK rows must be sorted and unique")
        if self.discovered_at.date() < self.filed_on:
            raise ValueError("accounting discovery cannot precede filing date")
        return self


class AccountingFilingMetadata(ContractModel):
    issuer_name: ShortText
    filing: SecFilingRecord


class AccountingDocumentClient(Protocol):
    def fetch_primary_html_document(
        self,
        *,
        cik: str | int,
        accession_number: str,
        document_name: str,
    ) -> SecFetchedPrimaryDocument: ...


class SecAccountingIngestionService:
    def __init__(self, client: AccountingDocumentClient) -> None:
        self._client = client

    def ingest(
        self,
        metadata: AccountingFilingMetadata,
        *,
        prior_receipts: tuple[AccountingFilingReceipt, ...],
        prior_search_complete: bool,
        primary_document_observer: (
            Callable[[SecFilingRecord, SecFetchedPrimaryDocument], None] | None
        ) = None,
    ) -> AccountingFilingReceipt:
        filing = metadata.filing
        form = normalize_accounting_form(filing.form)
        document = self._client.fetch_primary_html_document(
            cik=filing.cik,
            accession_number=filing.accession_number,
            document_name=filing.primary_document,
        )
        if document.url != str(filing.filing_url):
            raise AccountingIdentityMismatch("fetched accounting URL does not match metadata")
        if document.content_sha256 != hashlib.sha256(document.body).hexdigest():
            raise AccountingParseError("accounting document hash changed during acquisition")
        if primary_document_observer is not None:
            primary_document_observer(filing, document)
        receipt = build_accounting_filing_receipt(
            accession_number=filing.accession_number,
            issuer_cik=filing.cik,
            issuer_name=metadata.issuer_name,
            form=form,
            source_url=str(filing.filing_url),
            body=document.body,
            accepted_at=filing.accepted_at,
            retrieved_at=document.retrieved_at,
            prior_receipts=prior_receipts,
            prior_search_complete=prior_search_complete,
        )
        if not receipt.events:
            raise AccountingNoSupportedEvents("no exact supported accounting events")
        return receipt


def accounting_filing_from_submissions(
    document: SecFetchedDocument,
    *,
    accession_number: str,
) -> AccountingFilingMetadata | None:
    """Select one aligned supported filing row without interpreting other history."""

    try:
        payload: object = json.loads(document.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AccountingParseError("SEC submissions metadata is not valid JSON") from error
    if not isinstance(payload, Mapping):
        raise AccountingParseError("SEC submissions metadata is not an object")
    normalized_cik = normalize_cik(payload.get("cik"))
    issuer_name = payload.get("name")
    if normalized_cik != document.cik or not isinstance(normalized_cik, str):
        raise AccountingParseError("SEC submissions CIK does not match retrieval identity")
    if not isinstance(issuer_name, str) or not issuer_name.strip():
        raise AccountingParseError("SEC submissions issuer name is unavailable")
    filings = payload.get("filings")
    recent = filings.get("recent") if isinstance(filings, Mapping) else None
    if not isinstance(recent, Mapping):
        raise AccountingParseError("SEC submissions recent filing metadata is unavailable")
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
        raise AccountingParseError("SEC submissions filing columns are malformed")
    lengths = {len(value) for value in values.values() if isinstance(value, list)}
    if len(lengths) != 1:
        raise AccountingParseError("SEC submissions filing columns are misaligned")
    accessions = values["accessionNumber"]
    assert isinstance(accessions, list)
    matches = [index for index, value in enumerate(accessions) if value == accession_number]
    if not matches:
        return None
    if len(matches) != 1:
        raise AccountingParseError("SEC submissions repeats the requested accession")
    index = matches[0]

    def selected(key: str) -> object:
        column = values[key]
        assert isinstance(column, list)
        return column[index]

    primary_document = selected("primaryDocument")
    fields = {key: selected(key) for key in columns if key != "accessionNumber"}
    if any(not isinstance(value, str) for value in fields.values()):
        raise AccountingParseError("requested SEC accounting metadata has invalid primitives")
    assert isinstance(primary_document, str)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*[.](?:htm|html)", primary_document, re.I) is None:
        raise AccountingParseError("accounting primary document is not direct HTML")
    record_id = hashlib.sha256(f"sec:accounting-filing:{accession_number}".encode()).hexdigest()
    try:
        filing = SecFilingRecord.model_validate(
            {
                "record_id": record_id,
                "cik": normalized_cik,
                "accession_number": accession_number,
                "form": fields["form"],
                "filing_date": fields["filingDate"],
                "report_date": fields["reportDate"] or None,
                "accepted_at": fields["acceptanceDateTime"],
                "available_at": document.retrieved_at,
                "retrieved_at": document.retrieved_at,
                "file_number": str(fields["fileNumber"]).strip() or None,
                "primary_document": primary_document,
                "primary_document_description": (
                    str(fields["primaryDocDescription"]).strip() or None
                ),
                "filing_url": (
                    "https://www.sec.gov/Archives/edgar/data/"
                    f"{int(normalized_cik)}/{accession_number.replace('-', '')}/"
                    f"{primary_document}"
                ),
                "source_content_sha256": document.content_sha256,
            }
        )
        normalize_accounting_form(filing.form)
        return AccountingFilingMetadata(issuer_name=issuer_name.strip(), filing=filing)
    except ValueError as error:
        raise AccountingParseError(
            "requested SEC accounting metadata violates the closed filing contract"
        ) from error
