"""Disposable PostgreSQL checks for immutable validated SEC-link receipts."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from kalki_market_intelligence.database import DatabaseOptions, DatabaseRuntime
from kalki_market_intelligence.radar.sec_links import ValidatedSecFilingLinks
from kalki_market_intelligence.radar.store import (
    PostgresRadarStore,
    SecLinkReceiptReplayConflict,
)
from kalki_market_intelligence.web.repository import PostgresResearchRepository

GATE_PASSWORD_FILE = os.environ.get("KALKI_SEC_LINK_GATE_PASSWORD_FILE")
GATE_PORT = int(os.environ.get("KALKI_SEC_LINK_GATE_PORT", "55448"))
ACCESSION = "0000320193-26-000001"
SOURCE_HASH = "c" * 64
BASE = "https://www.sec.gov/Archives/edgar/data/320193/000032019326000001"
COMPLETE_URL = f"https://www.sec.gov/Archives/edgar/data/320193/{ACCESSION}.txt"


def _runtime() -> DatabaseRuntime:
    assert GATE_PASSWORD_FILE is not None
    return DatabaseRuntime(
        DatabaseOptions(
            host="127.0.0.1",
            port=GATE_PORT,
            name="kalki",
            user="kalki_app",
            password_file=Path(GATE_PASSWORD_FILE),
            minimum_pool_size=1,
            maximum_pool_size=1,
        )
    )


def _receipt() -> ValidatedSecFilingLinks:
    return ValidatedSecFilingLinks(
        receipt_id=uuid5(
            NAMESPACE_URL,
            f"kalki-sec-links:{ACCESSION}:{SOURCE_HASH}:1.0.0",
        ),
        canonical_cik="0000320193",
        accession_number=ACCESSION,
        complete_submission_url=COMPLETE_URL,
        archive_index_url=f"{BASE}/{ACCESSION}-index.html",
        primary_document_url=f"{BASE}/event.htm",
        complete_submission_sha256=SOURCE_HASH,
        archive_index_sha256="d" * 64,
        primary_document_sha256="e" * 64,
        inline_xbrl_validated=False,
        validated_at=datetime(2026, 8, 30, 10, 3, 30, tzinfo=UTC),
    )


@pytest.mark.skipif(GATE_PASSWORD_FILE is None, reason="SEC-link PostgreSQL gate is not running")
def test_exact_replay_conflict_and_public_projection() -> None:
    runtime = _runtime()
    runtime.open()
    try:
        receipt = _receipt()
        store = PostgresRadarStore(runtime.connection)
        store.append_validated_sec_links(receipt)
        with pytest.raises(SecLinkReceiptReplayConflict):
            store.append_validated_sec_links(
                receipt.model_copy(
                    update={"validated_at": receipt.validated_at + timedelta(seconds=1)}
                )
            )
        repository = PostgresResearchRepository(runtime.connection)
        public = repository.get_brief_sec_links(UUID("86000000-0000-4000-8000-000000000001"))
        assert public is not None
        assert public.primary_document_url == f"{BASE}/event.htm"
        assert "sha256" not in public.model_dump()
        assert repository.get_brief_sec_links(uuid5(NAMESPACE_URL, "absent")) is None
    finally:
        runtime.close()
