"""Disposable PostgreSQL gate for private append-only engineering measurements."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from kalki_market_intelligence.radar.measurements import (
    EngineeringMeasurementReceipt,
    EngineeringMetricName,
    FilingLatencyReceipt,
    accepted_metric_definitions,
    build_filing_latency_receipt,
    build_ratio_measurement,
)
from kalki_market_intelligence.radar.store import PostgresRadarStore
from kalki_market_intelligence.web.repository import PostgresResearchRepository

GATE_PORT = int(os.environ.get("KALKI_MEASUREMENT_GATE_PORT", "55449"))
GATE_ENABLED = os.environ.get("KALKI_MEASUREMENT_GATE_ENABLED") == "1"
NOW = datetime(2026, 8, 31, 16, tzinfo=UTC)
ACCESSION = "0000005001-26-000001"


def _connect(*, user: str) -> psycopg.Connection[tuple[object, ...]]:
    return psycopg.connect(host="127.0.0.1", port=GATE_PORT, dbname="kalki_test", user=user)


def _connect_dict(*, user: str) -> psycopg.Connection[dict[str, object]]:
    return psycopg.connect(
        host="127.0.0.1",
        port=GATE_PORT,
        dbname="kalki_test",
        user=user,
        row_factory=dict_row,
    )


def _insert_measurement(
    connection: psycopg.Connection[tuple[object, ...]],
    receipt: EngineeringMeasurementReceipt,
    *,
    record: dict[str, object] | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO research_engineering_measurements (
            receipt_id, metric_name, metric_version, definition_sha256,
            window_started_at, window_ended_at, measured_at, availability,
            unavailable_reason, coverage_started_at, sample_count, numerator,
            denominator, scaled_value_millionths, minimum_value, p50_value,
            p90_value, p95_value, maximum_value, gauge_value, record
        ) VALUES (
            %(receipt_id)s, %(metric_name)s, %(measurement_version)s,
            %(definition_sha256)s, %(window_started_at)s, %(window_ended_at)s,
            %(measured_at)s, %(availability)s, %(unavailable_reason)s,
            %(coverage_started_at)s, %(sample_count)s, %(numerator)s,
            %(denominator)s, %(scaled_value_millionths)s, %(minimum_value)s,
            %(p50_value)s, %(p90_value)s, %(p95_value)s, %(maximum_value)s,
            %(gauge_value)s, %(record)s
        )
        """,
        {
            **receipt.model_dump(),
            "record": Jsonb(record or receipt.model_dump(mode="json")),
        },
    )


def _insert_latency(
    connection: psycopg.Connection[tuple[object, ...]], receipt: FilingLatencyReceipt
) -> None:
    connection.execute(
        """
        INSERT INTO research_filing_latency_receipts (
            receipt_id, accession_number, event_lineage_id,
            authoritative_first_known_at, discovered_at, published_at, alerted_at,
            first_known_to_discovery_ms, first_known_to_discovery_reason,
            discovery_to_publication_ms, discovery_to_publication_reason,
            first_known_to_alert_ms, first_known_to_alert_reason, measured_at,
            measurement_version, record
        ) VALUES (
            %(receipt_id)s, %(accession_number)s, %(event_lineage_id)s,
            %(authoritative_first_known_at)s, %(discovered_at)s, %(published_at)s,
            %(alerted_at)s, %(first_discovery_ms)s, %(first_discovery_reason)s,
            %(discovery_publication_ms)s, %(discovery_publication_reason)s,
            %(first_alert_ms)s, %(first_alert_reason)s, %(measured_at)s,
            %(measurement_version)s, %(record)s
        )
        """,
        {
            **receipt.model_dump(),
            "first_discovery_ms": receipt.first_known_to_discovery.value_ms,
            "first_discovery_reason": receipt.first_known_to_discovery.unavailable_reason,
            "discovery_publication_ms": receipt.discovery_to_publication.value_ms,
            "discovery_publication_reason": (receipt.discovery_to_publication.unavailable_reason),
            "first_alert_ms": receipt.first_known_to_alert.value_ms,
            "first_alert_reason": receipt.first_known_to_alert.unavailable_reason,
            "record": Jsonb(receipt.model_dump(mode="json")),
        },
    )


@pytest.mark.skipif(not GATE_ENABLED, reason="measurement PostgreSQL gate is not running")
def test_definition_catalog_measurement_shape_and_closed_record_reconcile() -> None:
    receipt = build_ratio_measurement(
        metric_name=EngineeringMetricName.ANALYST_TIMEOUT_RATE,
        window_started_at=NOW - timedelta(hours=24),
        window_ended_at=NOW,
        measured_at=NOW,
        numerator=2,
        denominator=10,
    )
    with _connect(user="kalki_app") as application:
        _insert_measurement(application, receipt)
        definitions = application.execute(
            """
            SELECT metric_name, definition_sha256
            FROM research_engineering_metric_definitions ORDER BY metric_name
            """
        ).fetchall()
        assert definitions == [
            (item.metric_name.value, item.definition_sha256)
            for item in accepted_metric_definitions()
        ]

    rogue_record = {
        **receipt.model_dump(mode="json"),
        "receipt_id": "30000000-0000-4000-8000-000000000003",
        "prompt": "must never persist",
    }
    rogue = receipt.model_construct(
        **{
            **receipt.__dict__,
            "receipt_id": UUID("30000000-0000-4000-8000-000000000003"),
        }
    )
    with _connect(user="kalki_app") as application:
        with pytest.raises(psycopg.errors.RaiseException, match="outside the closed contract"):
            _insert_measurement(application, rogue, record=rogue_record)


@pytest.mark.skipif(not GATE_ENABLED, reason="measurement PostgreSQL gate is not running")
def test_unknown_first_known_latency_stays_unavailable_and_history_is_immutable() -> None:
    discovered_at = NOW - timedelta(hours=2)
    with _connect(user="postgres") as owner:
        owner.execute(
            """
            INSERT INTO research_candidates (
                accession_number, cik, company_name, ticker, exchange, filing_form,
                filed_at, source_url, discovered_at, status, attempts, updated_at
            ) VALUES (
                %(accession)s, '5001', 'Synthetic measurement issuer', 'MEAS',
                'Test', '8-K', %(filed_at)s,
                'https://www.sec.gov/Archives/edgar/data/5001/000000500126000001/0000005001-26-000001.txt',
                %(discovered_at)s, 'skipped', 1, %(discovered_at)s
            )
            """,
            {
                "accession": ACCESSION,
                "filed_at": discovered_at - timedelta(minutes=1),
                "discovered_at": discovered_at,
            },
        )

    receipt = build_filing_latency_receipt(
        accession_number=ACCESSION,
        event_lineage_id=None,
        authoritative_first_known_at=None,
        discovered_at=discovered_at,
        published_at=None,
        alerted_at=None,
        measured_at=NOW,
    )
    with _connect(user="kalki_app") as application:
        _insert_latency(application, receipt)
        row = application.execute(
            """
            SELECT first_known_to_discovery_ms, first_known_to_discovery_reason,
                   discovery_to_publication_ms, discovery_to_publication_reason,
                   first_known_to_alert_ms, first_known_to_alert_reason
            FROM research_filing_latency_receipts WHERE receipt_id = %s
            """,
            (receipt.receipt_id,),
        ).fetchone()
        assert row == (
            None,
            "authoritative_first_known_unavailable",
            None,
            "publication_unavailable",
            None,
            "authoritative_first_known_unavailable",
        )
        application.commit()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            application.execute(
                "UPDATE research_filing_latency_receipts SET measured_at = measured_at"
            )

    with _connect(user="postgres") as owner:
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            owner.execute("UPDATE research_engineering_measurements SET measured_at = measured_at")
        owner.rollback()
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            owner.execute("TRUNCATE research_filing_latency_receipts")


@pytest.mark.skipif(not GATE_ENABLED, reason="measurement PostgreSQL gate is not running")
def test_migration_state_and_least_privilege_are_exact() -> None:
    with _connect(user="postgres") as owner:
        result = owner.execute(
            """
            SELECT
                (SELECT count(*) FROM research_engineering_measurement_state),
                (SELECT count(*) FROM research_engineering_metric_definitions),
                (SELECT count(*) FROM research_engineering_measurements),
                (SELECT count(*) FROM research_filing_latency_receipts),
                has_table_privilege('kalki_app', 'research_engineering_measurements', 'INSERT'),
                has_table_privilege('kalki_app', 'research_engineering_measurements', 'UPDATE'),
                has_table_privilege('kalki_app', 'research_filing_latency_receipts', 'DELETE'),
                (SELECT count(*) FROM schema_migrations
                 WHERE version = '0021_engineering_measurements')
            """
        ).fetchone()
        assert result == (1, 20, 1, 1, True, False, False, 1)


@pytest.mark.skipif(not GATE_ENABLED, reason="measurement PostgreSQL gate is not running")
def test_runtime_generation_is_idempotent_and_private_projection_is_bounded() -> None:
    with _connect_dict(user="kalki_app") as application:
        state = application.execute(
            "SELECT started_at FROM research_engineering_measurement_state WHERE singleton"
        ).fetchone()
    assert state is not None
    started_at = state["started_at"]
    assert isinstance(started_at, datetime)
    observed_at = started_at + timedelta(minutes=1)
    store = PostgresRadarStore(lambda: _connect_dict(user="kalki_app"))

    first = store.generate_engineering_measurements(now=observed_at)
    second = store.generate_engineering_measurements(now=observed_at)
    too_soon = store.generate_engineering_measurements(now=observed_at + timedelta(minutes=15))
    snapshot = PostgresResearchRepository(
        lambda: _connect_dict(user="kalki_app")
    ).get_engineering_measurements()

    assert first == second == 34
    assert too_soon == 0
    assert snapshot is not None
    assert [len(window.measurements) for window in snapshot.windows] == [14, 14]
    assert len(snapshot.gauges) == 6
    with _connect(user="postgres") as owner:
        duplicate_ids = owner.execute(
            """
            SELECT count(*) - count(DISTINCT receipt_id)
            FROM research_engineering_measurements
            """
        ).fetchone()
    assert duplicate_ids == (0,)
