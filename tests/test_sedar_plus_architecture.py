"""Tests for the disabled SEDAR+ provider and future authorized-feed boundary."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from kalki_market_intelligence.providers.sedar_plus.contracts import (
    CanadianDisclosureRecord,
    IdentifierNamespace,
    LicensedDisclosureEnvelope,
)
from kalki_market_intelligence.providers.sedar_plus.normalization import (
    SedarPlusRightsError,
    normalize_authorized_disclosure,
)
from kalki_market_intelligence.providers.sedar_plus.provider import (
    SedarPlusAutomationUnavailable,
    UnavailableSedarPlusProvider,
)

FIXTURE = (
    Path(__file__).parents[1] / "data/fixtures/sedar_plus/synthetic-authorized-disclosure.json"
)
RETRIEVED_AT = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)


def envelope() -> LicensedDisclosureEnvelope:
    return LicensedDisclosureEnvelope.model_validate_json(FIXTURE.read_text())


def test_public_site_provider_fails_closed_without_network_access() -> None:
    provider = UnavailableSedarPlusProvider()

    with pytest.raises(SedarPlusAutomationUnavailable, match="not authorized"):
        provider.fetch_disclosures("SYNTHETIC-PROFILE")


def test_authorized_envelope_normalizes_to_utc_with_source_lineage() -> None:
    normalized = normalize_authorized_disclosure(envelope(), retrieved_at=RETRIEVED_AT)

    assert normalized.issuer.country == "CA"
    assert normalized.issuer.retrieved_at == RETRIEVED_AT
    assert normalized.disclosure.filed_at == datetime(2026, 3, 31, 20, 15, tzinfo=UTC)
    assert normalized.disclosure.available_at == datetime(2026, 3, 31, 20, 16, tzinfo=UTC)
    assert normalized.disclosure.content_sha256 == "c" * 64
    assert normalized.disclosure.source_record_sha256 == normalized.issuer.source_record_sha256
    assert normalized.disclosure.public_redistribution_allowed is False


def test_identifier_mapping_keeps_profile_and_lei_explicit() -> None:
    normalized = normalize_authorized_disclosure(envelope(), retrieved_at=RETRIEVED_AT)

    assert [(item.namespace, item.value) for item in normalized.issuer.identifiers] == [
        (IdentifierNamespace.SEDAR_PLUS_PROFILE, "SYNTHETIC-CA-PROFILE-0001"),
        (IdentifierNamespace.LEI, "SYNTHETICLEI00000057"),
    ]
    assert len(normalized.issuer.listings) == 2


def test_invalid_lei_checksum_is_rejected() -> None:
    payload = json.loads(FIXTURE.read_text())
    payload["issuer"]["lei"] = "SYNTHETICLEI00000000"

    with pytest.raises(ValidationError, match="LEI checksum"):
        LicensedDisclosureEnvelope.model_validate(payload)


def test_same_name_does_not_collapse_distinct_provider_profiles() -> None:
    original = envelope()
    second_profile = original.issuer.model_copy(
        update={"provider_profile_id": "SYNTHETIC-CA-PROFILE-0002"}
    )
    second = original.model_copy(
        update={
            "issuer": second_profile,
            "provider_document_id": "SYNTHETIC-CA-DOCUMENT-0002",
        }
    )

    first_record = normalize_authorized_disclosure(original, retrieved_at=RETRIEVED_AT)
    second_record = normalize_authorized_disclosure(second, retrieved_at=RETRIEVED_AT)

    assert first_record.issuer.legal_name == second_record.issuer.legal_name
    assert first_record.issuer.record_id != second_record.issuer.record_id


@pytest.mark.parametrize(
    "rights_update",
    [
        {"automated_processing_allowed": False},
        {"database_storage_allowed": False},
        {"expires_on": date(2026, 3, 31)},
    ],
)
def test_missing_or_expired_rights_fail_before_normalization(
    rights_update: dict[str, object],
) -> None:
    original = envelope()
    restricted = original.model_copy(
        update={"rights": original.rights.model_copy(update=rights_update)}
    )

    with pytest.raises(SedarPlusRightsError):
        normalize_authorized_disclosure(restricted, retrieved_at=RETRIEVED_AT)


def test_retrieval_before_public_availability_is_rejected() -> None:
    with pytest.raises(ValidationError, match="retrieved_at must not precede available_at"):
        normalize_authorized_disclosure(
            envelope(),
            retrieved_at=datetime(2026, 3, 31, 20, 15, 30, tzinfo=UTC),
        )


def test_normalized_disclosure_schema_is_closed() -> None:
    schema = CanadianDisclosureRecord.model_json_schema()

    assert schema["additionalProperties"] is False
    assert {
        "agreement_reference",
        "available_at",
        "content_sha256",
        "filed_at",
        "retrieved_at",
    } <= set(schema["required"])
