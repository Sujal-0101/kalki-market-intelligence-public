"""Deterministic freshness and event-lineage regressions."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5

import pytest
from pydantic import ValidationError
from pydantic.networks import HttpUrl

from kalki_market_intelligence.contracts.evidence import SourceClass
from kalki_market_intelligence.forensics.novelty import (
    EventDisclosure,
    EventDisclosureContext,
    EventEvidence,
    EventLineageReceipt,
    EventNoveltyDisposition,
    EventNoveltyReason,
    EventNumericFact,
    EventNumericKind,
    EventSourceReceipt,
    NumericComparator,
    classify_event_novelty,
    event_fingerprints,
    extract_strategic_partnership_disclosure,
)
from kalki_market_intelligence.radar.contracts import FilingCandidate
from kalki_market_intelligence.radar.extraction import extract_research_excerpt
from kalki_market_intelligence.radar.sec_source import SecRadarDocument
from kalki_market_intelligence.radar.worker import FilingRadarWorker

FIXTURES = Path(__file__).parent / "fixtures" / "novelty"
EVALUATED_AT = datetime(2026, 8, 30, 9, 50, tzinfo=UTC)


def _fixture(name: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((FIXTURES / name).read_text(encoding="utf-8")))


def _disclosure(name: str) -> EventDisclosure:
    fixture = _fixture(name)
    source = EventSourceReceipt(
        source_class=SourceClass(fixture["source_class"]),
        publisher=fixture["publisher"],
        canonical_url=fixture["canonical_url"],
        accession_number=fixture.get("accession_number"),
        source_content_sha256=fixture["source_content_sha256"],
        published_at=fixture["published_at"],
        available_at=fixture["available_at"],
        retrieved_at=fixture["retrieved_at"],
    )
    result = extract_strategic_partnership_disclosure(
        issuer_cik=fixture["issuer_cik"],
        issuer_name=fixture["issuer_name"],
        text=fixture["excerpt"],
        source=source,
        supported_event_dates=tuple(
            date.fromisoformat(item) for item in fixture["supported_event_dates"]
        ),
    )
    assert result is not None
    return result


def test_synthetic_later_disclosure_is_a_recap_not_a_fresh_catalyst() -> None:
    original = _disclosure("synthetic-original-partnership.json")
    later_filing = _disclosure("synthetic-later-partnership-recap.json")

    result = classify_event_novelty(
        later_filing,
        prior_disclosures=(original,),
        prior_search_complete=True,
        evaluated_at=EVALUATED_AT,
    )

    assert result.disposition is EventNoveltyDisposition.RECAP_EXISTING_EVENT
    assert result.reason is EventNoveltyReason.SAME_EVENT_NO_NEW_MATERIAL_FACT
    assert result.current_disclosure.source.source_class is SourceClass.SEC
    assert result.prior_related_disclosure == original
    assert result.current_disclosure.event_fingerprint == original.event_fingerprint
    assert result.current_disclosure.fact_fingerprint == original.fact_fingerprint
    assert result.authoritative_first_known_disclosure == original.source
    # The official IR page supplied a date but no precise publication timestamp.
    # Event lineage therefore preserves UNKNOWN instead of inventing midnight UTC.
    assert result.authoritative_first_known_at is None
    assert {item.display_name for item in original.entities} == {
        "Alder Capital",
        "Beacon Partners",
        "Cedar Infrastructure",
    }
    assert original.numeric_facts[0].value == Decimal("500000000000")
    assert original.numeric_facts[0].comparator is NumericComparator.GREATER_THAN


def test_synthetic_recap_evidence_is_removed_before_qwen() -> None:
    original = _disclosure("synthetic-original-partnership.json")
    fixture = _fixture("synthetic-later-partnership-recap.json")
    candidate = FilingCandidate(
        accession_number=fixture["accession_number"],
        cik=fixture["issuer_cik"],
        company_name=fixture["issuer_name"],
        ticker="EXMPL",
        exchange="Nasdaq",
        filing_form="8-K",
        filed_at=datetime(2026, 8, 26, tzinfo=UTC),
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/1/000000000126000001/0000000001-26-000001.txt"
        ),
        discovered_at=datetime(2026, 8, 27, tzinfo=UTC),
    )
    document = SecRadarDocument(
        url=candidate.source_url,
        body=fixture["excerpt"].encode(),
        content_sha256=fixture["source_content_sha256"],
        retrieved_at=EVALUATED_AT,
        media_type="text/html",
    )

    class Store:
        receipt: EventLineageReceipt | None = None

        def event_disclosures(self, **_: object) -> tuple[EventDisclosure, ...]:
            return (original,)

        def append_event_lineage(self, receipt: EventLineageReceipt) -> EventLineageReceipt:
            self.receipt = receipt
            return receipt

    store = Store()
    worker = object.__new__(FilingRadarWorker)
    cast(Any, worker)._store = store
    worker._now = lambda: EVALUATED_AT

    filtered = worker._apply_event_novelty(
        candidate,
        document,
        extract_research_excerpt(document.body),
    )

    assert store.receipt is not None
    assert store.receipt.disposition is EventNoveltyDisposition.RECAP_EXISTING_EVENT
    assert "Alder Capital" not in filtered.text
    assert "partnership" not in filtered.opportunity_terms
    assert not filtered.is_research_relevant


def test_same_document_is_duplicate_and_incomplete_search_is_unknown() -> None:
    current = _disclosure("synthetic-later-partnership-recap.json")

    duplicate = classify_event_novelty(
        current,
        prior_disclosures=(current,),
        prior_search_complete=True,
        evaluated_at=EVALUATED_AT,
    )
    unknown = classify_event_novelty(
        current,
        prior_disclosures=(),
        prior_search_complete=False,
        evaluated_at=EVALUATED_AT,
    )

    assert duplicate.disposition is EventNoveltyDisposition.DUPLICATE_DISCLOSURE
    assert unknown.disposition is EventNoveltyDisposition.UNKNOWN_NOVELTY
    assert unknown.reason is EventNoveltyReason.PRIOR_SEARCH_INCOMPLETE


def test_only_source_supported_new_material_fact_creates_update() -> None:
    """Synthetic contract case: the new term is explicit and source-bound."""

    previous = _disclosure("synthetic-original-partnership.json")
    current = _disclosure("synthetic-later-partnership-recap.json")
    quote = (
        "Synthetic contract fixture repeats the over USD 500 billion term and explicitly "
        "reports an additional USD 1 amount."
    )
    source_hash = sha256(quote.encode()).hexdigest()
    evidence_id = uuid5(NAMESPACE_URL, "synthetic-material-update-evidence")
    evidence = EventEvidence(
        evidence_id=evidence_id,
        quote=quote,
        source_content_sha256=source_hash,
    )
    added_fact = EventNumericFact(
        kind=EventNumericKind.AMOUNT,
        value=Decimal("1"),
        unit="USD",
        basis="synthetic additional committed amount",
        evidence_id=evidence_id,
    )
    repeated_fact = current.numeric_facts[0].model_copy(update={"evidence_id": evidence_id})
    numeric_facts = (repeated_fact, added_fact)
    event_hash, fact_hash = event_fingerprints(
        issuer_cik=current.issuer_cik,
        category=current.category,
        entities=current.entities,
        supported_event_dates=current.supported_event_dates,
        numeric_facts=numeric_facts,
    )
    source = EventSourceReceipt(
        source_class=SourceClass.OFFICIAL_RELEASE,
        publisher="Synthetic contract fixture",
        canonical_url=HttpUrl("https://example.invalid/material-update"),
        source_content_sha256=source_hash,
        published_at=EVALUATED_AT,
        available_at=EVALUATED_AT,
        retrieved_at=EVALUATED_AT,
    )
    update = current.model_copy(
        update={
            "disclosure_id": uuid5(
                NAMESPACE_URL,
                f"event-disclosure:{current.issuer_cik}:{source_hash}:{event_hash}",
            ),
            "numeric_facts": numeric_facts,
            "evidence": (evidence,),
            "source": source,
            "event_fingerprint": event_hash,
            "fact_fingerprint": fact_hash,
        }
    )
    update = EventDisclosure.model_validate(update.model_dump())

    result = classify_event_novelty(
        update,
        prior_disclosures=(previous,),
        prior_search_complete=True,
        evaluated_at=EVALUATED_AT,
    )

    assert result.disposition is EventNoveltyDisposition.MATERIAL_UPDATE
    assert result.reason is EventNoveltyReason.SUPPORTED_MATERIAL_FACT_CHANGED


def test_historical_context_does_not_depend_on_age_and_new_requires_complete_search() -> None:
    current = _disclosure("synthetic-later-partnership-recap.json")
    historical = EventDisclosure.model_validate(
        current.model_copy(
            update={"context": EventDisclosureContext.HISTORICAL_CONTEXT}
        ).model_dump()
    )

    result = classify_event_novelty(
        historical,
        prior_disclosures=(),
        prior_search_complete=False,
        evaluated_at=EVALUATED_AT,
    )
    new = classify_event_novelty(
        current,
        prior_disclosures=(),
        prior_search_complete=True,
        evaluated_at=EVALUATED_AT,
    )

    assert result.disposition is EventNoveltyDisposition.HISTORICAL_CONTEXT
    assert new.disposition is EventNoveltyDisposition.NEW_EVENT


def test_lineage_rejects_guessed_first_known_timestamp() -> None:
    original = _disclosure("synthetic-original-partnership.json")
    current = _disclosure("synthetic-later-partnership-recap.json")
    receipt = classify_event_novelty(
        current,
        prior_disclosures=(original,),
        prior_search_complete=True,
        evaluated_at=EVALUATED_AT,
    )

    with pytest.raises(ValidationError, match="unknown publication time"):
        EventLineageReceipt.model_validate(
            receipt.model_copy(update={"authoritative_first_known_at": EVALUATED_AT}).model_dump()
        )
