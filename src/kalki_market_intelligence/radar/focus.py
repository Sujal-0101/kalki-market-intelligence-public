"""Versioned Focus Universe history and starvation-safe queue priority."""

from __future__ import annotations

from datetime import timedelta
from enum import IntEnum, StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from kalki_market_intelligence.contracts.common import ContractModel, ShortText, UtcDatetime
from kalki_market_intelligence.radar.contracts import AccessionNumber, TickerText

FOCUS_MEMBERSHIP_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
FOCUS_PRIORITY_RULESET_VERSION: Literal["1.0.0"] = "1.0.0"
FOCUS_FAIRNESS_AGE = timedelta(hours=24)

type CanonicalCik = Annotated[str, StringConstraints(pattern=r"^\d{10}$")]
type UniverseVersion = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=64, pattern=r"^[A-Z0-9._-]+$"
    ),
]


class FocusMembershipAction(StrEnum):
    ADDED = "added"
    REMOVED = "removed"


class FocusMembershipReason(StrEnum):
    WIDELY_FOLLOWED = "widely_followed"
    USER_INTEREST = "user_interest"
    CURATED_REVIEW = "curated_review"


class FocusMembershipEvent(ContractModel):
    """One append-only, availability-aware Focus membership transition."""

    event_id: UUID
    canonical_cik: CanonicalCik
    ticker: TickerText | None
    company_name: ShortText
    action: FocusMembershipAction
    reason: FocusMembershipReason
    effective_at: UtcDatetime
    recorded_at: UtcDatetime
    universe_version: UniverseVersion
    supersedes_event_id: UUID | None = None
    schema_version: Literal["1.0.0"] = FOCUS_MEMBERSHIP_SCHEMA_VERSION

    @model_validator(mode="after")
    def timing_and_chain_shape_are_safe(self) -> FocusMembershipEvent:
        if self.recorded_at < self.effective_at:
            raise ValueError("focus membership cannot be recorded before it is effective")
        if self.action is FocusMembershipAction.REMOVED and self.supersedes_event_id is None:
            raise ValueError("focus removal must supersede the active membership event")
        if self.supersedes_event_id == self.event_id:
            raise ValueError("focus membership event cannot supersede itself")
        return self


class FocusMember(ContractModel):
    canonical_cik: CanonicalCik
    ticker: TickerText | None
    company_name: ShortText
    active_event_id: UUID
    reason: FocusMembershipReason
    effective_at: UtcDatetime
    recorded_at: UtcDatetime
    universe_version: UniverseVersion


class FocusUniverseSnapshot(ContractModel):
    """Point-in-time projection that cannot see later-recorded membership."""

    as_of: UtcDatetime
    members: tuple[FocusMember, ...] = Field(max_length=10_000)
    schema_version: Literal["1.0.0"] = FOCUS_MEMBERSHIP_SCHEMA_VERSION

    @model_validator(mode="after")
    def membership_is_unique_and_available(self) -> FocusUniverseSnapshot:
        ciks = tuple(member.canonical_cik for member in self.members)
        if len(set(ciks)) != len(ciks):
            raise ValueError("focus snapshot cannot contain duplicate issuers")
        if any(
            member.effective_at > self.as_of or member.recorded_at > self.as_of
            for member in self.members
        ):
            raise ValueError("focus snapshot cannot contain future membership")
        return self


class QueueMaterialBasis(StrEnum):
    DETERMINISTIC_ESCALATION = "deterministic_escalation"
    NOT_ESTABLISHED = "not_established"


class FocusQueueBand(IntEnum):
    AGED_FAIRNESS = 0
    FOCUS_MATERIAL = 1
    MATERIAL = 2
    FOCUS = 3
    ORDINARY = 4


class FocusQueueCandidate(ContractModel):
    accession_number: AccessionNumber
    cik: Annotated[str, StringConstraints(pattern=r"^\d{1,10}$")]
    discovered_at: UtcDatetime
    material_basis: QueueMaterialBasis = QueueMaterialBasis.NOT_ESTABLISHED


class FocusQueuePriorityReceipt(ContractModel):
    """Content-free priority decision; it never authorizes a second pipeline."""

    accession_number: AccessionNumber
    canonical_cik: CanonicalCik
    evaluated_at: UtcDatetime
    discovered_at: UtcDatetime
    age_seconds: int = Field(ge=0)
    is_focus_member: bool
    material_basis: QueueMaterialBasis
    band: FocusQueueBand
    aged_fairness_override: bool
    ruleset_version: Literal["1.0.0"] = FOCUS_PRIORITY_RULESET_VERSION

    @model_validator(mode="after")
    def band_reconciles_to_inputs(self) -> FocusQueuePriorityReceipt:
        if self.evaluated_at < self.discovered_at:
            raise ValueError("queue priority cannot be evaluated before discovery")
        expected_age = int((self.evaluated_at - self.discovered_at).total_seconds())
        if self.age_seconds != expected_age:
            raise ValueError("queue priority age must be calculated deterministically")
        expected = _priority_band(
            age=self.evaluated_at - self.discovered_at,
            is_focus=self.is_focus_member,
            material_basis=self.material_basis,
        )
        if self.band is not expected or self.aged_fairness_override != (
            expected is FocusQueueBand.AGED_FAIRNESS
        ):
            raise ValueError("queue priority band does not reconcile to its closed inputs")
        return self


class FocusHistoryError(ValueError):
    """Membership history is ambiguous or internally inconsistent."""


def project_focus_universe(
    events: tuple[FocusMembershipEvent, ...], *, as_of: UtcDatetime
) -> FocusUniverseSnapshot:
    """Project only transitions effective and recorded by the point-in-time cutoff."""

    event_ids = tuple(event.event_id for event in events)
    if len(set(event_ids)) != len(event_ids):
        raise FocusHistoryError("focus membership event IDs must be unique")
    eligible = tuple(
        event for event in events if event.effective_at <= as_of and event.recorded_at <= as_of
    )
    by_cik: dict[str, list[FocusMembershipEvent]] = {}
    for event in eligible:
        by_cik.setdefault(event.canonical_cik, []).append(event)
    members: list[FocusMember] = []
    for cik, issuer_events in by_cik.items():
        ordered = sorted(issuer_events, key=lambda event: (event.recorded_at, str(event.event_id)))
        previous: FocusMembershipEvent | None = None
        for event in ordered:
            if previous is None:
                if (
                    event.action is not FocusMembershipAction.ADDED
                    or event.supersedes_event_id is not None
                ):
                    raise FocusHistoryError("focus history must begin with an unsuperseded add")
            else:
                if event.supersedes_event_id != previous.event_id:
                    raise FocusHistoryError("focus history transitions must form one exact chain")
                if event.action is previous.action:
                    raise FocusHistoryError(
                        "focus membership add/remove transitions must alternate"
                    )
                if event.company_name != previous.company_name:
                    raise FocusHistoryError("focus history cannot silently change issuer identity")
            previous = event
        assert previous is not None
        if previous.action is FocusMembershipAction.ADDED:
            members.append(
                FocusMember(
                    canonical_cik=cik,
                    ticker=previous.ticker,
                    company_name=previous.company_name,
                    active_event_id=previous.event_id,
                    reason=previous.reason,
                    effective_at=previous.effective_at,
                    recorded_at=previous.recorded_at,
                    universe_version=previous.universe_version,
                )
            )
    return FocusUniverseSnapshot(
        as_of=as_of,
        members=tuple(sorted(members, key=lambda member: member.canonical_cik)),
    )


def prioritize_focus_queue(
    candidates: tuple[FocusQueueCandidate, ...],
    *,
    focus: FocusUniverseSnapshot,
    evaluated_at: UtcDatetime,
) -> tuple[FocusQueuePriorityReceipt, ...]:
    """Rank one queue with an explicit 24-hour starvation-prevention override."""

    accessions = tuple(candidate.accession_number for candidate in candidates)
    if len(set(accessions)) != len(accessions):
        raise ValueError("queue priority candidates must have unique accessions")
    focus_ciks = {member.canonical_cik for member in focus.members}
    receipts = tuple(
        _priority_receipt(
            candidate,
            evaluated_at=evaluated_at,
            is_focus=candidate.cik.zfill(10) in focus_ciks,
        )
        for candidate in candidates
    )
    return tuple(
        sorted(
            receipts,
            key=lambda receipt: (
                int(receipt.band),
                receipt.discovered_at,
                receipt.accession_number,
            ),
        )
    )


def _priority_receipt(
    candidate: FocusQueueCandidate, *, evaluated_at: UtcDatetime, is_focus: bool
) -> FocusQueuePriorityReceipt:
    if evaluated_at < candidate.discovered_at:
        raise ValueError("queue priority cannot be evaluated before discovery")
    age = evaluated_at - candidate.discovered_at
    band = _priority_band(
        age=age,
        is_focus=is_focus,
        material_basis=candidate.material_basis,
    )
    return FocusQueuePriorityReceipt(
        accession_number=candidate.accession_number,
        canonical_cik=candidate.cik.zfill(10),
        evaluated_at=evaluated_at,
        discovered_at=candidate.discovered_at,
        age_seconds=int(age.total_seconds()),
        is_focus_member=is_focus,
        material_basis=candidate.material_basis,
        band=band,
        aged_fairness_override=band is FocusQueueBand.AGED_FAIRNESS,
    )


def _priority_band(
    *, age: timedelta, is_focus: bool, material_basis: QueueMaterialBasis
) -> FocusQueueBand:
    if age >= FOCUS_FAIRNESS_AGE:
        return FocusQueueBand.AGED_FAIRNESS
    if is_focus and material_basis is QueueMaterialBasis.DETERMINISTIC_ESCALATION:
        return FocusQueueBand.FOCUS_MATERIAL
    if material_basis is QueueMaterialBasis.DETERMINISTIC_ESCALATION:
        return FocusQueueBand.MATERIAL
    if is_focus:
        return FocusQueueBand.FOCUS
    return FocusQueueBand.ORDINARY
