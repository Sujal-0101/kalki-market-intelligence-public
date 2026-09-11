"""Disposable PostgreSQL gate for immutable Phase 43 contradiction receipts."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import psycopg
import pytest

from kalki_market_intelligence.database import DatabaseOptions, DatabaseRuntime
from kalki_market_intelligence.forensics.contradiction_store import (
    PostgresContradictionStore,
)
from kalki_market_intelligence.forensics.contradictions import (
    ClaimUnderReview,
    ContradictionFact,
    ContradictionFactKind,
    ContradictionFactUnit,
    ContradictionFamily,
    ContradictionPredicate,
    ContradictionReceipt,
    check_deterministic_contradiction,
)
from kalki_market_intelligence.web.repository import PostgresResearchRepository

GATE_PASSWORD_FILE = os.environ.get("KALKI_CONTRADICTION_GATE_PASSWORD_FILE")
GATE_PORT = int(os.environ.get("KALKI_CONTRADICTION_GATE_PORT", "55449"))
NOW = datetime(2026, 9, 7, 15, 0, tzinfo=UTC)


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


def _receipt() -> ContradictionReceipt:
    claim = ClaimUnderReview(
        claim_id=UUID("43000000-0000-4000-8000-000000000101"),
        issuer_cik="0000000043",
        family=ContradictionFamily.LIQUIDITY,
        predicate=ContradictionPredicate.CASH_AT_LEAST_CURRENT_LIABILITIES,
        asserted_truth=True,
        comparison_scope_id="balance-sheet:2026-06-30",
        as_of_date=date(2026, 6, 30),
        available_at=NOW - timedelta(minutes=4),
        retrieved_at=NOW - timedelta(minutes=3),
        source_record_id="xbrl-liquidity:0000000043-26-000001",
        source_content_sha256="43" * 32,
        evidence_ids=(UUID("43000000-0000-4000-8001-000000000101"),),
    )
    facts = (
        ContradictionFact(
            fact_id=UUID("43000000-0000-4000-8000-000000000102"),
            issuer_cik=claim.issuer_cik,
            kind=ContradictionFactKind.CASH,
            value=Decimal("100"),
            unit=ContradictionFactUnit.CURRENCY,
            currency="USD",
            comparison_scope_id=claim.comparison_scope_id,
            as_of_date=claim.as_of_date,
            available_at=NOW - timedelta(minutes=2),
            retrieved_at=NOW - timedelta(minutes=1),
            source_record_id="companyfacts-2026q2",
            source_content_sha256="44" * 32,
            evidence_ids=(UUID("43000000-0000-4000-8001-000000000102"),),
        ),
        ContradictionFact(
            fact_id=UUID("43000000-0000-4000-8000-000000000103"),
            issuer_cik=claim.issuer_cik,
            kind=ContradictionFactKind.CURRENT_LIABILITIES,
            value=Decimal("90"),
            unit=ContradictionFactUnit.CURRENCY,
            currency="USD",
            comparison_scope_id=claim.comparison_scope_id,
            as_of_date=claim.as_of_date,
            available_at=NOW - timedelta(minutes=2),
            retrieved_at=NOW - timedelta(minutes=1),
            source_record_id="companyfacts-2026q2",
            source_content_sha256="44" * 32,
            evidence_ids=(UUID("43000000-0000-4000-8001-000000000103"),),
        ),
    )
    return check_deterministic_contradiction(claim, facts, knowledge_cutoff_at=NOW)


@pytest.mark.skipif(
    GATE_PASSWORD_FILE is None,
    reason="Contradiction receipt PostgreSQL gate is not running",
)
def test_receipt_replay_cutoff_schema_mutation_and_least_privilege() -> None:
    receipt = _receipt()
    runtime = _runtime()
    runtime.open()
    try:
        store = PostgresContradictionStore(runtime.connection)
        assert store.append_receipt(receipt) == receipt
        assert store.append_receipt(receipt) == receipt
        assert (
            store.receipt_at_cutoff(
                receipt.receipt_id,
                knowledge_cutoff_at=NOW - timedelta(seconds=1),
            )
            is None
        )
        assert (
            store.receipt_at_cutoff(
                receipt.receipt_id,
                knowledge_cutoff_at=NOW,
            )
            == receipt
        )
        assert store.receipts_for_issuer(
            cik="43",
            knowledge_cutoff_at=NOW,
        ) == (receipt,)
        with pytest.raises(ValueError, match="timezone-aware"):
            store.receipts_for_issuer(cik="43", knowledge_cutoff_at=NOW.replace(tzinfo=None))
        with runtime.connection() as connection:
            rows = connection.execute(
                """
                SELECT receipt_id, canonical_cik, fact_count, consumed_fact_count, record
                FROM research_contradiction_receipts
                """
            ).fetchall()
        assert len(rows) == 1
        assert rows[0]["receipt_id"] == receipt.receipt_id
        assert rows[0]["canonical_cik"] == "0000000043"
        assert rows[0]["fact_count"] == 2
        assert rows[0]["consumed_fact_count"] == 2
        assert rows[0]["record"] == receipt.model_dump(mode="json")
        assert not set(rows[0]["record"]) & {
            "prompt",
            "response",
            "human_hypothesis",
            "publication",
            "exception",
        }
        operations = PostgresResearchRepository(runtime.connection).get_convergence_operations()
        assert operations is not None
        assert operations.receipt_count == 1
        assert operations.families[0].name == "LIQUIDITY"
        assert operations.dispositions[0].name == "SUPPORTED"
        assert operations.sources[0].name == "XBRL_LIQUIDITY"
        assert not hasattr(operations, "receipts")
    finally:
        runtime.close()

    with psycopg.connect(
        host="127.0.0.1", port=GATE_PORT, dbname="kalki_test", user="postgres"
    ) as owner:
        with pytest.raises(psycopg.errors.RaiseException, match="closed JSON schema"):
            owner.execute(
                """
                INSERT INTO research_contradiction_receipts
                SELECT '43000000-0000-4000-8000-000000000199', claim_id,
                       canonical_cik, family, predicate, asserted_truth,
                       comparison_scope_id, claim_as_of_date, claim_available_at,
                       claim_retrieved_at, knowledge_cutoff_at, disposition,
                       observed_truth, reason, fact_count, consumed_fact_count,
                       repeat('9', 64), rule_version,
                       jsonb_set(record, '{receipt_id}',
                           '"43000000-0000-4000-8000-000000000199"')
                           || '{"private_human":"forbidden"}'::jsonb
                FROM research_contradiction_receipts LIMIT 1
                """
            )
        owner.rollback()
        with pytest.raises(psycopg.errors.RaiseException, match="point-in-time lineage"):
            owner.execute(
                """
                INSERT INTO research_contradiction_receipts
                SELECT '43000000-0000-4000-8000-000000000198', claim_id,
                       canonical_cik, family, predicate, asserted_truth,
                       comparison_scope_id, claim_as_of_date, claim_available_at,
                       claim_retrieved_at, knowledge_cutoff_at, disposition,
                       observed_truth, reason, fact_count, consumed_fact_count,
                       repeat('8', 64), rule_version,
                       jsonb_set(
                           jsonb_set(
                               jsonb_set(record, '{receipt_id}',
                                   '"43000000-0000-4000-8000-000000000198"'),
                               '{receipt_sha256}', to_jsonb(repeat('8', 64))
                           ),
                           '{facts,0,retrieved_at}',
                           '"2026-09-07T15:00:01Z"'
                       )
                FROM research_contradiction_receipts LIMIT 1
                """
            )
        owner.rollback()
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            owner.execute("UPDATE research_contradiction_receipts SET family = family")
        owner.rollback()
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            owner.execute("TRUNCATE research_contradiction_receipts")
        owner.rollback()

    with psycopg.connect(
        host="127.0.0.1", port=GATE_PORT, dbname="kalki_test", user="kalki_app"
    ) as application:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            application.execute("DELETE FROM research_contradiction_receipts")
