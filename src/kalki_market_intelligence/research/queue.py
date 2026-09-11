"""Restart-safe queue semantics for human research leads.

The memory implementation is a deterministic test double. Production persistence
is provided by the PostgreSQL adapter in ``radar.store`` using the same contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from kalki_market_intelligence.research.intake import (
    HumanLeadPriority,
    HumanLeadStatus,
    HumanResearchLead,
)


@dataclass(frozen=True, slots=True)
class LeadEvent:
    lead_id: str
    status: HumanLeadStatus
    occurred_at: datetime
    detail: str


class MemoryHumanLeadQueue:
    """Small deterministic queue used by unit tests and local dry runs."""

    def __init__(self, leads: tuple[HumanResearchLead, ...] = ()) -> None:
        self._leads = {lead.lead_id: lead for lead in leads}
        if len(self._leads) != len(leads):
            raise ValueError("human lead IDs must be unique")
        self._events: list[LeadEvent] = [
            LeadEvent(
                lead_id=str(lead.lead_id),
                status=lead.status,
                occurred_at=lead.submitted_at,
                detail="lead restored",
            )
            for lead in leads
        ]

    def enqueue(self, lead: HumanResearchLead, *, now: datetime) -> HumanResearchLead:
        """Return a duplicate marker or persist a queued lead exactly once."""

        if any(
            item.dedupe_key == lead.dedupe_key
            and item.status
            not in {
                HumanLeadStatus.DUPLICATE,
                HumanLeadStatus.REJECTED,
                HumanLeadStatus.CANCELLED,
            }
            for item in self._leads.values()
        ):
            duplicate = lead.model_copy(update={"status": HumanLeadStatus.DUPLICATE})
            self._record(duplicate, now, "duplicate lead suppressed")
            return duplicate
        queued = lead.model_copy(update={"status": HumanLeadStatus.QUEUED})
        self._leads[queued.lead_id] = queued
        self._record(queued, now, "lead queued")
        return queued

    def claim(self, *, now: datetime) -> HumanResearchLead | None:
        eligible = [item for item in self._leads.values() if item.status is HumanLeadStatus.QUEUED]
        if not eligible:
            return None
        priority = {
            HumanLeadPriority.HIGH: 0,
            HumanLeadPriority.NORMAL: 1,
            HumanLeadPriority.LOW: 2,
        }
        selected = min(
            eligible,
            key=lambda item: (priority[item.priority], item.submitted_at, str(item.lead_id)),
        )
        claimed = selected.model_copy(
            update={
                "status": HumanLeadStatus.ANALYZING,
                "attempts": selected.attempts + 1,
            }
        )
        self._leads[claimed.lead_id] = claimed
        self._record(claimed, now, "lead claimed for bounded analysis")
        return claimed

    def transition(
        self,
        lead_id: str,
        status: HumanLeadStatus,
        *,
        now: datetime,
        detail: str,
    ) -> HumanResearchLead:
        """Append a bounded status event and update only the mutable queue head."""

        matching = next(
            (item for item in self._leads.values() if str(item.lead_id) == lead_id),
            None,
        )
        if matching is None:
            raise KeyError("unknown human lead")
        updated = matching.model_copy(update={"status": status})
        self._leads[updated.lead_id] = updated
        self._record(updated, now, detail)
        return updated

    def events(self, lead_id: str | None = None) -> tuple[LeadEvent, ...]:
        if lead_id is None:
            return tuple(self._events)
        return tuple(item for item in self._events if item.lead_id == lead_id)

    def pending_count(self) -> int:
        return sum(item.status is HumanLeadStatus.QUEUED for item in self._leads.values())

    def _record(self, lead: HumanResearchLead, now: datetime, detail: str) -> None:
        occurred_at = now.astimezone(UTC) if now.tzinfo else now.replace(tzinfo=UTC)
        self._events.append(
            LeadEvent(
                lead_id=str(lead.lead_id),
                status=lead.status,
                occurred_at=occurred_at,
                detail=detail,
            )
        )
