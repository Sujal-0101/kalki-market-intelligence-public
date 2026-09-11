"""Command-line entry point for approved SEC issuer ingestion."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from pydantic import ValidationError

from kalki_market_intelligence.config import Settings
from kalki_market_intelligence.providers.sec.client import SecClient, SecProviderError
from kalki_market_intelligence.providers.sec.ingestion import SecIngestionService
from kalki_market_intelligence.providers.sec.normalization import SecNormalizationError
from kalki_market_intelligence.providers.sec.storage import (
    ArtifactIntegrityError,
    FileSecArtifactStore,
)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cik", nargs="+", help="one or more SEC CIK values")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Ingest explicitly requested issuers without running a crawler."""

    args = _parse_args(argv)
    try:
        settings = Settings.load()
        if settings.sec_user_agent is None:
            raise ValueError(
                "KALKI_SEC_USER_AGENT is required; use an application name and contact email"
            )
        client = SecClient(
            user_agent=settings.sec_user_agent,
            requests_per_second=settings.sec_requests_per_second,
            timeout_seconds=settings.sec_timeout_seconds,
            maximum_response_bytes=settings.sec_maximum_response_bytes,
        )
        service = SecIngestionService(client, FileSecArtifactStore(settings.data_dir))
        for cik in args.cik:
            batch = service.ingest_issuer(cik)
            print(
                json.dumps(
                    {
                        "cik": batch.cik,
                        "issuer": batch.issuer.name,
                        "filings": len(batch.filings),
                        "facts": len(batch.facts),
                        "artifacts": len(batch.artifacts),
                        "logical_fingerprint": batch.logical_fingerprint,
                    },
                    sort_keys=True,
                )
            )
    except (
        ArtifactIntegrityError,
        SecNormalizationError,
        SecProviderError,
        ValidationError,
        ValueError,
        OSError,
    ) as error:
        print(f"SEC ingestion failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
