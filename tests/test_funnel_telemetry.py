"""Phase 34 bounded telemetry contracts and deployment wiring."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from kalki_market_intelligence.forensics.detectors import ForensicStatus
from kalki_market_intelligence.radar.telemetry import (
    DetectorReceipt,
    PipelineEvent,
    PipelineStage,
)

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 27, 20, tzinfo=UTC)
RUN_ID = UUID("10000000-0000-4000-8000-000000000001")
ACCESSION = "0000320193-26-000001"


def test_pipeline_events_are_content_free_and_context_bound() -> None:
    poll = PipelineEvent(
        event_id=UUID("10000000-0000-4000-8000-000000000002"),
        occurred_at=NOW,
        stage=PipelineStage.SEC_POLL_ATTEMPTED,
        run_id=RUN_ID,
    )
    failed = PipelineEvent(
        event_id=UUID("10000000-0000-4000-8000-000000000003"),
        occurred_at=NOW,
        stage=PipelineStage.CANDIDATE_FAILED,
        run_id=RUN_ID,
        accession_number=ACCESSION,
        failure_category="analyst",
    )

    assert poll.model_dump()["run_id"] == RUN_ID
    assert failed.failure_category == "analyst"
    assert "prompt" not in PipelineEvent.model_json_schema()["properties"]
    assert "response" not in PipelineEvent.model_json_schema()["properties"]
    with pytest.raises(ValidationError, match="run identity"):
        PipelineEvent(
            event_id=UUID("10000000-0000-4000-8000-000000000004"),
            occurred_at=NOW,
            stage=PipelineStage.SEC_POLL_ATTEMPTED,
        )
    with pytest.raises(ValidationError, match="bounded category"):
        PipelineEvent(
            event_id=UUID("10000000-0000-4000-8000-000000000005"),
            occurred_at=NOW,
            stage=PipelineStage.CANDIDATE_RETRY_WAIT,
            accession_number=ACCESSION,
        )


def test_detector_receipts_fail_closed_on_invocation_and_contribution() -> None:
    receipt = DetectorReceipt(
        receipt_id=UUID("20000000-0000-4000-8000-000000000001"),
        accession_number=ACCESSION,
        observed_at=NOW,
        detector_name="going_concern",
        invoked=True,
        status=ForensicStatus.POSITIVE,
        contributed_to_escalation=False,
    )
    assert receipt.status is ForensicStatus.POSITIVE

    with pytest.raises(ValidationError, match="not invoked"):
        DetectorReceipt.model_validate(
            receipt.model_dump() | {"invoked": False, "status": ForensicStatus.POSITIVE.value}
        )
    with pytest.raises(ValidationError, match="positive detector"):
        DetectorReceipt(
            receipt_id=UUID("20000000-0000-4000-8000-000000000002"),
            accession_number=ACCESSION,
            observed_at=NOW,
            detector_name="liquidity",
            invoked=True,
            status=ForensicStatus.UNKNOWN,
            contributed_to_escalation=True,
        )


def test_migration_backup_restore_and_fresh_compose_include_telemetry() -> None:
    migration = (ROOT / "migrations/0011_funnel_telemetry.sql").read_text(encoding="utf-8")
    compose = (ROOT / "compose.production.yaml").read_text(encoding="utf-8")
    backup = (ROOT / "scripts/backup-postgres.sh").read_text(encoding="utf-8")
    restore = (ROOT / "scripts/restore-postgres-gate.sh").read_text(encoding="utf-8")

    assert "CREATE TABLE research_funnel_telemetry_state" in migration
    assert "CREATE TABLE research_pipeline_events" in migration
    assert "CREATE TABLE research_detector_receipts" in migration
    assert "reject_append_only_mutation" in migration
    assert "GRANT SELECT, INSERT ON research_pipeline_events" in migration
    assert "0011_funnel_telemetry.sql" in compose
    for table in (
        "research_funnel_telemetry_state",
        "research_pipeline_events",
        "research_detector_receipts",
    ):
        assert table in backup
        assert table in restore
    assert "0011_funnel_telemetry" in restore
