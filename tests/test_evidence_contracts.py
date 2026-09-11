"""Tests for provenance, UTC, and evidence invariants."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from kalki_market_intelligence.contracts.evidence import (
    EvidenceClaim,
    EvidenceKind,
    SourceClass,
    SourceDocument,
    SourceQuality,
    quality_for_source_class,
)

SOURCE_ID = UUID("00000000-0000-4000-8000-000000000010")
CLAIM_ID = UUID("00000000-0000-4000-8000-000000000011")
CONTENT_HASH = "a" * 64
PUBLISHED_AT = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


def source_document(**overrides: object) -> SourceDocument:
    values: dict[str, object] = {
        "source_id": SOURCE_ID,
        "source_class": SourceClass.SEC,
        "publisher": "U.S. Securities and Exchange Commission",
        "title": "Example filing",
        "canonical_url": "https://www.sec.gov/example",
        "media_type": "application/json",
        "content_sha256": CONTENT_HASH,
        "published_at": PUBLISHED_AT,
        "available_at": PUBLISHED_AT + timedelta(minutes=1),
        "retrieved_at": PUBLISHED_AT + timedelta(minutes=2),
    }
    values.update(overrides)
    return SourceDocument.model_validate(values)


def test_source_document_normalizes_aware_timestamps_to_utc() -> None:
    eastern = timezone(timedelta(hours=-4))
    source = source_document(
        published_at=datetime(2026, 8, 20, 8, 0, tzinfo=eastern),
    )

    assert source.published_at == PUBLISHED_AT
    assert source.published_at.tzinfo is UTC


def test_source_document_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone offset"):
        source_document(published_at=datetime(2026, 8, 20, 12, 0))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "available_at",
            PUBLISHED_AT - timedelta(seconds=1),
            "available_at must be on or after published_at",
        ),
        (
            "retrieved_at",
            PUBLISHED_AT,
            "retrieved_at must be on or after available_at",
        ),
    ],
)
def test_source_document_rejects_temporal_leakage(
    field: str,
    value: datetime,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        source_document(**{field: value})


def test_source_document_rejects_invalid_content_hash() -> None:
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        source_document(content_sha256="not-a-sha256")


def test_direct_quote_requires_verbatim_text() -> None:
    with pytest.raises(ValidationError, match="verbatim_text"):
        EvidenceClaim(
            claim_id=CLAIM_ID,
            source_id=SOURCE_ID,
            kind=EvidenceKind.DIRECT_QUOTE,
            statement="Management described demand as strong.",
            locator="page 4",
            recorded_at=PUBLISHED_AT + timedelta(minutes=3),
        )


def test_inference_is_explicit_and_source_linked() -> None:
    claim = EvidenceClaim(
        claim_id=CLAIM_ID,
        source_id=SOURCE_ID,
        kind=EvidenceKind.ANALYST_INFERENCE,
        statement="The contract could diversify revenue.",
        locator="section 2",
        recorded_at=PUBLISHED_AT + timedelta(minutes=3),
    )

    assert claim.source_id == SOURCE_ID
    assert claim.kind is EvidenceKind.ANALYST_INFERENCE


def test_evidence_contract_exports_closed_json_schema() -> None:
    schema = SourceDocument.model_json_schema()

    assert schema["additionalProperties"] is False
    assert {
        "available_at",
        "canonical_url",
        "content_sha256",
        "published_at",
        "retrieved_at",
        "source_class",
        "source_id",
    } <= set(schema["required"])


def test_source_quality_is_derived_from_authority_class() -> None:
    assert source_document().source_quality is SourceQuality.PRIMARY
    assert (
        source_document(source_class=SourceClass.REPUTABLE_NEWS).source_quality
        is SourceQuality.SUPPORTING
    )
    assert (
        source_document(source_class=SourceClass.DISCOVERY_ONLY).source_quality
        is SourceQuality.LOWER_CONFIDENCE
    )
    assert quality_for_source_class(SourceClass.COMPANY_IR) is SourceQuality.PRIMARY


def test_source_quality_cannot_downgrade_a_primary_source() -> None:
    with pytest.raises(ValidationError, match="source_quality must match"):
        source_document(source_quality=SourceQuality.LOWER_CONFIDENCE)


def test_legacy_evidence_claim_defaults_to_conservative_quality() -> None:
    claim = EvidenceClaim(
        claim_id=CLAIM_ID,
        source_id=SOURCE_ID,
        kind=EvidenceKind.REPORTED_FACT,
        statement="A filing reported a result.",
        locator="section 1",
        recorded_at=PUBLISHED_AT + timedelta(minutes=3),
    )
    assert claim.source_quality is SourceQuality.LOWER_CONFIDENCE
