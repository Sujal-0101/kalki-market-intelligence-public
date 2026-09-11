"""Exact SEC metadata acquisition for bounded financing intelligence."""

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
from kalki_market_intelligence.forensics.financing import (
    FinancingFilingReceipt,
    FinancingForm,
    FinancingParseError,
    extract_financing_evidence,
    normalize_financing_form,
    parse_financing_terms,
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


class FinancingIdentityMismatch(FinancingParseError):
    """The selected SEC index identity does not own the primary filing."""


class FinancingNoSupportedTerms(FinancingParseError):
    """The filing is valid, but no exact Phase 40 term grammar completed."""


class FinancingDiscoveryCandidate(ContractModel):
    accession_number: AccessionNumber
    index_ciks: tuple[Cik, ...] = Field(min_length=1, max_length=16)
    index_names: tuple[ShortText, ...] = Field(min_length=1, max_length=16)
    form: FinancingForm
    filed_on: date
    discovered_at: UtcDatetime
    source_index_url: HttpUrl
    source_index_sha256: Sha256Hex

    @model_validator(mode="after")
    def discovery_is_consistent(self) -> FinancingDiscoveryCandidate:
        if len(self.index_ciks) != len(self.index_names):
            raise ValueError("financing index CIK and name rows must remain paired")
        if self.index_ciks != tuple(sorted(set(self.index_ciks))):
            raise ValueError("financing index CIK rows must be sorted and unique")
        if self.discovered_at.date() < self.filed_on:
            raise ValueError("financing discovery cannot precede filing date")
        return self


class FinancingFilingMetadata(ContractModel):
    issuer_name: ShortText
    filing: SecFilingRecord


class FinancingDocumentClient(Protocol):
    def fetch_primary_html_document(
        self,
        *,
        cik: str | int,
        accession_number: str,
        document_name: str,
    ) -> SecFetchedPrimaryDocument: ...


class SecFinancingIngestionService:
    def __init__(self, client: FinancingDocumentClient) -> None:
        self._client = client

    def ingest(
        self,
        metadata: FinancingFilingMetadata,
        *,
        primary_document_observer: (
            Callable[[SecFilingRecord, SecFetchedPrimaryDocument], None] | None
        ) = None,
    ) -> FinancingFilingReceipt:
        filing = metadata.filing
        form = normalize_financing_form(filing.form)
        document = self._client.fetch_primary_html_document(
            cik=filing.cik,
            accession_number=filing.accession_number,
            document_name=filing.primary_document,
        )
        if document.url != str(filing.filing_url):
            raise FinancingIdentityMismatch("fetched financing URL does not match metadata")
        if document.content_sha256 != hashlib.sha256(document.body).hexdigest():
            raise FinancingParseError("financing document hash changed during acquisition")
        if primary_document_observer is not None:
            primary_document_observer(filing, document)
        bundle = extract_financing_evidence(document.body)
        terms = parse_financing_terms(bundle)
        if not terms:
            raise FinancingNoSupportedTerms("no exact supported financing terms")
        if bundle.source_content_sha256 != document.content_sha256:
            raise FinancingParseError("financing document hash changed during parsing")
        return FinancingFilingReceipt(
            accession_number=filing.accession_number,
            issuer_cik=filing.cik,
            issuer_name=metadata.issuer_name,
            form=form,
            terms=terms,
            evidence_bundle=bundle,
            source_url=filing.filing_url,
            source_content_sha256=document.content_sha256,
            accepted_at=filing.accepted_at,
            retrieved_at=document.retrieved_at,
        )


def financing_filing_from_submissions(
    document: SecFetchedDocument,
    *,
    accession_number: str,
) -> FinancingFilingMetadata | None:
    """Select one aligned financing row without validating unrelated history."""

    try:
        payload: object = json.loads(document.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FinancingParseError("SEC submissions metadata is not valid JSON") from error
    if not isinstance(payload, Mapping):
        raise FinancingParseError("SEC submissions metadata is not an object")
    normalized_cik = normalize_cik(payload.get("cik"))
    issuer_name = payload.get("name")
    if normalized_cik != document.cik or not isinstance(normalized_cik, str):
        raise FinancingParseError("SEC submissions CIK does not match retrieval identity")
    if not isinstance(issuer_name, str) or not issuer_name.strip():
        raise FinancingParseError("SEC submissions issuer name is unavailable")
    filings = payload.get("filings")
    recent = filings.get("recent") if isinstance(filings, Mapping) else None
    if not isinstance(recent, Mapping):
        raise FinancingParseError("SEC submissions recent filing metadata is unavailable")
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
        raise FinancingParseError("SEC submissions filing columns are malformed")
    lengths = {len(value) for value in values.values() if isinstance(value, list)}
    if len(lengths) != 1:
        raise FinancingParseError("SEC submissions filing columns are misaligned")
    accessions = values["accessionNumber"]
    assert isinstance(accessions, list)
    matches = [index for index, value in enumerate(accessions) if value == accession_number]
    if not matches:
        return None
    if len(matches) != 1:
        raise FinancingParseError("SEC submissions repeats the requested accession")
    index = matches[0]

    def selected(key: str) -> object:
        column = values[key]
        assert isinstance(column, list)
        return column[index]

    primary_document = selected("primaryDocument")
    fields = {key: selected(key) for key in columns if key != "accessionNumber"}
    if any(not isinstance(value, str) for value in fields.values()):
        raise FinancingParseError("requested SEC financing metadata has invalid primitives")
    assert isinstance(primary_document, str)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*[.](?:htm|html)", primary_document, re.I) is None:
        raise FinancingParseError("financing primary document is not direct HTML")
    record_id = hashlib.sha256(f"sec:financing-filing:{accession_number}".encode()).hexdigest()
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
        normalize_financing_form(filing.form)
        return FinancingFilingMetadata(issuer_name=issuer_name.strip(), filing=filing)
    except ValueError as error:
        raise FinancingParseError(
            "requested SEC financing metadata violates the closed filing contract"
        ) from error
