"""Closed, deterministic event-novelty contracts and comparison rules."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, HttpUrl, StringConstraints, model_validator

from kalki_market_intelligence.contracts.common import (
    ContractModel,
    NonEmptyText,
    Sha256Hex,
    ShortText,
    UtcDatetime,
)
from kalki_market_intelligence.contracts.evidence import SourceClass, quality_for_source_class
from kalki_market_intelligence.radar.contracts import AccessionNumber, CikText

EVENT_NOVELTY_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
EVENT_NOVELTY_RULE_VERSION: Literal["event-novelty-v1"] = "event-novelty-v1"
EVENT_EXTRACTOR_VERSION: Literal["strategic-partnership-v1"] = "strategic-partnership-v1"

type NormalizedEntityName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]


class EventNoveltyDisposition(StrEnum):
    """Closed event result; filing recency alone never selects one of these."""

    NEW_EVENT = "NEW_EVENT"
    MATERIAL_UPDATE = "MATERIAL_UPDATE"
    RECAP_EXISTING_EVENT = "RECAP_EXISTING_EVENT"
    DUPLICATE_DISCLOSURE = "DUPLICATE_DISCLOSURE"
    HISTORICAL_CONTEXT = "HISTORICAL_CONTEXT"
    UNKNOWN_NOVELTY = "UNKNOWN_NOVELTY"


class EventNoveltyReason(StrEnum):
    """Bounded proof selected by the deterministic comparison path."""

    COMPLETE_SEARCH_NO_RELATED_EVENT = "COMPLETE_SEARCH_NO_RELATED_EVENT"
    SUPPORTED_MATERIAL_FACT_CHANGED = "SUPPORTED_MATERIAL_FACT_CHANGED"
    SAME_EVENT_NO_NEW_MATERIAL_FACT = "SAME_EVENT_NO_NEW_MATERIAL_FACT"
    SAME_SOURCE_DOCUMENT = "SAME_SOURCE_DOCUMENT"
    EXPLICIT_HISTORICAL_CONTEXT = "EXPLICIT_HISTORICAL_CONTEXT"
    PRIOR_SEARCH_INCOMPLETE = "PRIOR_SEARCH_INCOMPLETE"
    AMBIGUOUS_EVENT_RELATIONSHIP = "AMBIGUOUS_EVENT_RELATIONSHIP"


class EventCategory(StrEnum):
    """Initial closed categories; unsupported event shapes remain unclassified."""

    STRATEGIC_PARTNERSHIP = "STRATEGIC_PARTNERSHIP"


class EventDisclosureContext(StrEnum):
    CURRENT_EVENT = "CURRENT_EVENT"
    HISTORICAL_CONTEXT = "HISTORICAL_CONTEXT"


class EventNumericKind(StrEnum):
    AMOUNT = "AMOUNT"
    PERCENTAGE = "PERCENTAGE"
    SHARE_COUNT = "SHARE_COUNT"


class NumericComparator(StrEnum):
    EXACT = "EXACT"
    GREATER_THAN = "GREATER_THAN"
    AT_LEAST = "AT_LEAST"
    UP_TO = "UP_TO"
    APPROXIMATELY = "APPROXIMATELY"


class EventEntity(ContractModel):
    """One source-stated entity plus its deterministic comparison key."""

    display_name: ShortText
    normalized_name: NormalizedEntityName

    @model_validator(mode="after")
    def normalized_value_matches_display_name(self) -> Self:
        if self.normalized_name != normalize_entity_name(self.display_name):
            raise ValueError("event entity normalized name is not deterministic")
        return self


class EventEvidence(ContractModel):
    """Bounded exact evidence tied to the complete source-document hash."""

    evidence_id: UUID
    quote: NonEmptyText = Field(max_length=2_000)
    source_content_sha256: Sha256Hex


class EventNumericFact(ContractModel):
    """One explicitly reported numeric term; no value is inferred or calculated."""

    kind: EventNumericKind
    value: Decimal = Field(gt=0, max_digits=30, decimal_places=8)
    unit: Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{1,31}$")]
    comparator: NumericComparator = NumericComparator.EXACT
    basis: ShortText
    evidence_id: UUID


class EventSourceReceipt(ContractModel):
    """Primary-source identity with optional historical publication knowledge."""

    source_class: SourceClass
    publisher: ShortText
    canonical_url: HttpUrl
    accession_number: AccessionNumber | None = None
    source_content_sha256: Sha256Hex
    published_at: UtcDatetime | None = None
    available_at: UtcDatetime | None = None
    retrieved_at: UtcDatetime

    @model_validator(mode="after")
    def source_is_primary_and_temporally_consistent(self) -> Self:
        if quality_for_source_class(self.source_class).value != "primary":
            raise ValueError("event lineage requires a primary source")
        if self.source_class is SourceClass.SEC and self.accession_number is None:
            raise ValueError("SEC event sources require an accession number")
        if self.available_at is not None:
            if self.published_at is not None and self.available_at < self.published_at:
                raise ValueError("event availability cannot precede publication")
            if self.retrieved_at < self.available_at:
                raise ValueError("event retrieval cannot precede availability")
        elif self.published_at is not None and self.retrieved_at < self.published_at:
            raise ValueError("event retrieval cannot precede publication")
        return self


class EventDisclosure(ContractModel):
    """One source-bound event assertion before comparison with prior history."""

    disclosure_id: UUID
    issuer_cik: CikText
    issuer_name: ShortText
    category: EventCategory
    context: EventDisclosureContext
    entities: tuple[EventEntity, ...] = Field(min_length=1, max_length=32)
    supported_event_dates: tuple[date, ...] = Field(default=(), max_length=8)
    numeric_facts: tuple[EventNumericFact, ...] = Field(default=(), max_length=24)
    evidence: tuple[EventEvidence, ...] = Field(min_length=1, max_length=16)
    source: EventSourceReceipt
    event_fingerprint: Sha256Hex
    fact_fingerprint: Sha256Hex
    extractor_version: Literal["strategic-partnership-v1"] = EVENT_EXTRACTOR_VERSION
    schema_version: Literal["1.0.0"] = EVENT_NOVELTY_SCHEMA_VERSION

    @model_validator(mode="after")
    def disclosure_is_closed_and_reproducible(self) -> Self:
        normalized_entities = tuple(item.normalized_name for item in self.entities)
        if len(set(normalized_entities)) != len(normalized_entities):
            raise ValueError("event entities must be unique")
        if normalized_entities != tuple(sorted(normalized_entities)):
            raise ValueError("event entities must use deterministic order")
        if len(set(self.supported_event_dates)) != len(self.supported_event_dates):
            raise ValueError("supported event dates must be unique")
        evidence_ids = {item.evidence_id for item in self.evidence}
        if len(evidence_ids) != len(self.evidence):
            raise ValueError("event evidence IDs must be unique")
        if any(
            item.source_content_sha256 != self.source.source_content_sha256
            for item in self.evidence
        ):
            raise ValueError("event evidence must match its complete source hash")
        if any(item.evidence_id not in evidence_ids for item in self.numeric_facts):
            raise ValueError("numeric event facts must cite retained evidence")
        expected_event, expected_fact = event_fingerprints(
            issuer_cik=self.issuer_cik,
            category=self.category,
            entities=self.entities,
            supported_event_dates=self.supported_event_dates,
            numeric_facts=self.numeric_facts,
        )
        if self.event_fingerprint != expected_event or self.fact_fingerprint != expected_fact:
            raise ValueError("event fingerprints are not reproducible from closed facts")
        expected_disclosure_id = uuid5(
            NAMESPACE_URL,
            f"event-disclosure:{self.issuer_cik.zfill(10)}:"
            f"{self.source.source_content_sha256}:{self.event_fingerprint}",
        )
        if self.disclosure_id != expected_disclosure_id:
            raise ValueError("event disclosure ID is not reproducible from source identity")
        return self


class EventLineageReceipt(ContractModel):
    """Append-only novelty decision for one current event disclosure."""

    lineage_id: UUID
    evaluated_at: UtcDatetime
    current_disclosure: EventDisclosure
    prior_related_disclosure: EventDisclosure | None = None
    authoritative_first_known_disclosure: EventSourceReceipt | None = None
    authoritative_first_known_at: UtcDatetime | None = None
    disposition: EventNoveltyDisposition
    reason: EventNoveltyReason
    prior_search_complete: bool
    rule_version: Literal["event-novelty-v1"] = EVENT_NOVELTY_RULE_VERSION
    schema_version: Literal["1.0.0"] = EVENT_NOVELTY_SCHEMA_VERSION

    @model_validator(mode="after")
    def decision_lineage_is_consistent(self) -> Self:
        expected_lineage_id = uuid5(
            NAMESPACE_URL,
            f"event-lineage:{self.current_disclosure.disclosure_id}:{EVENT_NOVELTY_RULE_VERSION}",
        )
        if self.lineage_id != expected_lineage_id:
            raise ValueError("event lineage ID is not reproducible from rule and disclosure")
        if self.authoritative_first_known_at is not None:
            if self.authoritative_first_known_disclosure is None:
                raise ValueError("first-known time requires its authoritative disclosure")
            if self.authoritative_first_known_disclosure.published_at is None:
                raise ValueError("unknown publication time cannot become first-known time")
            if (
                self.authoritative_first_known_at
                != self.authoritative_first_known_disclosure.published_at
            ):
                raise ValueError("first-known time must be source-supported, never guessed")
        expected = _REASON_BY_DISPOSITION[self.disposition]
        if self.reason not in expected:
            raise ValueError("event novelty reason does not match disposition")
        if (
            self.disposition
            in {
                EventNoveltyDisposition.MATERIAL_UPDATE,
                EventNoveltyDisposition.RECAP_EXISTING_EVENT,
                EventNoveltyDisposition.DUPLICATE_DISCLOSURE,
            }
            and self.prior_related_disclosure is None
        ):
            raise ValueError("related-event novelty requires the prior disclosure")
        if self.disposition is EventNoveltyDisposition.NEW_EVENT and not self.prior_search_complete:
            raise ValueError("new event requires a complete prior search")
        return self


_REASON_BY_DISPOSITION: dict[EventNoveltyDisposition, set[EventNoveltyReason]] = {
    EventNoveltyDisposition.NEW_EVENT: {
        EventNoveltyReason.COMPLETE_SEARCH_NO_RELATED_EVENT,
    },
    EventNoveltyDisposition.MATERIAL_UPDATE: {
        EventNoveltyReason.SUPPORTED_MATERIAL_FACT_CHANGED,
    },
    EventNoveltyDisposition.RECAP_EXISTING_EVENT: {
        EventNoveltyReason.SAME_EVENT_NO_NEW_MATERIAL_FACT,
    },
    EventNoveltyDisposition.DUPLICATE_DISCLOSURE: {
        EventNoveltyReason.SAME_SOURCE_DOCUMENT,
    },
    EventNoveltyDisposition.HISTORICAL_CONTEXT: {
        EventNoveltyReason.EXPLICIT_HISTORICAL_CONTEXT,
    },
    EventNoveltyDisposition.UNKNOWN_NOVELTY: {
        EventNoveltyReason.PRIOR_SEARCH_INCOMPLETE,
        EventNoveltyReason.AMBIGUOUS_EVENT_RELATIONSHIP,
    },
}


def normalize_entity_name(value: str) -> str:
    """Create a conservative comparison key without guessing corporate identity."""

    normalized = unicodedata.normalize("NFKC", value)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized.casefold())
    return " ".join(normalized.split())


def event_fingerprints(
    *,
    issuer_cik: str,
    category: EventCategory,
    entities: tuple[EventEntity, ...],
    supported_event_dates: tuple[date, ...],
    numeric_facts: tuple[EventNumericFact, ...],
) -> tuple[str, str]:
    """Hash event identity separately from its versioned material facts."""

    core = {
        "issuer_cik": issuer_cik.zfill(10),
        "category": category.value,
        "entities": [item.normalized_name for item in entities],
    }
    facts = {
        **core,
        "supported_event_dates": [item.isoformat() for item in sorted(supported_event_dates)],
        "numeric_facts": sorted(
            (
                item.kind.value,
                format(item.value, "f"),
                item.unit,
                item.comparator.value,
                item.basis,
            )
            for item in numeric_facts
        ),
    }
    return _canonical_hash(core), _canonical_hash(facts)


def classify_event_novelty(
    current: EventDisclosure,
    *,
    prior_disclosures: tuple[EventDisclosure, ...],
    prior_search_complete: bool,
    evaluated_at: UtcDatetime,
) -> EventLineageReceipt:
    """Compare closed facts; absence is evidence only after a complete search."""

    if current.context is EventDisclosureContext.HISTORICAL_CONTEXT:
        return _lineage(
            current,
            evaluated_at=evaluated_at,
            prior=None,
            first=None,
            disposition=EventNoveltyDisposition.HISTORICAL_CONTEXT,
            reason=EventNoveltyReason.EXPLICIT_HISTORICAL_CONTEXT,
            prior_search_complete=prior_search_complete,
        )
    exact_source = next(
        (
            item
            for item in prior_disclosures
            if item.source.source_content_sha256 == current.source.source_content_sha256
            and item.event_fingerprint == current.event_fingerprint
        ),
        None,
    )
    if exact_source is not None:
        return _lineage(
            current,
            evaluated_at=evaluated_at,
            prior=exact_source,
            first=_first_known(prior_disclosures),
            disposition=EventNoveltyDisposition.DUPLICATE_DISCLOSURE,
            reason=EventNoveltyReason.SAME_SOURCE_DOCUMENT,
            prior_search_complete=prior_search_complete,
        )
    related = tuple(item for item in prior_disclosures if _events_are_related(item, current))
    if related:
        prior = sorted(related, key=_source_order_key)[-1]
        if _has_new_material_facts(prior, current):
            disposition = EventNoveltyDisposition.MATERIAL_UPDATE
            reason = EventNoveltyReason.SUPPORTED_MATERIAL_FACT_CHANGED
        else:
            disposition = EventNoveltyDisposition.RECAP_EXISTING_EVENT
            reason = EventNoveltyReason.SAME_EVENT_NO_NEW_MATERIAL_FACT
        return _lineage(
            current,
            evaluated_at=evaluated_at,
            prior=prior,
            first=_first_known(related),
            disposition=disposition,
            reason=reason,
            prior_search_complete=prior_search_complete,
        )
    if any(_events_overlap_ambiguously(item, current) for item in prior_disclosures):
        return _lineage(
            current,
            evaluated_at=evaluated_at,
            prior=None,
            first=None,
            disposition=EventNoveltyDisposition.UNKNOWN_NOVELTY,
            reason=EventNoveltyReason.AMBIGUOUS_EVENT_RELATIONSHIP,
            prior_search_complete=prior_search_complete,
        )
    if prior_search_complete:
        return _lineage(
            current,
            evaluated_at=evaluated_at,
            prior=None,
            first=None,
            disposition=EventNoveltyDisposition.NEW_EVENT,
            reason=EventNoveltyReason.COMPLETE_SEARCH_NO_RELATED_EVENT,
            prior_search_complete=True,
        )
    return _lineage(
        current,
        evaluated_at=evaluated_at,
        prior=None,
        first=None,
        disposition=EventNoveltyDisposition.UNKNOWN_NOVELTY,
        reason=EventNoveltyReason.PRIOR_SEARCH_INCOMPLETE,
        prior_search_complete=False,
    )


_PARTNERSHIP_ENTITIES = re.compile(
    r"\bwith\s+(?P<entities>.{3,500}?)\s+to\s+"
    r"(?:mobilize|raise|deploy|establish|create|build|finance)\b",
    re.IGNORECASE,
)
_MONEY = re.compile(
    r"(?P<comparator>over|more than|at least|up to|approximately)?\s*"
    r"\$\s*(?P<value>\d[\d,.]*)\s*(?P<scale>million|billion|trillion)?\b",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"[^.!?]*(?:partnership|partnerships)[^.!?]*(?:[.!?]|$)", re.IGNORECASE)


def extract_strategic_partnership_disclosure(
    *,
    issuer_cik: str,
    issuer_name: str,
    text: str,
    source: EventSourceReceipt,
    supported_event_dates: tuple[date, ...] = (),
    context: EventDisclosureContext = EventDisclosureContext.CURRENT_EVENT,
) -> EventDisclosure | None:
    """Extract only explicit partnership/entity grammar; ambiguous text stays unsupported."""

    matches = tuple(_SENTENCE.finditer(" ".join(text.split())))
    candidates: list[tuple[str, tuple[str, ...], re.Match[str] | None]] = []
    for sentence_match in matches:
        sentence = sentence_match.group(0).strip()
        entity_match = _PARTNERSHIP_ENTITIES.search(sentence)
        if entity_match is None:
            continue
        names = _split_entities(entity_match.group("entities"))
        if len(names) < 2:
            continue
        candidates.append((sentence, names, _MONEY.search(sentence)))
    if len(candidates) != 1:
        return None
    quote, names, money_match = candidates[0]
    evidence_id = uuid5(
        NAMESPACE_URL,
        f"event-evidence:{source.source_content_sha256}:{sha256(quote.encode()).hexdigest()}",
    )
    evidence = (
        EventEvidence(
            evidence_id=evidence_id,
            quote=quote,
            source_content_sha256=source.source_content_sha256,
        ),
    )
    numeric_facts: tuple[EventNumericFact, ...] = ()
    if money_match is not None:
        numeric_facts = (
            EventNumericFact(
                kind=EventNumericKind.AMOUNT,
                value=_scaled_decimal(money_match.group("value"), money_match.group("scale")),
                unit="USD",
                comparator=_comparator(money_match.group("comparator")),
                basis="third-party capital"
                if "third-party capital" in quote.casefold()
                else "amount",
                evidence_id=evidence_id,
            ),
        )
    entities = tuple(
        sorted(
            (
                EventEntity(display_name=name, normalized_name=normalize_entity_name(name))
                for name in names
            ),
            key=lambda item: item.normalized_name,
        )
    )
    event_hash, fact_hash = event_fingerprints(
        issuer_cik=issuer_cik,
        category=EventCategory.STRATEGIC_PARTNERSHIP,
        entities=entities,
        supported_event_dates=supported_event_dates,
        numeric_facts=numeric_facts,
    )
    return EventDisclosure(
        disclosure_id=uuid5(
            NAMESPACE_URL,
            f"event-disclosure:{issuer_cik.zfill(10)}:{source.source_content_sha256}:{event_hash}",
        ),
        issuer_cik=issuer_cik.zfill(10),
        issuer_name=issuer_name,
        category=EventCategory.STRATEGIC_PARTNERSHIP,
        context=context,
        entities=entities,
        supported_event_dates=tuple(sorted(supported_event_dates)),
        numeric_facts=numeric_facts,
        evidence=evidence,
        source=source,
        event_fingerprint=event_hash,
        fact_fingerprint=fact_hash,
    )


def _lineage(
    current: EventDisclosure,
    *,
    evaluated_at: UtcDatetime,
    prior: EventDisclosure | None,
    first: EventDisclosure | None,
    disposition: EventNoveltyDisposition,
    reason: EventNoveltyReason,
    prior_search_complete: bool,
) -> EventLineageReceipt:
    first_source = first.source if first is not None else None
    first_known_at = first_source.published_at if first_source is not None else None
    return EventLineageReceipt(
        lineage_id=uuid5(
            NAMESPACE_URL,
            f"event-lineage:{current.disclosure_id}:{EVENT_NOVELTY_RULE_VERSION}",
        ),
        evaluated_at=evaluated_at,
        current_disclosure=current,
        prior_related_disclosure=prior,
        authoritative_first_known_disclosure=first_source,
        authoritative_first_known_at=first_known_at,
        disposition=disposition,
        reason=reason,
        prior_search_complete=prior_search_complete,
    )


def _events_are_related(previous: EventDisclosure, current: EventDisclosure) -> bool:
    if previous.issuer_cik != current.issuer_cik or previous.category is not current.category:
        return False
    if previous.event_fingerprint == current.event_fingerprint:
        return True
    before = {item.normalized_name for item in previous.entities}
    after = {item.normalized_name for item in current.entities}
    return bool(before and after and before < after)


def _events_overlap_ambiguously(previous: EventDisclosure, current: EventDisclosure) -> bool:
    if previous.issuer_cik != current.issuer_cik or previous.category is not current.category:
        return False
    before = {item.normalized_name for item in previous.entities}
    after = {item.normalized_name for item in current.entities}
    return bool(before & after)


def _has_new_material_facts(previous: EventDisclosure, current: EventDisclosure) -> bool:
    previous_entities = {item.normalized_name for item in previous.entities}
    current_entities = {item.normalized_name for item in current.entities}
    if current_entities - previous_entities:
        return True
    previous_dates = set(previous.supported_event_dates)
    if set(current.supported_event_dates) - previous_dates:
        return True
    previous_facts = {_numeric_fact_key(item) for item in previous.numeric_facts}
    current_facts = {_numeric_fact_key(item) for item in current.numeric_facts}
    return bool(current_facts - previous_facts)


def _numeric_fact_key(item: EventNumericFact) -> tuple[str, str, str, str, str]:
    return (
        item.kind.value,
        format(item.value, "f"),
        item.unit,
        item.comparator.value,
        item.basis,
    )


def _first_known(disclosures: tuple[EventDisclosure, ...]) -> EventDisclosure | None:
    if not disclosures:
        return None
    if len(disclosures) == 1:
        return disclosures[0]
    if any(item.source.published_at is None for item in disclosures):
        return None
    return min(disclosures, key=_source_order_key)


def _source_order_key(disclosure: EventDisclosure) -> tuple[str, str]:
    published = disclosure.source.published_at
    return (
        published.isoformat()
        if published is not None
        else disclosure.source.retrieved_at.isoformat(),
        str(disclosure.disclosure_id),
    )


def _split_entities(value: str) -> tuple[str, ...]:
    cleaned = re.sub(
        r"^(?:the\s+)?(?:strategic\s+)?(?:partnerships?\s+)?",
        "",
        value.strip(),
        flags=re.IGNORECASE,
    )
    parts = re.split(r"\s*,\s*|\s+and\s+", cleaned)
    result = tuple(item.strip(" ,") for item in parts if item.strip(" ,"))
    if any(len(item) > 255 for item in result):
        return ()
    return tuple(dict.fromkeys(result))


def _scaled_decimal(value: str, scale: str | None) -> Decimal:
    multipliers = {
        None: Decimal(1),
        "million": Decimal(1_000_000),
        "billion": Decimal(1_000_000_000),
        "trillion": Decimal(1_000_000_000_000),
    }
    return Decimal(value.replace(",", "")) * multipliers[scale.casefold() if scale else None]


def _comparator(value: str | None) -> NumericComparator:
    return {
        None: NumericComparator.EXACT,
        "over": NumericComparator.GREATER_THAN,
        "more than": NumericComparator.GREATER_THAN,
        "at least": NumericComparator.AT_LEAST,
        "up to": NumericComparator.UP_TO,
        "approximately": NumericComparator.APPROXIMATELY,
    }[value.casefold() if value else None]


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(encoded.encode()).hexdigest()
