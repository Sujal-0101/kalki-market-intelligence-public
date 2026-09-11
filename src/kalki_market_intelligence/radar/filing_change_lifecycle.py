"""Deterministic lifecycle orchestration for private filing-change snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time
from enum import StrEnum
from hashlib import sha256
from typing import Literal, Protocol
from uuid import UUID

from pydantic import model_validator

from kalki_market_intelligence.contracts.common import ContractModel, Sha256Hex, UtcDatetime
from kalki_market_intelligence.forensics.filing_change import (
    FilingChangeForm,
    FilingChangeRelationship,
    FilingChangeSelectionReceipt,
    FilingChangeSnapshot,
    compare_and_select_filing_changes,
)
from kalki_market_intelligence.providers.sec.client import SecFetchedPrimaryDocument
from kalki_market_intelligence.providers.sec.contracts import SecFilingRecord
from kalki_market_intelligence.providers.sec.filing_change import (
    FilingChangeExtractionError,
    build_snapshot_from_filing_change_extraction,
    extract_filing_change_sections,
)
from kalki_market_intelligence.radar.contracts import AccessionNumber

FILING_CHANGE_LIFECYCLE_VERSION: Literal["filing-change-lifecycle-v1"] = (
    "filing-change-lifecycle-v1"
)

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


class FilingChangeLifecycleDisposition(StrEnum):
    SNAPSHOT_ONLY = "snapshot_only"
    SELECTION_RECORDED = "selection_recorded"
    NO_SELECTED_CHANGE = "no_selected_change"


class FilingChangeLifecycleReason(StrEnum):
    NO_PRIOR_SNAPSHOT = "no_prior_snapshot"
    NO_COMPATIBLE_PRIOR = "no_compatible_prior"
    CHANGED_SECTIONS_SELECTED = "changed_sections_selected"
    SELECTED_SECTIONS_UNCHANGED = "selected_sections_unchanged"


class FilingChangeLifecycleReceipt(ContractModel):
    """Content-free result of one deterministic snapshot lifecycle decision."""

    current_accession_number: AccessionNumber
    current_manifest_sha256: Sha256Hex
    knowledge_cutoff_at: UtcDatetime
    disposition: FilingChangeLifecycleDisposition
    reason: FilingChangeLifecycleReason
    previous_accession_number: AccessionNumber | None = None
    previous_manifest_sha256: Sha256Hex | None = None
    relationship: FilingChangeRelationship | None = None
    selection_receipt_id: UUID | None = None
    selection_sha256: Sha256Hex | None = None
    selected_characters: int | None = None
    lifecycle_version: Literal["filing-change-lifecycle-v1"] = FILING_CHANGE_LIFECYCLE_VERSION

    @model_validator(mode="after")
    def lifecycle_fields_reconcile(self) -> FilingChangeLifecycleReceipt:
        previous_fields = (
            self.previous_accession_number,
            self.previous_manifest_sha256,
            self.relationship,
        )
        selection_fields = (
            self.selection_receipt_id,
            self.selection_sha256,
            self.selected_characters,
        )
        has_previous = all(value is not None for value in previous_fields)
        has_selection = all(value is not None for value in selection_fields)
        if any(value is not None for value in previous_fields) != has_previous:
            raise ValueError("filing-change prior identity must be present together")
        if any(value is not None for value in selection_fields) != has_selection:
            raise ValueError("filing-change selection identity must be present together")
        if self.disposition is FilingChangeLifecycleDisposition.SNAPSHOT_ONLY:
            if has_previous or has_selection or self.selected_characters is not None:
                raise ValueError("snapshot-only lifecycle cannot retain a prior selection")
            if self.reason not in {
                FilingChangeLifecycleReason.NO_PRIOR_SNAPSHOT,
                FilingChangeLifecycleReason.NO_COMPATIBLE_PRIOR,
            }:
                raise ValueError("snapshot-only lifecycle requires a closed no-prior reason")
        else:
            if not has_previous or not has_selection:
                raise ValueError("filing-change comparison requires complete selection identity")
            if self.disposition is FilingChangeLifecycleDisposition.SELECTION_RECORDED:
                if self.reason is not FilingChangeLifecycleReason.CHANGED_SECTIONS_SELECTED:
                    raise ValueError("changed selection requires its closed lifecycle reason")
                if self.selected_characters is None or self.selected_characters <= 0:
                    raise ValueError("changed selection must retain selected characters")
            elif (
                self.reason is not FilingChangeLifecycleReason.SELECTED_SECTIONS_UNCHANGED
                or self.selected_characters != 0
            ):
                raise ValueError("unchanged selection must retain a zero-character result")
        return self


@dataclass(frozen=True, slots=True)
class FilingChangePrimarySource:
    """Validated transport result required to build one private source snapshot."""

    accession_number: str
    cik: str
    filing_form: FilingChangeForm
    filed_at: datetime
    available_at: datetime
    retrieved_at: datetime
    source_url: str
    source_content_sha256: str
    body: bytes


class FilingChangeLifecycleStore(Protocol):
    def append_filing_change_snapshot(self, snapshot: FilingChangeSnapshot) -> None: ...

    def filing_change_snapshot_for_accession(
        self,
        *,
        cik: str,
        accession_number: str,
        knowledge_cutoff_at: UtcDatetime,
    ) -> FilingChangeSnapshot | None: ...

    def filing_change_snapshots(
        self,
        *,
        cik: str,
        knowledge_cutoff_at: UtcDatetime,
        exclude_accession_number: str | None = None,
        limit: int = 16,
    ) -> tuple[FilingChangeSnapshot, ...]: ...

    def append_filing_change_selection(
        self,
        previous: FilingChangeSnapshot,
        current: FilingChangeSnapshot,
        receipt: FilingChangeSelectionReceipt,
    ) -> None: ...


def persist_filing_change_snapshot(
    store: FilingChangeLifecycleStore,
    current: FilingChangeSnapshot,
) -> FilingChangeLifecycleReceipt:
    """Persist one current snapshot and its latest admissible prior comparison."""

    current = FilingChangeSnapshot.model_validate(current.model_dump(mode="json"))
    candidates = store.filing_change_snapshots(
        cik=current.cik,
        knowledge_cutoff_at=current.retrieved_at,
        exclude_accession_number=current.accession_number,
        limit=64,
    )
    selected = _select_prior(candidates, current)
    if selected is None:
        store.append_filing_change_snapshot(current)
        return FilingChangeLifecycleReceipt(
            current_accession_number=current.accession_number,
            current_manifest_sha256=current.manifest_sha256,
            knowledge_cutoff_at=current.retrieved_at,
            disposition=FilingChangeLifecycleDisposition.SNAPSHOT_ONLY,
            reason=(
                FilingChangeLifecycleReason.NO_PRIOR_SNAPSHOT
                if not candidates
                else FilingChangeLifecycleReason.NO_COMPATIBLE_PRIOR
            ),
        )

    previous, relationship = selected
    selection = compare_and_select_filing_changes(
        previous,
        current,
        relationship=relationship,
    )
    store.append_filing_change_selection(previous, current, selection)
    changed = bool(selection.changes)
    return FilingChangeLifecycleReceipt(
        current_accession_number=current.accession_number,
        current_manifest_sha256=current.manifest_sha256,
        knowledge_cutoff_at=current.retrieved_at,
        disposition=(
            FilingChangeLifecycleDisposition.SELECTION_RECORDED
            if changed
            else FilingChangeLifecycleDisposition.NO_SELECTED_CHANGE
        ),
        reason=(
            FilingChangeLifecycleReason.CHANGED_SECTIONS_SELECTED
            if changed
            else FilingChangeLifecycleReason.SELECTED_SECTIONS_UNCHANGED
        ),
        previous_accession_number=previous.accession_number,
        previous_manifest_sha256=previous.manifest_sha256,
        relationship=relationship,
        selection_receipt_id=selection.receipt_id,
        selection_sha256=selection.selection_sha256,
        selected_characters=selection.selected_characters,
    )


def persist_filing_change_primary_source(
    store: FilingChangeLifecycleStore,
    source: FilingChangePrimarySource,
) -> FilingChangeLifecycleReceipt:
    """Validate, extract and persist one exact supported primary filing source."""

    if sha256(source.body).hexdigest() != source.source_content_sha256:
        raise ValueError("filing-change primary source hash does not reconcile")
    extraction = extract_filing_change_sections(
        source.body,
        filing_form=source.filing_form,
    )
    if extraction.source_content_sha256 != source.source_content_sha256:
        raise ValueError("filing-change extraction changed the primary source identity")
    snapshot = build_snapshot_from_filing_change_extraction(
        extraction,
        accession_number=source.accession_number,
        cik=source.cik,
        filed_at=source.filed_at,
        available_at=source.available_at,
        retrieved_at=source.retrieved_at,
        source_url=source.source_url,
    )
    return persist_filing_change_snapshot(store, snapshot)


def observe_sec_primary_filing_change(
    store: FilingChangeLifecycleStore,
    filing: SecFilingRecord,
    document: SecFetchedPrimaryDocument,
) -> FilingChangeLifecycleReceipt | None:
    """Persist an eligible fetched primary source without widening its parent pipeline.

    Unsupported forms and sources that cannot produce a bounded relevant-section
    snapshot are outside this optional sink. Identity, replay, and persistence
    failures still propagate so the parent queue can retry rather than lose history.
    """

    try:
        filing_form = FilingChangeForm(filing.form)
    except ValueError:
        return None
    if (
        document.cik != filing.cik
        or document.accession_number != filing.accession_number
        or document.document_name != filing.primary_document
        or document.url != str(filing.filing_url)
    ):
        raise ValueError("filing-change primary document identity does not reconcile")
    if sha256(document.body).hexdigest() != document.content_sha256:
        raise ValueError("filing-change primary document hash does not reconcile")
    existing = store.filing_change_snapshot_for_accession(
        cik=filing.cik,
        accession_number=filing.accession_number,
        knowledge_cutoff_at=document.retrieved_at,
    )
    if existing is not None:
        if (
            existing.filing_form is not filing_form
            or existing.filed_at.date() != filing.filing_date
            or existing.source_url != document.url
            or existing.source_content_sha256 != document.content_sha256
        ):
            raise ValueError("filing-change accession conflicts with immutable source history")
        return persist_filing_change_snapshot(store, existing)
    try:
        return persist_filing_change_primary_source(
            store,
            FilingChangePrimarySource(
                accession_number=filing.accession_number,
                cik=filing.cik,
                filing_form=filing_form,
                filed_at=datetime.combine(filing.filing_date, time.min, tzinfo=UTC),
                available_at=filing.available_at,
                retrieved_at=document.retrieved_at,
                source_url=document.url,
                source_content_sha256=document.content_sha256,
                body=document.body,
            ),
        )
    except FilingChangeExtractionError:
        return None


def _select_prior(
    candidates: tuple[FilingChangeSnapshot, ...],
    current: FilingChangeSnapshot,
) -> tuple[FilingChangeSnapshot, FilingChangeRelationship] | None:
    compatible: list[tuple[FilingChangeSnapshot, FilingChangeRelationship]] = []
    for previous in candidates:
        relationship = _relationship(previous, current)
        if relationship is not None:
            compatible.append((previous, relationship))
    if current.filing_form.value.endswith("/A"):
        for selected in compatible:
            if selected[1] is FilingChangeRelationship.AMENDMENT_OF:
                return selected
    return compatible[0] if compatible else None


def _relationship(
    previous: FilingChangeSnapshot,
    current: FilingChangeSnapshot,
) -> FilingChangeRelationship | None:
    if (
        previous.cik != current.cik
        or previous.accession_number == current.accession_number
        or previous.available_at >= current.available_at
        or previous.retrieved_at > current.retrieved_at
        or previous.filed_at > current.filed_at
        or previous.extraction_version != current.extraction_version
    ):
        return None
    if current.filing_form.value.endswith("/A"):
        if (
            not previous.filing_form.value.endswith("/A")
            and current.filing_form.value.removesuffix("/A") == previous.filing_form.value
        ):
            return FilingChangeRelationship.AMENDMENT_OF
        if previous.filing_form in _PROSPECTUS_FORMS:
            return FilingChangeRelationship.PROSPECTUS_UPDATE
        return None
    if current.filing_form in _PERIODIC_FORMS:
        if previous.filing_form is current.filing_form:
            return FilingChangeRelationship.SUCCESSIVE_PERIODIC_REPORT
        return None
    if current.filing_form in _PROSPECTUS_FORMS and previous.filing_form in _PROSPECTUS_FORMS:
        return FilingChangeRelationship.PROSPECTUS_UPDATE
    return None
