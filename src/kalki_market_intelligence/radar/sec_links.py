"""Fail-closed canonical SEC filing links for later public projections."""

from __future__ import annotations

import re
from hashlib import sha256
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import StringConstraints, model_validator

from kalki_market_intelligence.contracts.common import ContractModel, Sha256Hex, UtcDatetime
from kalki_market_intelligence.providers.sec.client import SecProviderError
from kalki_market_intelligence.radar.contracts import AccessionNumber
from kalki_market_intelligence.radar.sec_source import SecRadarClient, SecRadarDocument

SEC_LINK_VALIDATION_VERSION: Literal["1.0.0"] = "1.0.0"
_DOCUMENT_BLOCK = re.compile(rb"<DOCUMENT>(.*?)</DOCUMENT>", re.IGNORECASE | re.DOTALL)
_PRIMARY_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*[.](?:htm|html)$", re.IGNORECASE)
_INLINE_XBRL = re.compile(
    rb"(?:xmlns:ix\s*=\s*['\"]https?://www[.]xbrl[.]org/(?:2008|2013)/inlineXBRL['\"]|<ix:)",
    re.IGNORECASE,
)

type CanonicalCik = Annotated[str, StringConstraints(pattern=r"^\d{10}$")]
type CompleteSubmissionUrl = Annotated[
    str,
    StringConstraints(
        max_length=2_048,
        pattern=(
            r"^https://www[.]sec[.]gov/Archives/edgar/data/\d{1,10}/(?:\d{18}/)?"
            r"\d{10}-\d{2}-\d{6}[.]txt$"
        ),
    ),
]
type ArchiveIndexUrl = Annotated[
    str,
    StringConstraints(
        max_length=2_048,
        pattern=(
            r"^https://www[.]sec[.]gov/Archives/edgar/data/\d{1,10}/\d{18}/"
            r"\d{10}-\d{2}-\d{6}-index[.]html$"
        ),
    ),
]
type PrimaryDocumentUrl = Annotated[
    str,
    StringConstraints(
        max_length=2_048,
        pattern=(
            r"^https://www[.]sec[.]gov/Archives/edgar/data/\d{1,10}/\d{18}/"
            r"[A-Za-z0-9][A-Za-z0-9._-]*[.](?:htm|html)$"
        ),
    ),
]
type InlineXbrlUrl = Annotated[
    str,
    StringConstraints(
        max_length=2_048,
        pattern=(
            r"^https://www[.]sec[.]gov/ixviewer/doc/action[?]doc=/Archives/edgar/data/"
            r"\d{1,10}/\d{18}/[A-Za-z0-9][A-Za-z0-9._-]*[.](?:htm|html)$"
        ),
    ),
]


class SecLinkValidationError(ValueError):
    """A proposed public SEC link could not be proven from the filing."""


class ValidatedSecFilingLinks(ContractModel):
    """Closed website/Discord projection derived from fetched SEC documents only."""

    receipt_id: UUID
    canonical_cik: CanonicalCik
    accession_number: AccessionNumber
    complete_submission_url: CompleteSubmissionUrl
    archive_index_url: ArchiveIndexUrl
    primary_document_url: PrimaryDocumentUrl
    inline_xbrl_url: InlineXbrlUrl | None = None
    complete_submission_sha256: Sha256Hex
    archive_index_sha256: Sha256Hex
    primary_document_sha256: Sha256Hex
    inline_xbrl_validated: bool
    validated_at: UtcDatetime
    validation_version: Literal["1.0.0"] = SEC_LINK_VALIDATION_VERSION

    @model_validator(mode="after")
    def urls_reconcile_to_identity(self) -> ValidatedSecFilingLinks:
        base = _archive_base(self.canonical_cik, self.accession_number)
        if self.complete_submission_url not in _complete_submission_urls(
            self.canonical_cik, self.accession_number
        ):
            raise ValueError("complete-submission URL does not match filing identity")
        if self.archive_index_url != f"{base}/{self.accession_number}-index.html":
            raise ValueError("archive-index URL does not match filing identity")
        primary_name = self.primary_document_url.rsplit("/", maxsplit=1)[1]
        if self.primary_document_url != f"{base}/{primary_name}":
            raise ValueError("primary-document URL does not match filing identity")
        expected_inline = (
            "https://www.sec.gov/ixviewer/doc/action?doc="
            f"/Archives/edgar/data/{int(self.canonical_cik)}/"
            f"{self.accession_number.replace('-', '')}/{primary_name}"
        )
        if self.inline_xbrl_validated != (self.inline_xbrl_url is not None):
            raise ValueError("inline-XBRL validation flag and URL must agree")
        if self.inline_xbrl_url is not None and self.inline_xbrl_url != expected_inline:
            raise ValueError("inline-XBRL URL does not match the validated primary document")
        if self.receipt_id != _receipt_id(
            self.accession_number,
            self.complete_submission_sha256,
            self.validation_version,
        ):
            raise ValueError("SEC link receipt identity does not match its immutable inputs")
        return self


class PublicSecFilingLinks(ContractModel):
    """URL-only public projection; validation hashes and operations remain private."""

    accession_number: AccessionNumber
    complete_submission_url: CompleteSubmissionUrl
    archive_index_url: ArchiveIndexUrl
    primary_document_url: PrimaryDocumentUrl
    inline_xbrl_url: InlineXbrlUrl | None = None


def public_sec_filing_links(receipt: ValidatedSecFilingLinks) -> PublicSecFilingLinks:
    """Minimize a stored validation receipt before website or Discord rendering."""

    return PublicSecFilingLinks(
        accession_number=receipt.accession_number,
        complete_submission_url=receipt.complete_submission_url,
        archive_index_url=receipt.archive_index_url,
        primary_document_url=receipt.primary_document_url,
        inline_xbrl_url=receipt.inline_xbrl_url,
    )


def validate_sec_filing_links(
    *,
    client: SecRadarClient,
    canonical_cik: str,
    accession_number: str,
    filing_form: str,
    complete_submission: SecRadarDocument,
) -> ValidatedSecFilingLinks:
    """Fetch and bind the archive index, primary document and optional ixviewer."""

    if re.fullmatch(r"\d{10}", canonical_cik) is None:
        raise SecLinkValidationError("canonical CIK is invalid")
    if re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession_number) is None:
        raise SecLinkValidationError("accession number is invalid")
    base = _archive_base(canonical_cik, accession_number)
    if complete_submission.url not in _complete_submission_urls(canonical_cik, accession_number):
        raise SecLinkValidationError("complete submission URL does not match filing identity")
    if sha256(complete_submission.body).hexdigest() != complete_submission.content_sha256:
        raise SecLinkValidationError("complete submission content hash does not reconcile")

    primary_name = extract_primary_document_name(complete_submission.body, filing_form=filing_form)
    index_url = f"{base}/{accession_number}-index.html"
    primary_url = f"{base}/{primary_name}"
    index = client.fetch(index_url, media_types=frozenset({"text/html", "application/xhtml+xml"}))
    primary = client.fetch(
        primary_url,
        media_types=frozenset({"text/html", "application/xhtml+xml"}),
    )
    if index.url != index_url or primary.url != primary_url:
        raise SecLinkValidationError("SEC filing link redirected away from its canonical URL")
    if primary_name.encode("ascii") not in index.body:
        raise SecLinkValidationError("SEC archive index does not reference the primary document")

    inline_url: str | None = None
    inline_validated = False
    validated_at = max(index.retrieved_at, primary.retrieved_at)
    if _INLINE_XBRL.search(primary.body) is not None:
        proposed_inline_url = (
            "https://www.sec.gov/ixviewer/doc/action?doc="
            f"/Archives/edgar/data/{int(canonical_cik)}/"
            f"{accession_number.replace('-', '')}/{primary_name}"
        )
        try:
            viewer = client.fetch(
                proposed_inline_url,
                media_types=frozenset({"text/html", "application/xhtml+xml"}),
            )
        except SecProviderError:
            # The viewer is optional. A missing, blocked or unavailable endpoint
            # never becomes a public URL and does not erase the independently
            # validated archive-index and primary-document links.
            pass
        else:
            if viewer.url == proposed_inline_url and viewer.body:
                inline_url = proposed_inline_url
                inline_validated = True
                validated_at = max(validated_at, viewer.retrieved_at)

    return ValidatedSecFilingLinks(
        receipt_id=_receipt_id(
            accession_number,
            complete_submission.content_sha256,
            SEC_LINK_VALIDATION_VERSION,
        ),
        canonical_cik=canonical_cik,
        accession_number=accession_number,
        complete_submission_url=complete_submission.url,
        archive_index_url=index_url,
        primary_document_url=primary_url,
        inline_xbrl_url=inline_url,
        complete_submission_sha256=complete_submission.content_sha256,
        archive_index_sha256=index.content_sha256,
        primary_document_sha256=primary.content_sha256,
        inline_xbrl_validated=inline_validated,
        validated_at=validated_at,
    )


def extract_primary_document_name(complete_submission: bytes, *, filing_form: str) -> str:
    """Select the exact primary HTML filename from a complete-submission document."""

    form = filing_form.strip().upper()
    for match in _DOCUMENT_BLOCK.finditer(complete_submission):
        block = match.group(1)
        document_type = _tag_value(block, b"TYPE")
        filename = _tag_value(block, b"FILENAME")
        if document_type is None or filename is None:
            continue
        if document_type.decode("ascii", errors="ignore").strip().upper() != form:
            continue
        try:
            name = filename.decode("ascii").strip()
        except UnicodeDecodeError as error:
            raise SecLinkValidationError("primary document filename is not ASCII") from error
        if len(name) > 255 or _PRIMARY_NAME.fullmatch(name) is None:
            raise SecLinkValidationError("primary document filename is not safe direct HTML")
        return name
    raise SecLinkValidationError("complete submission has no exact primary HTML document")


def _tag_value(block: bytes, tag: bytes) -> bytes | None:
    match = re.search(rb"<" + tag + rb">[ \t]*([^\r\n<]+)", block, re.IGNORECASE)
    return None if match is None else match.group(1).strip()


def _archive_base(canonical_cik: str, accession_number: str) -> str:
    return (
        "https://www.sec.gov/Archives/edgar/data/"
        f"{int(canonical_cik)}/{accession_number.replace('-', '')}"
    )


def _complete_submission_urls(canonical_cik: str, accession_number: str) -> frozenset[str]:
    """Return only the two official SEC complete-submission archive path shapes."""

    root = f"https://www.sec.gov/Archives/edgar/data/{int(canonical_cik)}"
    return frozenset(
        {
            f"{root}/{accession_number}.txt",
            f"{_archive_base(canonical_cik, accession_number)}/{accession_number}.txt",
        }
    )


def _receipt_id(accession_number: str, complete_sha256: str, version: str) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"kalki-sec-links:{accession_number}:{complete_sha256}:{version}",
    )
