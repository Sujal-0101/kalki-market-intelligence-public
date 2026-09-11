"""Bounded ownership discovery from the official SEC daily master index."""

from __future__ import annotations

from datetime import date
from typing import NamedTuple

from pydantic import HttpUrl

from kalki_market_intelligence.providers.sec.ownership import (
    OwnershipDiscoveryCandidate,
    OwnershipForm,
    OwnershipParseError,
    normalize_ownership_form,
)
from kalki_market_intelligence.radar.sec_source import MASTER_INDEX_PATTERN, SecRadarDocument

MAXIMUM_OWNERSHIP_INDEX_ROWS = 5_000


class _GroupedIndexRow(NamedTuple):
    form: OwnershipForm
    filed_on: date
    identities: dict[str, str]


def parse_ownership_master_index(
    document: SecRadarDocument,
) -> tuple[OwnershipDiscoveryCandidate, ...]:
    """Select supported ownership rows without requiring a listed ticker mapping."""

    text = document.body.decode("latin-1")
    grouped: dict[str, _GroupedIndexRow] = {}
    conflicted: set[str] = set()
    selected_rows = 0
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) != 5:
            continue
        cik, company_name, raw_form, filed_on, filename = parts
        try:
            form = normalize_ownership_form(raw_form)
        except OwnershipParseError:
            continue
        match = MASTER_INDEX_PATTERN.fullmatch(filename)
        if match is None or match.group(1) != cik:
            continue
        try:
            filed_date = date.fromisoformat(filed_on)
        except ValueError:
            continue
        normalized_name = " ".join(company_name.split())[:255]
        if not normalized_name:
            continue
        selected_rows += 1
        if selected_rows > MAXIMUM_OWNERSHIP_INDEX_ROWS:
            raise OwnershipParseError("ownership daily-index rows exceed the safety boundary")
        accession = match.group(2)
        normalized_cik = cik.zfill(10)
        existing = grouped.get(accession)
        if existing is None:
            grouped[accession] = _GroupedIndexRow(
                form=form,
                filed_on=filed_date,
                identities={normalized_cik: normalized_name},
            )
            continue
        if existing.form != form or existing.filed_on != filed_date:
            conflicted.add(accession)
            continue
        prior_name = existing.identities.get(normalized_cik)
        if prior_name is not None and prior_name != normalized_name:
            conflicted.add(accession)
            continue
        existing.identities[normalized_cik] = normalized_name
    candidates: list[OwnershipDiscoveryCandidate] = []
    for accession, group in sorted(grouped.items()):
        if accession in conflicted:
            continue
        identities = tuple(sorted(group.identities.items()))
        candidates.append(
            OwnershipDiscoveryCandidate(
                accession_number=accession,
                index_ciks=tuple(item[0] for item in identities),
                index_names=tuple(item[1] for item in identities),
                form=group.form,
                filed_on=group.filed_on,
                discovered_at=document.retrieved_at,
                source_index_url=HttpUrl(document.url),
                source_index_sha256=document.content_sha256,
            )
        )
    return tuple(candidates)
