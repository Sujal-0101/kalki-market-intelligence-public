"""Optional EdgarTools interpretation adapter with Kalki-owned provenance.

The adapter is deliberately not part of the production ingestion path yet.  It
accepts a small, parser-neutral view so equivalence can be tested without
installing EdgarTools or allowing that library to own identity and hashes.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Protocol

from pydantic import HttpUrl

from kalki_market_intelligence.contracts.common import Sha256Hex
from kalki_market_intelligence.providers.sec.contracts import SecFilingRecord


class EdgarToolsFilingView(Protocol):
    """Minimum semantic fields required from an EdgarTools filing object."""

    @property
    def cik(self) -> str: ...

    @property
    def accession_number(self) -> str: ...

    @property
    def form(self) -> str: ...

    @property
    def filing_date(self) -> date: ...

    @property
    def report_date(self) -> date | None: ...

    @property
    def accepted_at(self) -> datetime: ...

    @property
    def file_number(self) -> str | None: ...

    @property
    def primary_document(self) -> str: ...

    @property
    def primary_document_description(self) -> str | None: ...

    @property
    def filing_url(self) -> str: ...


class EdgarToolsAdapter:
    """Convert an interpreted filing while retaining SEC boundary metadata."""

    parser_name = "edgartools"

    def adapt(
        self,
        filing: EdgarToolsFilingView,
        *,
        source_content_sha256: Sha256Hex,
        available_at: datetime,
        retrieved_at: datetime,
    ) -> SecFilingRecord:
        """Return a normal Kalki filing record; no network or parser import occurs."""

        # Match Kalki's existing normalization identity exactly: accession only.
        record_id = hashlib.sha256(
            f"sec:filing:{json.dumps(filing.accession_number)}".encode()
        ).hexdigest()
        return SecFilingRecord(
            record_id=record_id,
            cik=filing.cik,
            accession_number=filing.accession_number,
            form=filing.form,
            filing_date=filing.filing_date,
            report_date=filing.report_date,
            accepted_at=filing.accepted_at,
            available_at=available_at,
            retrieved_at=retrieved_at,
            file_number=filing.file_number,
            primary_document=filing.primary_document,
            primary_document_description=filing.primary_document_description,
            filing_url=HttpUrl(filing.filing_url),
            source_content_sha256=source_content_sha256,
        )
