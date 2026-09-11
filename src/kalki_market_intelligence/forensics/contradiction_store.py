"""Private append-only persistence for deterministic contradiction receipts."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from psycopg.types.json import Jsonb

from kalki_market_intelligence.database import ConnectionFactory
from kalki_market_intelligence.forensics.contradictions import (
    ContradictionReceipt,
    check_deterministic_contradiction,
)


class ContradictionReceiptReplayConflict(RuntimeError):
    """An immutable receipt identity already has different content."""


class PostgresContradictionStore:
    """Persist and read closed receipts without exposing a public projection."""

    def __init__(self, connection: ConnectionFactory) -> None:
        self._connection = connection

    def append_receipt(self, receipt: ContradictionReceipt) -> ContradictionReceipt:
        """Append one recomputed receipt or accept its exact replay."""

        receipt = ContradictionReceipt.model_validate(receipt.model_dump(mode="json"))
        expected = check_deterministic_contradiction(
            receipt.claim,
            receipt.facts,
            knowledge_cutoff_at=receipt.knowledge_cutoff_at,
        )
        if expected != receipt:
            raise ValueError("contradiction receipt does not recompute before persistence")
        with self._connection() as connection:
            inserted = connection.execute(
                """
                INSERT INTO research_contradiction_receipts (
                    receipt_id, claim_id, canonical_cik, family, predicate,
                    asserted_truth, comparison_scope_id, claim_as_of_date,
                    claim_available_at, claim_retrieved_at, knowledge_cutoff_at,
                    disposition, observed_truth, reason, fact_count,
                    consumed_fact_count, receipt_sha256, rule_version, record
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                ) ON CONFLICT (receipt_id) DO NOTHING
                RETURNING record
                """,
                (
                    receipt.receipt_id,
                    receipt.claim.claim_id,
                    receipt.claim.issuer_cik.zfill(10),
                    receipt.claim.family.value,
                    receipt.claim.predicate.value,
                    receipt.claim.asserted_truth,
                    receipt.claim.comparison_scope_id,
                    receipt.claim.as_of_date,
                    receipt.claim.available_at,
                    receipt.claim.retrieved_at,
                    receipt.knowledge_cutoff_at,
                    receipt.disposition.value,
                    receipt.observed_truth,
                    receipt.reason.value,
                    len(receipt.facts),
                    len(receipt.consumed_fact_ids),
                    receipt.receipt_sha256,
                    receipt.rule_version,
                    Jsonb(receipt.model_dump(mode="json")),
                ),
            ).fetchone()
            if inserted is not None:
                return receipt
            existing = connection.execute(
                "SELECT record FROM research_contradiction_receipts WHERE receipt_id = %s",
                (receipt.receipt_id,),
            ).fetchone()
            if existing is None:
                raise ContradictionReceiptReplayConflict(
                    "contradiction receipt identity collided with immutable history"
                )
            stored = ContradictionReceipt.model_validate(existing["record"])
            if stored != receipt:
                raise ContradictionReceiptReplayConflict(
                    "contradiction receipt identity already has different immutable content"
                )
            return stored

    def receipt_at_cutoff(
        self,
        receipt_id: UUID,
        *,
        knowledge_cutoff_at: datetime,
    ) -> ContradictionReceipt | None:
        """Return a receipt only when its complete decision existed by the cutoff."""

        cutoff = _utc_cutoff(knowledge_cutoff_at)
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT record FROM research_contradiction_receipts
                WHERE receipt_id = %s
                  AND claim_available_at <= %s
                  AND claim_retrieved_at <= %s
                  AND knowledge_cutoff_at <= %s
                """,
                (receipt_id, cutoff, cutoff, cutoff),
            ).fetchone()
        if row is None:
            return None
        return ContradictionReceipt.model_validate(row["record"])

    def receipts_for_issuer(
        self,
        *,
        cik: str,
        knowledge_cutoff_at: datetime,
        limit: int = 100,
    ) -> tuple[ContradictionReceipt, ...]:
        """Return bounded private history available by one point-in-time cutoff."""

        if not cik.isascii() or not cik.isdigit() or not 1 <= len(cik) <= 10:
            raise ValueError("contradiction receipt lookup requires a numeric CIK")
        if not 1 <= limit <= 500:
            raise ValueError("contradiction receipt limit must be between one and 500")
        cutoff = _utc_cutoff(knowledge_cutoff_at)
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT record FROM research_contradiction_receipts
                WHERE canonical_cik = %s
                  AND claim_available_at <= %s
                  AND claim_retrieved_at <= %s
                  AND knowledge_cutoff_at <= %s
                ORDER BY knowledge_cutoff_at DESC, receipt_id
                LIMIT %s
                """,
                (cik.zfill(10), cutoff, cutoff, cutoff, limit),
            ).fetchall()
        return tuple(ContradictionReceipt.model_validate(row["record"]) for row in rows)


def _utc_cutoff(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("contradiction knowledge cutoff must be timezone-aware")
    return value.astimezone(UTC)
