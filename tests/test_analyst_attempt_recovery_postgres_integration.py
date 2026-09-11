"""Disposable PostgreSQL gate for restart-safe analyst-attempt receipts."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from kalki_market_intelligence.analysis.attempts import (
    AnalystAttemptOrigin,
    AnalystAttemptReceipt,
    AnalystAttemptStart,
    AnalystTerminalDisposition,
    AnalystWorkContext,
)
from kalki_market_intelligence.analysis.contracts import AnalystRole
from kalki_market_intelligence.database import DatabaseOptions, DatabaseRuntime
from kalki_market_intelligence.radar.contracts import FilingCandidate
from kalki_market_intelligence.radar.store import PostgresRadarStore
from kalki_market_intelligence.research.intake import HumanLeadStatus, HumanResearchLead

GATE_PASSWORD_FILE = os.environ.get("KALKI_ATTEMPT_GATE_PASSWORD_FILE")
GATE_PORT = int(os.environ.get("KALKI_ATTEMPT_GATE_PORT", "55447"))
NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)
STARTED_AT = NOW - timedelta(days=5)
DIGEST = "a" * 64


def _runtime() -> DatabaseRuntime:
    assert GATE_PASSWORD_FILE is not None
    return DatabaseRuntime(
        DatabaseOptions(
            host="127.0.0.1",
            port=GATE_PORT,
            name="kalki_test",
            user="kalki_app",
            password_file=Path(GATE_PASSWORD_FILE),
            minimum_pool_size=1,
            maximum_pool_size=1,
        )
    )


def _candidate(accession_number: str, *, discovered_at: datetime) -> FilingCandidate:
    compact = accession_number.replace("-", "")
    return FilingCandidate(
        accession_number=accession_number,
        cik="320193",
        company_name="Recovery Fixture",
        ticker="TEST",
        exchange="Nasdaq",
        filing_form="8-K",
        filed_at=discovered_at - timedelta(hours=1),
        source_url=(
            f"https://www.sec.gov/Archives/edgar/data/320193/{compact}/{accession_number}.txt"
        ),
        discovered_at=discovered_at,
    )


def _attempt(context: AnalystWorkContext) -> AnalystAttemptStart:
    return AnalystAttemptStart(
        attempt_id=uuid4(),
        invocation_id=uuid4(),
        context=context,
        provider_name="ollama-loopback",
        model_name="qwen3:4b",
        model_digest=DIGEST,
        role=AnalystRole.CATALYST_ANALYST,
        attempt_number=1,
        started_at=STARTED_AT,
        input_evidence_count=1,
        input_evidence_characters=100,
        system_prompt_characters=1_000,
        user_prompt_characters=1_000,
        context_tokens=4_096,
        maximum_output_tokens=512,
    )


@pytest.mark.skipif(
    GATE_PASSWORD_FILE is None,
    reason="Analyst-attempt recovery PostgreSQL gate is not running",
)
def test_stale_attempts_close_and_only_active_retryable_work_is_requeued() -> None:
    runtime = _runtime()
    runtime.open()
    try:
        store = PostgresRadarStore(runtime.connection)
        active = _candidate("0000320193-26-000001", discovered_at=STARTED_AT)
        terminal = _candidate(
            "0000320193-26-000002", discovered_at=STARTED_AT + timedelta(seconds=1)
        )
        store.discover((active, terminal))
        claimed_active = store.claim(now=STARTED_AT)
        claimed_terminal = store.claim(now=STARTED_AT + timedelta(seconds=1))
        assert claimed_active is not None and claimed_terminal is not None

        active_start = _attempt(
            AnalystWorkContext(
                origin=AnalystAttemptOrigin.CANDIDATE,
                candidate_accession_number=active.accession_number,
                ticker=active.ticker,
                cik=active.cik,
                accession_number=active.accession_number,
                filing_form=active.filing_form,
                work_attempt=1,
                runtime_retry_eligible=True,
            )
        )
        terminal_start = _attempt(
            AnalystWorkContext(
                origin=AnalystAttemptOrigin.CANDIDATE,
                candidate_accession_number=terminal.accession_number,
                ticker=terminal.ticker,
                cik=terminal.cik,
                accession_number=terminal.accession_number,
                filing_form=terminal.filing_form,
                work_attempt=1,
                runtime_retry_eligible=True,
            )
        )
        store.start_analyst_attempt(active_start)
        store.start_analyst_attempt(terminal_start)
        with runtime.connection() as connection:
            connection.execute(
                "UPDATE research_candidates SET status = 'skipped' WHERE accession_number = %s",
                (terminal.accession_number,),
            )

        lead = HumanResearchLead.from_submission(
            discord_message_id="12345678901234567",
            submitter_user_id="22345678901234567",
            channel_id="32345678901234567",
            submitted_at=STARTED_AT,
            ticker="TEST",
            cik="320193",
            hypothesis="Test interrupted private research work.",
        )
        store.enqueue_human_lead(lead, now=STARTED_AT)
        claimed_lead = store.claim_human_lead(now=STARTED_AT)
        assert claimed_lead is not None
        human_start = _attempt(
            AnalystWorkContext(
                origin=AnalystAttemptOrigin.HUMAN,
                lead_id=lead.lead_id,
                ticker="TEST",
                cik="320193",
                accession_number=active.accession_number,
                filing_form="8-K",
                work_attempt=1,
                runtime_retry_eligible=False,
            )
        )
        store.start_analyst_attempt(human_start)

        assert store.requeue_stale_processing(now=STARTED_AT + timedelta(minutes=20)) == 0
        with runtime.connection() as connection:
            premature = connection.execute(
                "SELECT count(*) AS count FROM research_analyst_attempts WHERE state = 'started'"
            ).fetchone()
        assert premature == {"count": 3}

        assert store.requeue_stale_processing(now=NOW) == 1

        with runtime.connection() as connection:
            rows = connection.execute(
                """
                SELECT attempt_id, state, record FROM research_analyst_attempts
                ORDER BY started_at, attempt_id
                """
            ).fetchall()
            candidate_rows = connection.execute(
                "SELECT accession_number, status FROM research_candidates ORDER BY accession_number"
            ).fetchall()
            human_row = connection.execute(
                "SELECT status FROM research_human_leads WHERE lead_id = %s",
                (lead.lead_id,),
            ).fetchone()
            event_row = connection.execute(
                """
                SELECT status, detail FROM research_human_lead_events
                WHERE lead_id = %s ORDER BY occurred_at DESC LIMIT 1
                """,
                (lead.lead_id,),
            ).fetchone()

        receipts = {
            row["attempt_id"]: AnalystAttemptReceipt.model_validate(row["record"]) for row in rows
        }
        assert {row["state"] for row in rows} == {"completed"}
        assert receipts[active_start.attempt_id].terminal_disposition is (
            AnalystTerminalDisposition.RETRY_PENDING
        )
        assert receipts[terminal_start.attempt_id].terminal_disposition is (
            AnalystTerminalDisposition.PROVIDER_ERROR
        )
        assert receipts[human_start.attempt_id].terminal_disposition is (
            AnalystTerminalDisposition.PROVIDER_ERROR
        )
        assert receipts[human_start.attempt_id].response_sha256 is None
        assert candidate_rows == [
            {"accession_number": active.accession_number, "status": "retry_wait"},
            {"accession_number": terminal.accession_number, "status": "skipped"},
        ]
        assert human_row == {"status": HumanLeadStatus.FAILED.value}
        assert event_row == {
            "status": HumanLeadStatus.FAILED.value,
            "detail": "interrupted analyst invocation lease expired",
        }
    finally:
        runtime.close()
