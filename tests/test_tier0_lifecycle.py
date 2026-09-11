"""Restart/replay fixtures for deterministic Tier-0 decisions."""

from uuid import UUID

from kalki_market_intelligence.forensics import ForensicInput, assess_forensics, choose_tier

ROUTING_EVIDENCE = UUID("42000000-0000-4000-8000-000000000001")


def test_replayed_tier0_decision_is_byte_stable_and_model_free() -> None:
    signals = assess_forensics(ForensicInput(evidence_ids=(ROUTING_EVIDENCE,)))
    first_decision = choose_tier(
        research_relevant=False,
        material_terms=False,
        evidence_ids=(ROUTING_EVIDENCE,),
        forensic_signals=signals,
    )
    replay_decision = choose_tier(
        research_relevant=False,
        material_terms=False,
        evidence_ids=(ROUTING_EVIDENCE,),
        forensic_signals=signals,
    )
    first = first_decision.model_dump_json()
    replay = replay_decision.model_dump_json()
    assert first == replay
    assert '"requires_model":false' in first
    assert ROUTING_EVIDENCE in first_decision.evidence_ids


def test_escalation_replay_retains_same_reason_and_evidence() -> None:
    decision = choose_tier(
        research_relevant=True,
        material_terms=True,
        evidence_ids=(ROUTING_EVIDENCE,),
    )
    replay = choose_tier(
        research_relevant=True,
        material_terms=True,
        evidence_ids=(ROUTING_EVIDENCE,),
    )
    assert decision.model_dump() == replay.model_dump()
