"""Compliant SEC EDGAR ingestion provider."""

from typing import TYPE_CHECKING

from kalki_market_intelligence.providers.sec.client import SecClient
from kalki_market_intelligence.providers.sec.edgartools_adapter import EdgarToolsAdapter
from kalki_market_intelligence.providers.sec.ingestion import SecIngestionService
from kalki_market_intelligence.providers.sec.storage import FileSecArtifactStore

if TYPE_CHECKING:
    from kalki_market_intelligence.providers.sec.filing_change import FilingChangeExtraction

__all__ = [
    "EdgarToolsAdapter",
    "FileSecArtifactStore",
    "FilingChangeExtraction",
    "SecClient",
    "SecIngestionService",
    "build_amendment_manifest_from_filing_change_snapshot",
    "build_snapshot_from_filing_change_extraction",
    "extract_filing_change_sections",
]


def __getattr__(name: str) -> object:
    """Load Phase 42 helpers without creating a contracts import cycle."""

    filing_change_exports = {
        "FilingChangeExtraction",
        "build_amendment_manifest_from_filing_change_snapshot",
        "build_snapshot_from_filing_change_extraction",
        "extract_filing_change_sections",
    }
    if name not in filing_change_exports:
        raise AttributeError(name)
    from kalki_market_intelligence.providers.sec import filing_change

    return getattr(filing_change, name)
