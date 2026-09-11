"""Fixture-driven SEC normalization, provenance, and recovery tests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from kalki_market_intelligence.providers.sec.client import (
    HttpResult,
    RateLimiter,
    SecClient,
    SecFetchedDocument,
    SecHttpError,
)
from kalki_market_intelligence.providers.sec.ingestion import SecIngestionService
from kalki_market_intelligence.providers.sec.normalization import (
    SecNormalizationError,
    normalize_companyfacts,
)
from kalki_market_intelligence.providers.sec.storage import FileSecArtifactStore

FIXTURE_ROOT = Path(__file__).parents[1] / "data/fixtures/sec"
RETRIEVED_AT = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


class FixtureTransport:
    def __init__(self, responses: list[HttpResult]) -> None:
        self.responses = responses
        self.requests: list[str] = []

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        maximum_bytes: int,
    ) -> HttpResult:
        self.requests.append(url)
        if not self.responses:
            raise AssertionError("fixture transport received an unexpected request")
        return self.responses.pop(0)


def fixture_response(name: str, url: str, *, status: int = 200) -> HttpResult:
    return HttpResult(
        url=url,
        status_code=status,
        headers={"content-type": "application/json", "etag": f'"{name}"'},
        body=(FIXTURE_ROOT / name).read_bytes(),
    )


def issuer_responses(prefix: str, cik: str) -> list[HttpResult]:
    return [
        fixture_response(
            f"{prefix}-submissions.json",
            f"https://data.sec.gov/submissions/CIK{cik}.json",
        ),
        fixture_response(
            f"{prefix}-companyfacts.json",
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
        ),
    ]


def service(tmp_path: Path, responses: list[HttpResult]) -> SecIngestionService:
    client = SecClient(
        user_agent="Kalki fixture tests test@example.com",
        transport=FixtureTransport(responses),
        limiter=RateLimiter(10, monotonic=lambda: 0.0, sleep=lambda _: None),
        retry_sleep=lambda _: None,
        now=lambda: RETRIEVED_AT,
    )
    return SecIngestionService(client, FileSecArtifactStore(tmp_path / "research-data"))


@pytest.mark.parametrize(
    ("prefix", "cik", "expected_filings", "expected_facts"),
    [
        ("synthetic-alpha", "0000000001", 2, 2),
        ("synthetic-beta", "0000000002", 1, 1),
    ],
)
def test_representative_issuer_set_normalizes_with_lineage(
    tmp_path: Path,
    prefix: str,
    cik: str,
    expected_filings: int,
    expected_facts: int,
) -> None:
    batch = service(tmp_path, issuer_responses(prefix, cik)).ingest_issuer(cik)

    assert batch.cik == cik
    assert len(batch.filings) == expected_filings
    assert len(batch.facts) == expected_facts
    assert len(batch.artifacts) == 2
    assert batch.issuer.available_at == RETRIEVED_AT
    assert all(filing.available_at == RETRIEVED_AT for filing in batch.filings)
    assert all(fact.available_at == RETRIEVED_AT for fact in batch.facts)
    source_hashes = {artifact.content_sha256 for artifact in batch.artifacts}
    assert batch.issuer.source_content_sha256 in source_hashes
    assert all(fact.source_content_sha256 in source_hashes for fact in batch.facts)


def test_company_fact_preserves_decimal_unit_context_and_accession(tmp_path: Path) -> None:
    batch = service(
        tmp_path,
        issuer_responses("synthetic-alpha", "0000000001"),
    ).ingest_issuer(1)
    revenue = next(fact for fact in batch.facts if fact.tag == "Revenues")

    assert revenue.value == Decimal("42000000.25")
    assert revenue.unit == "USD"
    assert revenue.period_start == datetime(2025, 1, 1).date()
    assert revenue.period_end == datetime(2025, 12, 31).date()
    assert revenue.accession_number == "0000000001-26-000001"


def test_filing_url_is_derived_from_validated_identifiers(tmp_path: Path) -> None:
    batch = service(
        tmp_path,
        issuer_responses("synthetic-alpha", "0000000001"),
    ).ingest_issuer(1)

    assert str(batch.filings[0].filing_url) == (
        "https://www.sec.gov/Archives/edgar/data/1/000000000126000001/synthetic-alpha-2025.htm"
    )


def test_repeated_ingestion_is_idempotent(tmp_path: Path) -> None:
    responses = issuer_responses("synthetic-alpha", "0000000001") * 2
    ingestion = service(tmp_path, responses)

    first = ingestion.ingest_issuer(1)
    second = ingestion.ingest_issuer(1)

    assert first == second
    assert first.logical_fingerprint == second.logical_fingerprint
    stored_files = list((tmp_path / "research-data/raw/sec").rglob("*.json"))
    assert len(stored_files) == 4


def test_failure_retains_valid_raw_checkpoint_and_retry_recovers(tmp_path: Path) -> None:
    submissions, companyfacts = issuer_responses("synthetic-beta", "0000000002")
    unavailable = HttpResult(
        url=companyfacts.url,
        status_code=503,
        headers={"content-type": "application/json"},
        body=b'{"message":"synthetic unavailable response"}',
    )
    data_root = tmp_path / "research-data"
    failing_client = SecClient(
        user_agent="Kalki fixture tests test@example.com",
        transport=FixtureTransport([submissions, unavailable]),
        limiter=RateLimiter(10, monotonic=lambda: 0.0, sleep=lambda _: None),
        maximum_attempts=1,
        now=lambda: RETRIEVED_AT,
    )

    with pytest.raises(SecHttpError):
        SecIngestionService(failing_client, FileSecArtifactStore(data_root)).ingest_issuer(2)

    assert len(list(data_root.rglob("*.json"))) == 2

    recovered = service(
        tmp_path,
        issuer_responses("synthetic-beta", "0000000002"),
    ).ingest_issuer(2)
    assert recovered.cik == "0000000002"
    assert len(list(data_root.rglob("*.json"))) == 4


def test_misaligned_submission_columns_fail_without_guessing(tmp_path: Path) -> None:
    submissions, companyfacts = issuer_responses("synthetic-alpha", "0000000001")
    payload = json.loads(submissions.body)
    payload["filings"]["recent"]["primaryDocDescription"].pop()
    malformed = HttpResult(
        url=submissions.url,
        status_code=200,
        headers=submissions.headers,
        body=json.dumps(payload).encode(),
    )

    with pytest.raises(SecNormalizationError, match="ValidationError"):
        service(tmp_path, [malformed, companyfacts]).ingest_issuer(1)

    # The exact raw response remains available for diagnosis, but no facts were fetched.
    assert len(list((tmp_path / "research-data").rglob("*.json"))) == 2


def test_raw_manifest_records_hash_url_and_utc_retrieval(tmp_path: Path) -> None:
    batch = service(
        tmp_path,
        issuer_responses("synthetic-beta", "0000000002"),
    ).ingest_issuer(2)
    artifact = batch.artifacts[0]
    manifest = json.loads((tmp_path / "research-data" / artifact.manifest_path).read_text())
    blob = (tmp_path / "research-data" / artifact.blob_path).read_bytes()

    assert manifest["content_sha256"] == artifact.content_sha256
    assert manifest["retrieved_at"] == "2026-08-21T12:00:00Z"
    assert manifest["url"].startswith("https://data.sec.gov/")
    assert len(blob) == manifest["byte_length"]


def test_companyfacts_null_optional_metadata_keeps_valid_facts() -> None:
    payload = {
        "cik": 1,
        "entityName": "Synthetic issuer",
        "facts": {
            "us-gaap": {
                "Revenue": {
                    "label": None,
                    "description": None,
                    "units": {
                        "USD": [
                            {
                                "end": "2025-12-31",
                                "val": 42,
                                "accn": "0000000001-26-000001",
                                "form": "10-K",
                                "filed": "2026-02-01",
                            },
                            {"end": "not-a-date", "val": 99},
                        ]
                    },
                }
            }
        },
    }
    document = SecFetchedDocument(
        endpoint="companyfacts",
        cik="0000000001",
        url="https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
        status_code=200,
        headers={"content-type": "application/json"},
        body=json.dumps(payload).encode(),
        content_sha256="a" * 64,
        retrieved_at=RETRIEVED_AT,
    )

    facts = normalize_companyfacts(document)

    assert len(facts) == 1
    assert facts[0].tag == "Revenue"
    assert facts[0].label == "Revenue"
    assert facts[0].description is None


def test_companyfacts_missing_required_identity_fails_closed() -> None:
    document = SecFetchedDocument(
        endpoint="companyfacts",
        cik="0000000001",
        url="https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
        status_code=200,
        headers={"content-type": "application/json"},
        body=json.dumps({"facts": {}}).encode(),
        content_sha256="b" * 64,
        retrieved_at=RETRIEVED_AT,
    )

    with pytest.raises(SecNormalizationError):
        normalize_companyfacts(document)
