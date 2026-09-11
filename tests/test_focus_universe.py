"""Versioned Focus Universe and one-queue fairness tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from kalki_market_intelligence.radar.focus import (
    FOCUS_FAIRNESS_AGE,
    FocusHistoryError,
    FocusMembershipAction,
    FocusMembershipEvent,
    FocusMembershipReason,
    FocusQueueBand,
    FocusQueueCandidate,
    QueueMaterialBasis,
    prioritize_focus_queue,
    project_focus_universe,
)

NOW = datetime(2026, 8, 30, 16, 0, tzinfo=UTC)
ADD = UUID("10000000-0000-4000-8000-000000000001")
REMOVE = UUID("10000000-0000-4000-8000-000000000002")


def membership(
    *,
    event_id: UUID = ADD,
    action: FocusMembershipAction = FocusMembershipAction.ADDED,
    effective_at: datetime = NOW - timedelta(days=2),
    recorded_at: datetime = NOW - timedelta(days=2),
    supersedes_event_id: UUID | None = None,
) -> FocusMembershipEvent:
    return FocusMembershipEvent(
        event_id=event_id,
        canonical_cik="0000789019",
        ticker="MSFT",
        company_name="Synthetic Focus Issuer",
        action=action,
        reason=FocusMembershipReason.CURATED_REVIEW,
        effective_at=effective_at,
        recorded_at=recorded_at,
        universe_version="TEST-2026.08",
        supersedes_event_id=supersedes_event_id,
    )


def candidate(
    accession: str,
    cik: str,
    *,
    age: timedelta,
    material: bool = False,
) -> FocusQueueCandidate:
    return FocusQueueCandidate(
        accession_number=accession,
        cik=cik,
        discovered_at=NOW - age,
        material_basis=(
            QueueMaterialBasis.DETERMINISTIC_ESCALATION
            if material
            else QueueMaterialBasis.NOT_ESTABLISHED
        ),
    )


def test_membership_projection_is_point_in_time_and_removal_is_append_only() -> None:
    removal = membership(
        event_id=REMOVE,
        action=FocusMembershipAction.REMOVED,
        effective_at=NOW - timedelta(hours=1),
        recorded_at=NOW - timedelta(hours=1),
        supersedes_event_id=ADD,
    )

    before = project_focus_universe((membership(), removal), as_of=NOW - timedelta(hours=2))
    after = project_focus_universe((membership(), removal), as_of=NOW)

    assert tuple(member.canonical_cik for member in before.members) == ("0000789019",)
    assert after.members == ()


def test_late_recorded_membership_cannot_leak_into_an_earlier_snapshot() -> None:
    late = membership(
        effective_at=NOW - timedelta(days=10),
        recorded_at=NOW + timedelta(hours=1),
    )

    assert project_focus_universe((late,), as_of=NOW).members == ()


def test_ambiguous_or_same_action_history_fails_closed() -> None:
    bad_removal = membership(
        event_id=REMOVE,
        action=FocusMembershipAction.REMOVED,
        supersedes_event_id=UUID("20000000-0000-4000-8000-000000000099"),
    )
    with pytest.raises(FocusHistoryError, match="exact chain"):
        project_focus_universe((membership(), bad_removal), as_of=NOW)

    duplicate_add = membership(
        event_id=REMOVE,
        effective_at=NOW - timedelta(days=1),
        recorded_at=NOW - timedelta(days=1),
        supersedes_event_id=ADD,
    )
    with pytest.raises(FocusHistoryError, match="must alternate"):
        project_focus_universe((membership(), duplicate_add), as_of=NOW)


def test_removal_without_prior_identity_and_future_recording_are_rejected() -> None:
    with pytest.raises(ValidationError, match="must supersede"):
        membership(event_id=REMOVE, action=FocusMembershipAction.REMOVED)
    with pytest.raises(ValidationError, match="recorded before"):
        membership(effective_at=NOW, recorded_at=NOW - timedelta(seconds=1))


def test_one_queue_prefers_focus_material_then_material_then_focus_then_ordinary() -> None:
    focus = project_focus_universe((membership(),), as_of=NOW)
    ranked = prioritize_focus_queue(
        (
            candidate("0000000001-26-000001", "1", age=timedelta(hours=1)),
            candidate("0000000002-26-000002", "2", age=timedelta(hours=1), material=True),
            candidate("0000789019-26-000003", "789019", age=timedelta(hours=1)),
            candidate("0000789019-26-000004", "789019", age=timedelta(hours=1), material=True),
        ),
        focus=focus,
        evaluated_at=NOW,
    )

    assert tuple(item.band for item in ranked) == (
        FocusQueueBand.FOCUS_MATERIAL,
        FocusQueueBand.MATERIAL,
        FocusQueueBand.FOCUS,
        FocusQueueBand.ORDINARY,
    )


def test_ordinary_candidate_cannot_starve_and_oldest_aged_work_wins() -> None:
    focus = project_focus_universe((membership(),), as_of=NOW)
    ranked = prioritize_focus_queue(
        (
            candidate(
                "0000000001-26-000001",
                "1",
                age=FOCUS_FAIRNESS_AGE + timedelta(hours=2),
            ),
            candidate("0000789019-26-000002", "789019", age=timedelta(minutes=5), material=True),
            candidate(
                "0000000002-26-000003",
                "2",
                age=FOCUS_FAIRNESS_AGE + timedelta(hours=1),
            ),
        ),
        focus=focus,
        evaluated_at=NOW,
    )

    assert tuple(item.accession_number for item in ranked[:2]) == (
        "0000000001-26-000001",
        "0000000002-26-000003",
    )
    assert all(item.aged_fairness_override for item in ranked[:2])
    assert ranked[2].band is FocusQueueBand.FOCUS_MATERIAL


def test_priority_rejects_duplicate_accessions_and_future_discovery() -> None:
    focus = project_focus_universe((), as_of=NOW)
    repeated = candidate("0000000001-26-000001", "1", age=timedelta(hours=1))
    with pytest.raises(ValueError, match="unique accessions"):
        prioritize_focus_queue((repeated, repeated), focus=focus, evaluated_at=NOW)
    with pytest.raises(ValueError, match="before discovery"):
        prioritize_focus_queue(
            (
                FocusQueueCandidate(
                    accession_number="0000000002-26-000002",
                    cik="2",
                    discovered_at=NOW + timedelta(seconds=1),
                ),
            ),
            focus=focus,
            evaluated_at=NOW,
        )
