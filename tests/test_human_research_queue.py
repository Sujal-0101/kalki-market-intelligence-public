"""Human lead queue ordering, deduplication, and restart semantics."""

from datetime import UTC, datetime, timedelta

from kalki_market_intelligence.research import (
    HumanLeadPriority,
    HumanLeadStatus,
    HumanResearchLead,
    MemoryHumanLeadQueue,
)

NOW = datetime(2026, 8, 26, 12, tzinfo=UTC)
IDS = {
    "discord_message_id": "123456789012345678",
    "submitter_user_id": "223456789012345678",
    "channel_id": "323456789012345678",
}


def make_lead(
    *,
    message_id: str,
    priority: HumanLeadPriority,
    hypothesis: str = "Possible financing deterioration",
) -> HumanResearchLead:
    return HumanResearchLead.from_submission(
        **{**IDS, "discord_message_id": message_id},
        submitted_at=NOW,
        ticker="XYZ",
        hypothesis=hypothesis,
        urls=("https://www.sec.gov/Archives/example",),
        priority=priority,
    )


def test_queue_suppresses_equivalent_pending_leads() -> None:
    queue = MemoryHumanLeadQueue()
    first = queue.enqueue(
        make_lead(message_id="123456789012345678", priority=HumanLeadPriority.NORMAL),
        now=NOW,
    )
    duplicate = queue.enqueue(
        make_lead(message_id="123456789012345679", priority=HumanLeadPriority.NORMAL),
        now=NOW + timedelta(seconds=1),
    )

    assert first.status is HumanLeadStatus.QUEUED
    assert duplicate.status is HumanLeadStatus.DUPLICATE
    assert queue.pending_count() == 1
    assert queue.events(str(duplicate.lead_id))[-1].status is HumanLeadStatus.DUPLICATE


def test_high_priority_lead_claims_before_older_low_priority_work() -> None:
    queue = MemoryHumanLeadQueue()
    low = make_lead(message_id="123456789012345678", priority=HumanLeadPriority.LOW)
    high = make_lead(
        message_id="123456789012345679",
        priority=HumanLeadPriority.HIGH,
        hypothesis="Possible going-concern deterioration",
    )
    queue.enqueue(low, now=NOW)
    queue.enqueue(high, now=NOW + timedelta(seconds=1))

    claimed = queue.claim(now=NOW + timedelta(seconds=2))

    assert claimed is not None
    assert claimed.lead_id == high.lead_id
    assert claimed.status is HumanLeadStatus.ANALYZING
    assert claimed.attempts == 1


def test_recreated_queue_restores_lead_without_duplicate_claim() -> None:
    queue = MemoryHumanLeadQueue()
    lead = queue.enqueue(
        make_lead(message_id="123456789012345678", priority=HumanLeadPriority.NORMAL),
        now=NOW,
    )
    claimed = queue.claim(now=NOW + timedelta(seconds=2))
    assert claimed is not None

    restored = MemoryHumanLeadQueue((claimed,))

    assert restored.claim(now=NOW + timedelta(seconds=3)) is None
    assert restored.events(str(lead.lead_id))[-1].status is HumanLeadStatus.ANALYZING
