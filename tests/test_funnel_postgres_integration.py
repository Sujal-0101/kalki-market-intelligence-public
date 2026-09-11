"""Opt-in Phase 34 aggregate query reconciliation against disposable PostgreSQL."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from kalki_market_intelligence.database import DatabaseOptions, DatabaseRuntime
from kalki_market_intelligence.web.repository import PostgresResearchRepository

PASSWORD_FILE = os.environ.get("KALKI_FUNNEL_GATE_PASSWORD_FILE")
PORT = int(os.environ.get("KALKI_FUNNEL_GATE_PORT", "55440"))

pytestmark = pytest.mark.skipif(
    PASSWORD_FILE is None,
    reason="Phase 34 funnel PostgreSQL gate is not running",
)


def test_funnel_query_reconciles_seeded_direct_counts_and_is_bounded() -> None:
    assert PASSWORD_FILE is not None
    runtime = DatabaseRuntime(
        DatabaseOptions(
            host="127.0.0.1",
            port=PORT,
            name="kalki",
            user="kalki_app",
            password_file=Path(PASSWORD_FILE),
            minimum_pool_size=1,
            maximum_pool_size=1,
        )
    )
    runtime.open()
    try:
        repository = PostgresResearchRepository(runtime.connection)
        started = time.perf_counter()
        snapshot = repository.get_funnel_snapshot()
        elapsed = time.perf_counter() - started
    finally:
        runtime.close()

    assert snapshot is not None
    assert elapsed < 1.0
    assert len(snapshot.windows) == 3
    window = snapshot.windows[0]
    assert window.hours == 24
    assert not window.telemetry_complete
    assert window.sec_polls_attempted == window.terminal_sec_polls == 1
    assert window.unterminated_sec_polls == 0
    assert window.completed_sec_polls == 1
    assert window.discovered_rows == window.unique_candidates == 1
    assert window.processing_transitions == 1
    assert window.retry_wait_transitions == window.failed_transitions == 0
    assert window.skipped_transitions == window.retained_transitions == 1
    assert window.retrieved == window.parsed == window.normalized == 1
    assert window.analyst_invocations == window.qwen_attempts == 1
    assert window.valid_contracts == window.latency_sample_size == 1
    assert window.latency_sample_label == "small_n"
    assert window.latency_p50_ms == window.latency_p95_ms == 1_000
    assert window.published == window.discord_sent == 1
    assert window.human_leads == window.human_results == window.human_delivered == 1
    assert window.failure_categories == ()
    going_concern = next(item for item in window.detectors if item.name == "going_concern")
    assert going_concern.invoked == going_concern.positive == 1
    assert going_concern.escalation_contributions == 0
    assert snapshot.current.skipped == snapshot.current.retained == 1
    assert snapshot.current.backlog_depth == 0
