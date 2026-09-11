"""Normalize SEC-owned JSON shapes into stable internal records."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, HttpUrl, ValidationError

from kalki_market_intelligence.providers.sec.client import SecFetchedDocument
from kalki_market_intelligence.providers.sec.contracts import (
    SecExternalCompanyFacts,
    SecExternalConcept,
    SecExternalFactUnit,
    SecExternalSubmissions,
    SecFactRecord,
    SecFilingRecord,
    SecIssuerRecord,
    SecSecurityIdentifier,
)


class SecNormalizationError(ValueError):
    """Raw SEC JSON cannot be normalized without guessing."""


def normalize_submissions(
    document: SecFetchedDocument,
) -> tuple[SecIssuerRecord, tuple[SecFilingRecord, ...]]:
    """Normalize issuer and recent filing metadata from one raw response."""

    external = _parse_model(document, SecExternalSubmissions)
    if external.cik != document.cik:
        raise SecNormalizationError("submissions response CIK does not match the request")
    securities = tuple(
        SecSecurityIdentifier(symbol=symbol, exchange_name=_optional(exchange))
        for symbol, exchange in zip(external.tickers, external.exchanges, strict=True)
    )
    issuer = SecIssuerRecord(
        record_id=_record_id("issuer", external.cik),
        cik=external.cik,
        name=external.name,
        sic=_optional(external.sic),
        sic_description=_optional(external.sic_description),
        entity_type=_optional(external.entity_type),
        securities=securities,
        available_at=document.retrieved_at,
        retrieved_at=document.retrieved_at,
        source_content_sha256=document.content_sha256,
    )
    recent = external.filings.recent
    filings = tuple(
        SecFilingRecord(
            record_id=_record_id("filing", accession_number),
            cik=external.cik,
            accession_number=accession_number,
            form=recent.forms[index],
            filing_date=recent.filing_dates[index],
            report_date=_optional_date(recent.report_dates[index]),
            accepted_at=recent.acceptance_datetimes[index],
            available_at=document.retrieved_at,
            retrieved_at=document.retrieved_at,
            file_number=_optional(recent.file_numbers[index]),
            primary_document=recent.primary_documents[index],
            primary_document_description=_optional(recent.primary_document_descriptions[index]),
            filing_url=HttpUrl(
                _filing_url(
                    external.cik,
                    accession_number,
                    recent.primary_documents[index],
                )
            ),
            source_content_sha256=document.content_sha256,
        )
        for index, accession_number in enumerate(recent.accession_numbers)
    )
    return issuer, filings


def normalize_companyfacts(document: SecFetchedDocument) -> tuple[SecFactRecord, ...]:
    """Flatten XBRL taxonomies, concepts, units, and contexts without calculation."""

    external = _parse_companyfacts(document)
    if external.cik != document.cik:
        raise SecNormalizationError("companyfacts response CIK does not match the request")
    records: list[SecFactRecord] = []
    for taxonomy, concepts in sorted(external.facts.items()):
        for tag, concept in sorted(concepts.items()):
            for unit, facts in sorted(concept.units.items()):
                for fact in facts:
                    record_key = {
                        "accession": fact.accession_number,
                        "end": fact.end.isoformat(),
                        "frame": fact.frame,
                        "start": fact.start.isoformat() if fact.start else None,
                        "tag": tag,
                        "taxonomy": taxonomy,
                        "unit": unit,
                        "value": str(fact.value),
                    }
                    records.append(
                        SecFactRecord(
                            record_id=_record_id("fact", record_key),
                            cik=external.cik,
                            entity_name=external.entity_name,
                            taxonomy=taxonomy,
                            tag=tag,
                            label=concept.label,
                            description=_optional(concept.description),
                            unit=unit,
                            value=fact.value,
                            period_start=fact.start,
                            period_end=fact.end,
                            filed_date=fact.filed,
                            accession_number=fact.accession_number,
                            form=fact.form,
                            fiscal_year=fact.fiscal_year,
                            fiscal_period=_optional(fact.fiscal_period or ""),
                            frame=_optional(fact.frame or ""),
                            available_at=document.retrieved_at,
                            retrieved_at=document.retrieved_at,
                            source_content_sha256=document.content_sha256,
                        )
                    )
    return tuple(records)


def _parse_companyfacts(document: SecFetchedDocument) -> SecExternalCompanyFacts:
    """Parse CompanyFacts while isolating optional metadata and bad fact entries.

    SEC occasionally returns null/empty human-readable labels or descriptions.
    Those fields are useful display metadata, not fact identity.  We preserve
    the taxonomy/tag and replace an unavailable label with the tag itself.  A
    malformed individual fact or concept is skipped, while required envelope
    identity (CIK/entity name) still fails closed.
    """

    try:
        decoded = json.loads(document.body, parse_float=Decimal)
        if not isinstance(decoded, Mapping):
            raise ValueError("CompanyFacts payload must be an object")
        raw_facts = decoded.get("facts")
        if not isinstance(raw_facts, Mapping):
            raise ValueError("CompanyFacts facts must be an object")
        sanitized_facts: dict[str, dict[str, dict[str, object]]] = {}
        for raw_taxonomy, raw_concepts in raw_facts.items():
            if not isinstance(raw_taxonomy, str) or not raw_taxonomy.strip():
                continue
            if not isinstance(raw_concepts, Mapping):
                continue
            concepts: dict[str, dict[str, object]] = {}
            for raw_tag, raw_concept in raw_concepts.items():
                if not isinstance(raw_tag, str) or not raw_tag.strip():
                    continue
                if not isinstance(raw_concept, Mapping):
                    continue
                raw_units = raw_concept.get("units")
                if not isinstance(raw_units, Mapping):
                    continue
                units: dict[str, tuple[dict[str, object], ...]] = {}
                for raw_unit, raw_entries in raw_units.items():
                    if not isinstance(raw_unit, str) or not raw_unit.strip():
                        continue
                    if not isinstance(raw_entries, (list, tuple)):
                        continue
                    valid_entries: list[dict[str, object]] = []
                    for raw_entry in raw_entries:
                        if not isinstance(raw_entry, Mapping):
                            continue
                        try:
                            entry = SecExternalFactUnit.model_validate(raw_entry)
                        except ValidationError:
                            continue
                        valid_entries.append(entry.model_dump(by_alias=True))
                    if valid_entries:
                        units[raw_unit] = tuple(valid_entries)
                if not units:
                    continue
                raw_label = raw_concept.get("label")
                label = raw_label.strip() if isinstance(raw_label, str) else ""
                # The tag is the stable identity; it is not presented as a
                # human label when SEC omitted that optional metadata.
                candidate_concept = {
                    "label": label or raw_tag,
                    "description": (
                        raw_concept.get("description")
                        if isinstance(raw_concept.get("description"), str)
                        else ""
                    ),
                    "units": units,
                }
                try:
                    SecExternalConcept.model_validate(candidate_concept)
                except ValidationError:
                    # Keep the rest of the taxonomy usable when one concept's
                    # optional metadata or tag shape is outside our contract.
                    continue
                concepts[raw_tag] = candidate_concept
            if concepts:
                sanitized_facts[raw_taxonomy] = concepts
        payload = dict(decoded)
        payload["facts"] = sanitized_facts
        return SecExternalCompanyFacts.model_validate(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError) as error:
        raise SecNormalizationError(
            f"invalid {document.endpoint} response: {type(error).__name__}"
        ) from error


def logical_fingerprint(
    issuer: SecIssuerRecord,
    filings: tuple[SecFilingRecord, ...],
    facts: tuple[SecFactRecord, ...],
    source_content_hashes: tuple[str, ...],
) -> str:
    """Identify normalized logical content independently of ingestion side effects."""

    return _record_id(
        "batch",
        {
            "cik": issuer.cik,
            "issuer": issuer.record_id,
            "source_hashes": sorted(set(source_content_hashes)),
            "filings": sorted(record.record_id for record in filings),
            "facts": sorted(record.record_id for record in facts),
        },
    )


def _parse_model[ModelT: BaseModel](document: SecFetchedDocument, model: type[ModelT]) -> ModelT:
    try:
        decoded = json.loads(document.body, parse_float=Decimal)
        return model.model_validate(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
        raise SecNormalizationError(
            f"invalid {document.endpoint} response: {type(error).__name__}"
        ) from error


def _record_id(kind: str, value: object) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"sec:{kind}:{serialized}".encode()).hexdigest()


def _optional(value: str) -> str | None:
    normalized = value.strip()
    return normalized or None


def _optional_date(value: str) -> date | None:
    normalized = value.strip()
    if not normalized:
        return None
    try:
        return date.fromisoformat(normalized)
    except ValueError as error:
        raise SecNormalizationError("SEC report date is not ISO formatted") from error


def _filing_url(cik: str, accession_number: str, primary_document: str) -> str:
    cik_without_zeroes = str(int(cik))
    accession_path = accession_number.replace("-", "")
    return (
        "https://www.sec.gov/Archives/edgar/data/"
        f"{cik_without_zeroes}/{accession_path}/{primary_document}"
    )
