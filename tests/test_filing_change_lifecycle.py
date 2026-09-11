"""Deterministic tests for selecting and persisting filing-change history."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from kalki_market_intelligence.forensics.filing_change import (
    FilingChangeCategory,
    FilingChangeForm,
    FilingChangeSelectionReceipt,
    FilingChangeSnapshot,
    build_filing_change_section,
    build_filing_change_snapshot,
)
from kalki_market_intelligence.providers.sec.client import SecFetchedPrimaryDocument
from kalki_market_intelligence.providers.sec.contracts import SecFilingRecord
from kalki_market_intelligence.radar.filing_change_lifecycle import (
    FilingChangeLifecycleDisposition,
    FilingChangeLifecycleReason,
    FilingChangePrimarySource,
    observe_sec_primary_filing_change,
    persist_filing_change_primary_source,
    persist_filing_change_snapshot,
)

BASE_TIME = datetime(2026, 9, 1, 10, tzinfo=UTC)


class MemoryStore:
    def __init__(self, snapshots: tuple[FilingChangeSnapshot, ...] = ()) -> None:
        self.snapshots = list(snapshots)
        self.selections: list[FilingChangeSelectionReceipt] = []

    def append_filing_change_snapshot(self, snapshot: FilingChangeSnapshot) -> None:
        if snapshot not in self.snapshots:
            self.snapshots.append(snapshot)

    def filing_change_snapshot_for_accession(
        self,
        *,
        cik: str,
        accession_number: str,
        knowledge_cutoff_at: datetime,
    ) -> FilingChangeSnapshot | None:
        matches = [
            item
            for item in self.snapshots
            if item.cik == cik
            and item.accession_number == accession_number
            and item.available_at <= knowledge_cutoff_at
            and item.retrieved_at <= knowledge_cutoff_at
        ]
        if len(matches) > 1:
            raise RuntimeError("duplicate immutable accession")
        return matches[0] if matches else None

    def filing_change_snapshots(
        self,
        *,
        cik: str,
        knowledge_cutoff_at: datetime,
        exclude_accession_number: str | None = None,
        limit: int = 16,
    ) -> tuple[FilingChangeSnapshot, ...]:
        eligible = [
            item
            for item in self.snapshots
            if item.cik == cik
            and item.available_at <= knowledge_cutoff_at
            and item.retrieved_at <= knowledge_cutoff_at
            and item.accession_number != exclude_accession_number
        ]
        return tuple(
            sorted(
                eligible,
                key=lambda item: (item.available_at, item.retrieved_at, item.manifest_sha256),
                reverse=True,
            )[:limit]
        )

    def append_filing_change_selection(
        self,
        previous: FilingChangeSnapshot,
        current: FilingChangeSnapshot,
        receipt: FilingChangeSelectionReceipt,
    ) -> None:
        self.append_filing_change_snapshot(previous)
        self.append_filing_change_snapshot(current)
        if receipt not in self.selections:
            self.selections.append(receipt)


def _snapshot(
    accession: str,
    *,
    hours: int,
    form: FilingChangeForm = FilingChangeForm.FORM_424_B_5,
    text: str = "The issuer reports a bounded risk factor for this exact source.",
) -> FilingChangeSnapshot:
    source = f"<html><h1>Risk Factors</h1><p>{text}</p></html>"
    available_at = BASE_TIME + timedelta(hours=hours)
    section = build_filing_change_section(
        selector="risks",
        heading="Risk factors",
        category=FilingChangeCategory.RISKS,
        text=text,
        normalized_start=25,
    )
    return build_filing_change_snapshot(
        accession_number=accession,
        cik="1075880",
        filing_form=form,
        filed_at=available_at.replace(hour=0),
        available_at=available_at,
        retrieved_at=available_at + timedelta(minutes=1),
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/1075880/"
            f"{accession.replace('-', '')}/fixture.htm"
        ),
        source_content_sha256=sha256(source.encode()).hexdigest(),
        normalized_visible_sha256=sha256(text.encode()).hexdigest(),
        sections=(section,),
    )


def test_first_snapshot_records_truthful_no_prior_disposition() -> None:
    current = _snapshot("0001213900-26-000001", hours=1)
    store = MemoryStore()

    receipt = persist_filing_change_snapshot(store, current)

    assert receipt.disposition is FilingChangeLifecycleDisposition.SNAPSHOT_ONLY
    assert receipt.reason is FilingChangeLifecycleReason.NO_PRIOR_SNAPSHOT
    assert store.snapshots == [current]
    assert store.selections == []


def test_primary_source_hash_is_validated_before_extraction_or_persistence() -> None:
    body = b"<html><h1>Risk Factors</h1><p>Bounded exact risk narrative for extraction.</p></html>"
    source = FilingChangePrimarySource(
        accession_number="0001213900-26-000001",
        cik="1075880",
        filing_form=FilingChangeForm.FORM_424_B_5,
        filed_at=BASE_TIME.replace(hour=0),
        available_at=BASE_TIME,
        retrieved_at=BASE_TIME + timedelta(minutes=1),
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/1075880/000121390026000001/fixture.htm"
        ),
        source_content_sha256="0" * 64,
        body=body,
    )
    store = MemoryStore()

    try:
        persist_filing_change_primary_source(store, source)
    except ValueError as error:
        assert str(error) == "filing-change primary source hash does not reconcile"
    else:
        raise AssertionError("tampered primary source must fail closed")
    assert store.snapshots == []


def test_primary_source_runs_the_complete_extraction_and_lifecycle_path() -> None:
    narrative = "Bounded exact risk narrative for deterministic source extraction. " * 4
    body = f"<html><h1>Risk Factors</h1><p>{narrative}</p></html>".encode()
    source = FilingChangePrimarySource(
        accession_number="0001213900-26-000001",
        cik="1075880",
        filing_form=FilingChangeForm.FORM_424_B_5,
        filed_at=BASE_TIME.replace(hour=0),
        available_at=BASE_TIME,
        retrieved_at=BASE_TIME + timedelta(minutes=1),
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/1075880/000121390026000001/fixture.htm"
        ),
        source_content_sha256=sha256(body).hexdigest(),
        body=body,
    )
    store = MemoryStore()

    receipt = persist_filing_change_primary_source(store, source)

    assert receipt.reason is FilingChangeLifecycleReason.NO_PRIOR_SNAPSHOT
    assert len(store.snapshots) == 1
    assert store.snapshots[0].source_content_sha256 == sha256(body).hexdigest()


def test_primary_source_retry_reuses_first_immutable_retrieval() -> None:
    narrative = "Bounded exact risk narrative for deterministic source extraction. " * 4
    body = f"<html><h1>Risk Factors</h1><p>{narrative}</p></html>".encode()
    filing = SecFilingRecord.model_validate(
        {
            "record_id": "1" * 64,
            "cik": "1075880",
            "accession_number": "0001213900-26-000001",
            "form": "424B5",
            "filing_date": "2026-09-01",
            "report_date": None,
            "accepted_at": BASE_TIME,
            "available_at": BASE_TIME + timedelta(minutes=1),
            "retrieved_at": BASE_TIME + timedelta(minutes=1),
            "file_number": None,
            "primary_document": "fixture.htm",
            "primary_document_description": None,
            "filing_url": (
                "https://www.sec.gov/Archives/edgar/data/1075880/000121390026000001/fixture.htm"
            ),
            "source_content_sha256": "2" * 64,
        }
    )
    first_document = SecFetchedPrimaryDocument(
        cik="0001075880",
        accession_number=filing.accession_number,
        document_name="fixture.htm",
        url=str(filing.filing_url),
        status_code=200,
        headers={"content-type": "text/html"},
        body=body,
        content_sha256=sha256(body).hexdigest(),
        retrieved_at=BASE_TIME + timedelta(minutes=2),
    )
    later_filing = filing.model_copy(
        update={
            "available_at": BASE_TIME + timedelta(hours=1),
            "retrieved_at": BASE_TIME + timedelta(hours=1),
        }
    )
    later_document = replace(
        first_document,
        retrieved_at=BASE_TIME + timedelta(hours=1, minutes=1),
    )
    store = MemoryStore()

    first = observe_sec_primary_filing_change(store, filing, first_document)
    replay = observe_sec_primary_filing_change(store, later_filing, later_document)

    assert replay == first
    assert len(store.snapshots) == 1
    assert store.snapshots[0].retrieved_at == first_document.retrieved_at


def test_latest_compatible_prior_is_selected_and_persisted_atomically() -> None:
    oldest = _snapshot("0001213900-26-000001", hours=1, text="Old bounded risk text.")
    latest = _snapshot("0001213900-26-000002", hours=2, text="Latest bounded risk text.")
    current = _snapshot("0001213900-26-000003", hours=3, text="Current bounded risk text.")
    store = MemoryStore((oldest, latest))

    receipt = persist_filing_change_snapshot(store, current)

    assert receipt.disposition is FilingChangeLifecycleDisposition.SELECTION_RECORDED
    assert receipt.reason is FilingChangeLifecycleReason.CHANGED_SECTIONS_SELECTED
    assert receipt.previous_accession_number == latest.accession_number
    assert receipt.relationship is not None
    assert receipt.selected_characters is not None and receipt.selected_characters > 0
    assert len(store.selections) == 1
    assert store.selections[0].previous_manifest_sha256 == latest.manifest_sha256
    assert current in store.snapshots


def test_incompatible_prior_is_not_forced_into_a_comparison() -> None:
    periodic = _snapshot(
        "0001213900-26-000001",
        hours=1,
        form=FilingChangeForm.FORM_10_K,
    )
    current = _snapshot("0001213900-26-000002", hours=2)
    store = MemoryStore((periodic,))

    receipt = persist_filing_change_snapshot(store, current)

    assert receipt.disposition is FilingChangeLifecycleDisposition.SNAPSHOT_ONLY
    assert receipt.reason is FilingChangeLifecycleReason.NO_COMPATIBLE_PRIOR
    assert store.selections == []


def test_amendment_prefers_its_base_form_over_a_newer_generic_prospectus() -> None:
    base = _snapshot(
        "0001213900-26-000001",
        hours=1,
        form=FilingChangeForm.FORM_S_3,
        text="Base registration risk text.",
    )
    newer_prospectus = _snapshot(
        "0001213900-26-000002",
        hours=2,
        form=FilingChangeForm.FORM_424_B_5,
        text="Newer prospectus risk text.",
    )
    amendment = _snapshot(
        "0001213900-26-000003",
        hours=3,
        form=FilingChangeForm.FORM_S_3_AMENDMENT,
        text="Amended registration risk text.",
    )
    store = MemoryStore((base, newer_prospectus))

    receipt = persist_filing_change_snapshot(store, amendment)

    assert receipt.previous_accession_number == base.accession_number
    assert receipt.relationship is not None
    assert receipt.relationship.value == "amendment_of"


def test_unchanged_selected_sections_record_a_zero_character_selection() -> None:
    previous = _snapshot("0001213900-26-000001", hours=1)
    current = _snapshot("0001213900-26-000002", hours=2)
    store = MemoryStore((previous,))

    receipt = persist_filing_change_snapshot(store, current)

    assert receipt.disposition is FilingChangeLifecycleDisposition.NO_SELECTED_CHANGE
    assert receipt.reason is FilingChangeLifecycleReason.SELECTED_SECTIONS_UNCHANGED
    assert receipt.selected_characters == 0
    assert store.selections[0].changes == ()


def test_future_retrieval_and_later_incompatible_snapshot_cannot_displace_prior() -> None:
    compatible = _snapshot("0001213900-26-000001", hours=1, text="Prior risk text.")
    incompatible = _snapshot(
        "0001213900-26-000002",
        hours=2,
        form=FilingChangeForm.FORM_10_Q,
    )
    future = _snapshot("0001213900-26-000003", hours=5, text="Future risk text.")
    current = _snapshot("0001213900-26-000004", hours=3, text="Current risk text.")
    store = MemoryStore((compatible, incompatible, future))

    receipt = persist_filing_change_snapshot(store, current)

    assert receipt.previous_accession_number == compatible.accession_number
    assert future not in store.filing_change_snapshots(
        cik=current.cik,
        knowledge_cutoff_at=current.retrieved_at,
    )
