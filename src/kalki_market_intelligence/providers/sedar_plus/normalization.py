"""Normalize only disclosure envelopes carrying explicit automation/storage rights."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from kalki_market_intelligence.providers.sedar_plus.contracts import (
    CanadianDisclosureRecord,
    CanadianIdentifier,
    CanadianIngestionRecord,
    CanadianIssuerMapping,
    IdentifierNamespace,
    LicensedDisclosureEnvelope,
)


class SedarPlusRightsError(ValueError):
    """A source agreement does not authorize the intended local operation."""


def normalize_authorized_disclosure(
    envelope: LicensedDisclosureEnvelope,
    *,
    retrieved_at: datetime,
) -> CanadianIngestionRecord:
    """Build traceable Canadian records without guessing identifiers or rights."""

    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise SedarPlusRightsError("retrieved_at must include a timezone offset")
    retrieved_at = retrieved_at.astimezone(UTC)
    if not envelope.rights.automated_processing_allowed:
        raise SedarPlusRightsError("source agreement does not allow automated processing")
    if not envelope.rights.database_storage_allowed:
        raise SedarPlusRightsError("source agreement does not allow database storage")
    if envelope.rights.expires_on is not None and retrieved_at.date() > envelope.rights.expires_on:
        raise SedarPlusRightsError("source agreement expired before retrieval")
    identifiers = [
        CanadianIdentifier(
            namespace=IdentifierNamespace.SEDAR_PLUS_PROFILE,
            value=envelope.issuer.provider_profile_id,
        )
    ]
    if envelope.issuer.lei is not None:
        identifiers.append(
            CanadianIdentifier(namespace=IdentifierNamespace.LEI, value=envelope.issuer.lei)
        )
    issuer_record_id = _record_id(
        "issuer",
        {
            "namespace": IdentifierNamespace.SEDAR_PLUS_PROFILE,
            "value": envelope.issuer.provider_profile_id,
        },
    )
    issuer = CanadianIssuerMapping(
        record_id=issuer_record_id,
        provider_profile_id=envelope.issuer.provider_profile_id,
        legal_name=envelope.issuer.legal_name,
        identifiers=tuple(identifiers),
        listings=envelope.issuer.listings,
        reporting_jurisdictions=envelope.issuer.reporting_jurisdictions,
        retrieved_at=retrieved_at,
        source_record_sha256=envelope.source_record_sha256,
    )
    disclosure = CanadianDisclosureRecord(
        record_id=_record_id(
            "disclosure",
            {
                "document_id": envelope.provider_document_id,
                "profile_id": envelope.issuer.provider_profile_id,
            },
        ),
        issuer_record_id=issuer_record_id,
        provider_document_id=envelope.provider_document_id,
        provider_profile_id=envelope.issuer.provider_profile_id,
        filing_category=envelope.filing_category,
        document_type=envelope.document_type,
        title=envelope.title,
        filed_at=envelope.filed_at,
        available_at=envelope.became_public_at or retrieved_at,
        retrieved_at=retrieved_at,
        language=envelope.language,
        media_type=envelope.media_type,
        byte_length=envelope.byte_length,
        content_sha256=envelope.content_sha256,
        source_record_sha256=envelope.source_record_sha256,
        access_mode=envelope.access_mode,
        agreement_reference=envelope.rights.agreement_reference,
        public_redistribution_allowed=envelope.rights.public_redistribution_allowed,
        authorized_locator=envelope.authorized_locator,
    )
    return CanadianIngestionRecord(issuer=issuer, disclosure=disclosure)


def _record_id(kind: str, value: object) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"sedar-plus:{kind}:{serialized}".encode()).hexdigest()
