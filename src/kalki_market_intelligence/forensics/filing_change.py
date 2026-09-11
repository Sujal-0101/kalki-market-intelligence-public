"""Versioned, provenance-bound filing-change selection before optional inference."""

from __future__ import annotations

import json
from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, StringConstraints, model_validator

from kalki_market_intelligence.contracts.common import (
    ContractModel,
    Sha256Hex,
    UtcDatetime,
    normalize_utc,
)
from kalki_market_intelligence.radar.contracts import AccessionNumber, CikText, SourceUrl

FILING_CHANGE_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
FILING_CHANGE_EXTRACTION_VERSION: Literal["filing-change-sections-v1"] = "filing-change-sections-v1"
FILING_CHANGE_SELECTION_VERSION: Literal["filing-change-selection-v1"] = (
    "filing-change-selection-v1"
)
MAXIMUM_CHANGED_SECTIONS = 128
MAXIMUM_SELECTED_CHANGES = 6
MAXIMUM_SELECTED_CHARACTERS = 3_600
MAXIMUM_EXCERPT_CHARACTERS = 600

type SectionSelector = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]
type SectionHeading = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]
type SectionText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)
]


class FilingChangeForm(StrEnum):
    FORM_10_K = "10-K"
    FORM_10_K_AMENDMENT = "10-K/A"
    FORM_10_Q = "10-Q"
    FORM_10_Q_AMENDMENT = "10-Q/A"
    FORM_S_1 = "S-1"
    FORM_S_1_AMENDMENT = "S-1/A"
    FORM_S_3 = "S-3"
    FORM_S_3_AMENDMENT = "S-3/A"
    FORM_424_B_2 = "424B2"
    FORM_424_B_3 = "424B3"
    FORM_424_B_4 = "424B4"
    FORM_424_B_5 = "424B5"
    FORM_424_B_7 = "424B7"
    FORM_424_B_8 = "424B8"
    FORM_424_H = "424H"
    FORM_FWP = "FWP"


class FilingChangeRelationship(StrEnum):
    AMENDMENT_OF = "amendment_of"
    SUCCESSIVE_PERIODIC_REPORT = "successive_periodic_report"
    PROSPECTUS_UPDATE = "prospectus_update"


class FilingChangeCategory(StrEnum):
    LIQUIDITY = "liquidity"
    RISKS = "risks"
    GOING_CONCERN = "going_concern"
    DEBT = "debt"
    ISSUANCE = "issuance"
    LITIGATION = "litigation"
    CONTROLS = "controls"
    OUTLOOK = "outlook"


class FilingChangeKind(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"


class FilingChangeSection(ContractModel):
    """One normalized relevant section tied to its exact text hash."""

    selector: SectionSelector
    heading: SectionHeading
    category: FilingChangeCategory
    normalized_start: int = Field(ge=0, le=50_000_000)
    normalized_end: int = Field(gt=0, le=50_000_000)
    text: SectionText
    text_sha256: Sha256Hex

    @model_validator(mode="after")
    def text_is_canonical_and_hashed(self) -> Self:
        if self.text != _normalize_text(self.text):
            raise ValueError("filing-change section text must use canonical whitespace")
        if self.normalized_end - self.normalized_start != len(self.text):
            raise ValueError("filing-change section range does not reconcile")
        if self.text_sha256 != _text_sha256(self.text):
            raise ValueError("filing-change section hash does not reconcile")
        return self


class FilingChangeSnapshot(ContractModel):
    """Comparable SEC filing sections with knowledge-time provenance."""

    accession_number: AccessionNumber
    cik: CikText
    filing_form: FilingChangeForm
    filed_at: UtcDatetime
    available_at: UtcDatetime
    retrieved_at: UtcDatetime
    source_url: SourceUrl
    source_content_sha256: Sha256Hex
    normalized_visible_sha256: Sha256Hex
    sections: tuple[FilingChangeSection, ...] = Field(min_length=1, max_length=64)
    manifest_sha256: Sha256Hex
    extraction_version: Literal["filing-change-sections-v1"] = FILING_CHANGE_EXTRACTION_VERSION
    schema_version: Literal["1.0.0"] = FILING_CHANGE_SCHEMA_VERSION

    @model_validator(mode="after")
    def snapshot_reconciles(self) -> Self:
        if self.available_at < self.filed_at:
            raise ValueError("filing availability cannot precede filing time")
        if self.retrieved_at < self.available_at:
            raise ValueError("filing retrieval cannot precede availability")
        selectors = tuple(section.selector for section in self.sections)
        if selectors != tuple(sorted(set(selectors))):
            raise ValueError("filing-change sections must use unique canonical selector order")
        expected_cik_path = f"/Archives/edgar/data/{int(self.cik)}/"
        if expected_cik_path not in self.source_url:
            raise ValueError("filing-change source URL does not match its canonical CIK")
        nested_accession = f"/{self.accession_number.replace('-', '')}/"
        flat_submission = f"/{self.accession_number}.txt"
        if nested_accession not in self.source_url and not self.source_url.endswith(
            flat_submission
        ):
            raise ValueError("filing-change source URL does not match its accession")
        if self.manifest_sha256 != _snapshot_manifest_sha256(self):
            raise ValueError("filing-change snapshot manifest does not reconcile")
        return self


class FilingSectionChange(ContractModel):
    """Content-free section delta retaining both source-side identities."""

    selector: SectionSelector
    heading: SectionHeading
    category: FilingChangeCategory
    kind: FilingChangeKind
    previous_text_sha256: Sha256Hex | None = None
    previous_characters: int = Field(default=0, ge=0, le=20_000)
    current_text_sha256: Sha256Hex | None = None
    current_characters: int = Field(default=0, ge=0, le=20_000)

    @model_validator(mode="after")
    def sides_reconcile(self) -> Self:
        previous_present = self.previous_text_sha256 is not None
        current_present = self.current_text_sha256 is not None
        if previous_present != bool(self.previous_characters):
            raise ValueError("previous section hash and size must be present together")
        if current_present != bool(self.current_characters):
            raise ValueError("current section hash and size must be present together")
        expected = {
            FilingChangeKind.ADDED: (False, True),
            FilingChangeKind.REMOVED: (True, False),
            FilingChangeKind.MODIFIED: (True, True),
        }[self.kind]
        if (previous_present, current_present) != expected:
            raise ValueError("filing section sides do not match the change kind")
        return self


class FilingChangeExcerpt(ContractModel):
    """Exact bounded before/after ranges selected from one changed section."""

    selector: SectionSelector
    heading: SectionHeading
    category: FilingChangeCategory
    kind: FilingChangeKind
    previous_start: int | None = Field(default=None, ge=0, le=20_000)
    previous_end: int | None = Field(default=None, gt=0, le=20_000)
    previous_text: str = Field(default="", max_length=MAXIMUM_EXCERPT_CHARACTERS)
    previous_text_sha256: Sha256Hex | None = None
    current_start: int | None = Field(default=None, ge=0, le=20_000)
    current_end: int | None = Field(default=None, gt=0, le=20_000)
    current_text: str = Field(default="", max_length=MAXIMUM_EXCERPT_CHARACTERS)
    current_text_sha256: Sha256Hex | None = None

    @model_validator(mode="after")
    def exact_ranges_reconcile(self) -> Self:
        _validate_excerpt_side(
            self.previous_start,
            self.previous_end,
            self.previous_text,
            self.previous_text_sha256,
            side="previous",
        )
        _validate_excerpt_side(
            self.current_start,
            self.current_end,
            self.current_text,
            self.current_text_sha256,
            side="current",
        )
        expected = {
            FilingChangeKind.ADDED: (False, True),
            FilingChangeKind.REMOVED: (True, False),
            FilingChangeKind.MODIFIED: (True, True),
        }[self.kind]
        if (bool(self.previous_text), bool(self.current_text)) != expected:
            raise ValueError("filing excerpt sides do not match the change kind")
        if len(self.previous_text) + len(self.current_text) > MAXIMUM_EXCERPT_CHARACTERS:
            raise ValueError("filing-change excerpt exceeds its per-change budget")
        return self


class FilingChangeSelectionReceipt(ContractModel):
    """Deterministic diff and bounded evidence package; it contains no model output."""

    receipt_id: UUID
    relationship: FilingChangeRelationship
    previous_accession_number: AccessionNumber
    current_accession_number: AccessionNumber
    previous_manifest_sha256: Sha256Hex
    current_manifest_sha256: Sha256Hex
    changes: tuple[FilingSectionChange, ...] = Field(max_length=MAXIMUM_CHANGED_SECTIONS)
    selected_excerpts: tuple[FilingChangeExcerpt, ...] = Field(max_length=MAXIMUM_SELECTED_CHANGES)
    omitted_selectors: tuple[SectionSelector, ...] = Field(default=(), max_length=128)
    selected_characters: int = Field(ge=0, le=MAXIMUM_SELECTED_CHARACTERS)
    selection_sha256: Sha256Hex
    extraction_version: Literal["filing-change-sections-v1"] = FILING_CHANGE_EXTRACTION_VERSION
    selection_version: Literal["filing-change-selection-v1"] = FILING_CHANGE_SELECTION_VERSION
    schema_version: Literal["1.0.0"] = FILING_CHANGE_SCHEMA_VERSION

    @model_validator(mode="after")
    def receipt_reconciles(self) -> Self:
        change_selectors = tuple(change.selector for change in self.changes)
        if change_selectors != tuple(sorted(set(change_selectors))):
            raise ValueError("filing changes must use unique canonical selector order")
        selected = tuple(item.selector for item in self.selected_excerpts)
        if len(set(selected)) != len(selected):
            raise ValueError("selected filing-change excerpts must be unique")
        if self.omitted_selectors != tuple(sorted(set(self.omitted_selectors))):
            raise ValueError("omitted selectors must use unique canonical order")
        if set(selected) & set(self.omitted_selectors):
            raise ValueError("selected and omitted filing-change selectors must be disjoint")
        if set(selected) | set(self.omitted_selectors) != set(change_selectors):
            raise ValueError("selected and omitted selectors must partition all changes")
        expected_characters = sum(
            len(item.previous_text) + len(item.current_text) for item in self.selected_excerpts
        )
        if self.selected_characters != expected_characters:
            raise ValueError("selected filing-change character count does not reconcile")
        if self.selection_sha256 != _selection_sha256(self):
            raise ValueError("filing-change selection hash does not reconcile")
        expected_id = uuid5(NAMESPACE_URL, f"kalki:filing-change:{self.selection_sha256}")
        if self.receipt_id != expected_id:
            raise ValueError("filing-change receipt identity does not reconcile")
        return self


def build_filing_change_section(
    *,
    selector: str,
    heading: str,
    category: FilingChangeCategory,
    text: str,
    normalized_start: int = 0,
) -> FilingChangeSection:
    normalized = _normalize_text(text)
    return FilingChangeSection(
        selector=selector,
        heading=heading,
        category=category,
        normalized_start=normalized_start,
        normalized_end=normalized_start + len(normalized),
        text=normalized,
        text_sha256=_text_sha256(normalized),
    )


def build_filing_change_snapshot(
    *,
    accession_number: str,
    cik: str,
    filing_form: FilingChangeForm,
    filed_at: UtcDatetime,
    available_at: UtcDatetime,
    retrieved_at: UtcDatetime,
    source_url: str,
    source_content_sha256: Sha256Hex,
    normalized_visible_sha256: Sha256Hex,
    sections: tuple[FilingChangeSection, ...],
) -> FilingChangeSnapshot:
    ordered = tuple(sorted(sections, key=lambda item: item.selector))
    normalized_filed_at = normalize_utc(filed_at)
    normalized_available_at = normalize_utc(available_at)
    normalized_retrieved_at = normalize_utc(retrieved_at)
    provisional = FilingChangeSnapshot.model_construct(
        accession_number=accession_number,
        cik=cik,
        filing_form=filing_form,
        filed_at=normalized_filed_at,
        available_at=normalized_available_at,
        retrieved_at=normalized_retrieved_at,
        source_url=source_url,
        source_content_sha256=source_content_sha256,
        normalized_visible_sha256=normalized_visible_sha256,
        sections=ordered,
        manifest_sha256="0" * 64,
    )
    return FilingChangeSnapshot(
        accession_number=accession_number,
        cik=cik,
        filing_form=filing_form,
        filed_at=normalized_filed_at,
        available_at=normalized_available_at,
        retrieved_at=normalized_retrieved_at,
        source_url=source_url,
        source_content_sha256=source_content_sha256,
        normalized_visible_sha256=normalized_visible_sha256,
        sections=ordered,
        manifest_sha256=_snapshot_manifest_sha256(provisional),
    )


def compare_and_select_filing_changes(
    previous: FilingChangeSnapshot,
    current: FilingChangeSnapshot,
    *,
    relationship: FilingChangeRelationship,
) -> FilingChangeSelectionReceipt:
    """Compare two admissible snapshots and select exact changed evidence deterministically."""

    _validate_relationship(previous, current, relationship)
    previous_by_selector = {item.selector: item for item in previous.sections}
    current_by_selector = {item.selector: item for item in current.sections}
    changes: list[FilingSectionChange] = []
    excerpts_by_selector: dict[str, FilingChangeExcerpt] = {}
    for selector in sorted(set(previous_by_selector) | set(current_by_selector)):
        before = previous_by_selector.get(selector)
        after = current_by_selector.get(selector)
        if before is not None and after is not None:
            if before.category is not after.category:
                raise ValueError("a canonical section selector cannot change category")
            if before.text_sha256 == after.text_sha256:
                continue
            kind = FilingChangeKind.MODIFIED
        elif before is None:
            kind = FilingChangeKind.ADDED
        else:
            kind = FilingChangeKind.REMOVED
        reference = after or before
        assert reference is not None
        changes.append(
            FilingSectionChange(
                selector=selector,
                heading=reference.heading,
                category=reference.category,
                kind=kind,
                previous_text_sha256=before.text_sha256 if before else None,
                previous_characters=len(before.text) if before else 0,
                current_text_sha256=after.text_sha256 if after else None,
                current_characters=len(after.text) if after else 0,
            )
        )
        excerpts_by_selector[selector] = _build_excerpt(before, after, kind=kind)

    ordered_changes = tuple(sorted(changes, key=lambda item: item.selector))
    selection_order = sorted(
        ordered_changes,
        key=lambda item: (_CATEGORY_ORDER[item.category], item.selector),
    )
    selected_changes = selection_order[:MAXIMUM_SELECTED_CHANGES]
    selected_excerpts = tuple(excerpts_by_selector[item.selector] for item in selected_changes)
    selected_selectors = {item.selector for item in selected_changes}
    omitted = tuple(
        item.selector for item in ordered_changes if item.selector not in selected_selectors
    )
    selected_characters = sum(
        len(item.previous_text) + len(item.current_text) for item in selected_excerpts
    )
    provisional = FilingChangeSelectionReceipt.model_construct(
        receipt_id=UUID(int=0),
        relationship=relationship,
        previous_accession_number=previous.accession_number,
        current_accession_number=current.accession_number,
        previous_manifest_sha256=previous.manifest_sha256,
        current_manifest_sha256=current.manifest_sha256,
        changes=ordered_changes,
        selected_excerpts=selected_excerpts,
        omitted_selectors=omitted,
        selected_characters=selected_characters,
        selection_sha256="0" * 64,
    )
    selection_sha256 = _selection_sha256(provisional)
    return FilingChangeSelectionReceipt(
        receipt_id=uuid5(NAMESPACE_URL, f"kalki:filing-change:{selection_sha256}"),
        relationship=relationship,
        previous_accession_number=previous.accession_number,
        current_accession_number=current.accession_number,
        previous_manifest_sha256=previous.manifest_sha256,
        current_manifest_sha256=current.manifest_sha256,
        changes=ordered_changes,
        selected_excerpts=selected_excerpts,
        omitted_selectors=omitted,
        selected_characters=selected_characters,
        selection_sha256=selection_sha256,
    )


_CATEGORY_ORDER = {category: index for index, category in enumerate(FilingChangeCategory)}
_PERIODIC_FORMS = {FilingChangeForm.FORM_10_K, FilingChangeForm.FORM_10_Q}
_PROSPECTUS_FORMS = {
    FilingChangeForm.FORM_S_1,
    FilingChangeForm.FORM_S_1_AMENDMENT,
    FilingChangeForm.FORM_S_3,
    FilingChangeForm.FORM_S_3_AMENDMENT,
    FilingChangeForm.FORM_424_B_2,
    FilingChangeForm.FORM_424_B_3,
    FilingChangeForm.FORM_424_B_4,
    FilingChangeForm.FORM_424_B_5,
    FilingChangeForm.FORM_424_B_7,
    FilingChangeForm.FORM_424_B_8,
    FilingChangeForm.FORM_424_H,
    FilingChangeForm.FORM_FWP,
}


def _validate_relationship(
    previous: FilingChangeSnapshot,
    current: FilingChangeSnapshot,
    relationship: FilingChangeRelationship,
) -> None:
    if previous.cik != current.cik:
        raise ValueError("filing changes require the same canonical CIK")
    if previous.accession_number == current.accession_number:
        raise ValueError("filing changes require distinct accessions")
    if current.available_at <= previous.available_at:
        raise ValueError("current filing must become available after the prior filing")
    if current.retrieved_at < previous.retrieved_at:
        raise ValueError("comparison cannot use a prior filing retrieved after the current cutoff")
    if current.filed_at < previous.filed_at:
        raise ValueError("current filing date cannot precede the prior filing date")
    if previous.extraction_version != current.extraction_version:
        raise ValueError("filing-change extraction versions must match")
    if relationship is FilingChangeRelationship.AMENDMENT_OF:
        if not current.filing_form.value.endswith("/A"):
            raise ValueError("amendment relationship requires an amendment form")
        if current.filing_form.value.removesuffix("/A") != previous.filing_form.value.removesuffix(
            "/A"
        ):
            raise ValueError("amendment and prior form families must match")
        if previous.filing_form.value.endswith("/A"):
            raise ValueError("amendment relationship requires a non-amended prior filing")
    elif relationship is FilingChangeRelationship.SUCCESSIVE_PERIODIC_REPORT:
        if (
            previous.filing_form not in _PERIODIC_FORMS
            or current.filing_form != previous.filing_form
        ):
            raise ValueError("successive periodic comparison requires matching 10-K or 10-Q forms")
    elif (
        previous.filing_form not in _PROSPECTUS_FORMS
        or current.filing_form not in _PROSPECTUS_FORMS
    ):
        raise ValueError("prospectus update requires two supported prospectus forms")


def _build_excerpt(
    before: FilingChangeSection | None,
    after: FilingChangeSection | None,
    *,
    kind: FilingChangeKind,
) -> FilingChangeExcerpt:
    reference = after or before
    assert reference is not None
    previous_range: tuple[int, int] | None = None
    current_range: tuple[int, int] | None = None
    if before is not None and after is not None:
        difference_at = _first_difference(before.text, after.text)
        previous_range = _centered_range(
            before.text, difference_at, MAXIMUM_EXCERPT_CHARACTERS // 2
        )
        current_range = _centered_range(after.text, difference_at, MAXIMUM_EXCERPT_CHARACTERS // 2)
    elif before is not None:
        previous_range = (0, min(len(before.text), MAXIMUM_EXCERPT_CHARACTERS))
    elif after is not None:
        current_range = (0, min(len(after.text), MAXIMUM_EXCERPT_CHARACTERS))
    previous_text = before.text[slice(*previous_range)] if before and previous_range else ""
    current_text = after.text[slice(*current_range)] if after and current_range else ""
    return FilingChangeExcerpt(
        selector=reference.selector,
        heading=reference.heading,
        category=reference.category,
        kind=kind,
        previous_start=previous_range[0] if previous_range else None,
        previous_end=previous_range[1] if previous_range else None,
        previous_text=previous_text,
        previous_text_sha256=_text_sha256(previous_text) if previous_text else None,
        current_start=current_range[0] if current_range else None,
        current_end=current_range[1] if current_range else None,
        current_text=current_text,
        current_text_sha256=_text_sha256(current_text) if current_text else None,
    )


def _first_difference(previous: str, current: str) -> int:
    shared = min(len(previous), len(current))
    for index in range(shared):
        if previous[index] != current[index]:
            return index
    return shared


def _centered_range(text: str, center: int, size: int) -> tuple[int, int]:
    start = max(0, center - size // 2)
    end = min(len(text), start + size)
    start = max(0, end - size)
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _validate_excerpt_side(
    start: int | None,
    end: int | None,
    text: str,
    text_sha256: str | None,
    *,
    side: str,
) -> None:
    present = bool(text)
    if present != all(value is not None for value in (start, end, text_sha256)):
        raise ValueError(f"{side} excerpt range, text and hash must be present together")
    if not present:
        return
    assert start is not None and end is not None and text_sha256 is not None
    if end - start != len(text):
        raise ValueError(f"{side} excerpt range does not reconcile to its text")
    if text_sha256 != _text_sha256(text):
        raise ValueError(f"{side} excerpt hash does not reconcile")


def _snapshot_manifest_sha256(snapshot: FilingChangeSnapshot) -> str:
    return _canonical_sha256(
        {
            "accession_number": snapshot.accession_number,
            "available_at": normalize_utc(snapshot.available_at).isoformat(),
            "cik": snapshot.cik,
            "extraction_version": snapshot.extraction_version,
            "filed_at": normalize_utc(snapshot.filed_at).isoformat(),
            "filing_form": snapshot.filing_form.value,
            "retrieved_at": normalize_utc(snapshot.retrieved_at).isoformat(),
            "schema_version": snapshot.schema_version,
            "sections": [
                {
                    "category": item.category.value,
                    "heading": item.heading,
                    "normalized_end": item.normalized_end,
                    "normalized_start": item.normalized_start,
                    "selector": item.selector,
                    "text_sha256": item.text_sha256,
                    "text_characters": len(item.text),
                }
                for item in snapshot.sections
            ],
            "source_content_sha256": snapshot.source_content_sha256,
            "normalized_visible_sha256": snapshot.normalized_visible_sha256,
            "source_url": snapshot.source_url,
        }
    )


def _selection_sha256(receipt: FilingChangeSelectionReceipt) -> str:
    return _canonical_sha256(
        receipt.model_dump(
            mode="json",
            exclude={"receipt_id", "selection_sha256"},
        )
    )


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(payload.encode()).hexdigest()


def _normalize_text(value: str) -> str:
    return " ".join(value.split())


def _text_sha256(value: str) -> str:
    return sha256(value.encode()).hexdigest()
