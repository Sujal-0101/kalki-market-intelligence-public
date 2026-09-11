"""Orchestrate raw retention and normalized SEC issuer ingestion."""

from __future__ import annotations

from kalki_market_intelligence.providers.sec.client import SecClient
from kalki_market_intelligence.providers.sec.contracts import SecIngestionBatch
from kalki_market_intelligence.providers.sec.normalization import (
    logical_fingerprint,
    normalize_companyfacts,
    normalize_submissions,
)
from kalki_market_intelligence.providers.sec.storage import FileSecArtifactStore


class SecIngestionService:
    """Fetch both official issuer datasets and return one validated batch."""

    def __init__(self, client: SecClient, artifact_store: FileSecArtifactStore) -> None:
        self._client = client
        self._artifact_store = artifact_store

    def ingest_issuer(self, cik: str | int) -> SecIngestionBatch:
        submissions_document = self._client.fetch_submissions(cik)
        submissions_artifact = self._artifact_store.store(submissions_document)
        issuer, filings = normalize_submissions(submissions_document)

        companyfacts_document = self._client.fetch_companyfacts(issuer.cik)
        companyfacts_artifact = self._artifact_store.store(companyfacts_document)
        facts = normalize_companyfacts(companyfacts_document)

        return SecIngestionBatch(
            cik=issuer.cik,
            issuer=issuer,
            filings=filings,
            facts=facts,
            artifacts=(submissions_artifact, companyfacts_artifact),
            logical_fingerprint=logical_fingerprint(
                issuer,
                filings,
                facts,
                (
                    submissions_artifact.content_sha256,
                    companyfacts_artifact.content_sha256,
                ),
            ),
        )
