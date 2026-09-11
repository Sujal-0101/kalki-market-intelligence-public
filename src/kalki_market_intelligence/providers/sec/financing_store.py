"""Append-only PostgreSQL persistence for SEC financing intelligence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from psycopg.types.json import Jsonb

from kalki_market_intelligence.database import ConnectionFactory
from kalki_market_intelligence.forensics.financing import (
    FinancingFilingReceipt,
    FinancingTier0Receipt,
)
from kalki_market_intelligence.providers.sec.financing import FinancingDiscoveryCandidate

FINANCING_FORM_PRIORITY = {
    "424B4": 0,
    "424B5": 1,
    "S-1": 2,
    "S-1/A": 3,
    "S-3": 4,
    "S-3/A": 5,
    "424B1": 6,
    "424B3": 7,
    "424B7": 8,
    "8-K": 9,
    "8-K/A": 10,
    "424B2": 11,
}


class FinancingReplayConflict(RuntimeError):
    """An accession conflicts with immutable financing history."""


@dataclass(frozen=True, slots=True)
class ClaimedFinancingJob:
    candidate: FinancingDiscoveryCandidate
    attempt: int


class PostgresFinancingStore:
    def __init__(self, connection: ConnectionFactory) -> None:
        self._connection = connection

    def append(
        self,
        receipt: FinancingFilingReceipt,
        routing: FinancingTier0Receipt,
    ) -> None:
        """Atomically append or verify one immutable receipt/routing pair."""

        with self._connection() as connection:
            self._append_pair(connection, receipt, routing)

    def discover(
        self,
        candidates: tuple[FinancingDiscoveryCandidate, ...],
        *,
        maximum_backlog: int,
    ) -> int:
        if not 1 <= maximum_backlog <= 1_000:
            raise ValueError("financing backlog limit must be between one and 1000")
        inserted = 0
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT count(*) AS count FROM research_financing_jobs
                WHERE status IN ('pending', 'processing', 'retry_wait')
                """
            ).fetchone()
            if row is None:
                raise RuntimeError("financing backlog count is unavailable")
            capacity = maximum_backlog - int(row["count"])
            for candidate in sorted(
                candidates,
                key=lambda item: (
                    FINANCING_FORM_PRIORITY[item.form.value],
                    item.filed_on,
                    item.accession_number,
                ),
            ):
                if capacity <= 0:
                    break
                result = connection.execute(
                    """
                    INSERT INTO research_financing_jobs (
                        accession_number, index_ciks, index_names, form, filed_on,
                        discovered_at, source_index_url, source_index_sha256, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (accession_number) DO NOTHING
                    """,
                    (
                        candidate.accession_number,
                        list(candidate.index_ciks),
                        list(candidate.index_names),
                        candidate.form.value,
                        candidate.filed_on,
                        candidate.discovered_at,
                        str(candidate.source_index_url),
                        candidate.source_index_sha256,
                        candidate.discovered_at,
                    ),
                )
                if result.rowcount:
                    inserted += 1
                    capacity -= 1
                    continue
                stored = connection.execute(
                    """
                    SELECT accession_number, index_ciks, index_names, form, filed_on,
                           discovered_at, source_index_url, source_index_sha256
                    FROM research_financing_jobs WHERE accession_number = %s
                    """,
                    (candidate.accession_number,),
                ).fetchone()
                if stored is None or _discovery_identity(_candidate_from_row(stored)) != (
                    _discovery_identity(candidate)
                ):
                    raise FinancingReplayConflict(
                        "financing discovery conflicts with immutable accession identity"
                    )
        return inserted

    def claim(self, *, now: datetime) -> ClaimedFinancingJob | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT accession_number, index_ciks, index_names, form, filed_on,
                       discovered_at, source_index_url, source_index_sha256, attempts
                FROM research_financing_jobs
                WHERE attempts < 3 AND (
                    status = 'pending' OR (status = 'retry_wait' AND next_attempt_at <= %s)
                )
                ORDER BY array_position(
                    ARRAY[
                        '424B4', '424B5', 'S-1', 'S-1/A', 'S-3', 'S-3/A',
                        '424B1', '424B3', '424B7', '8-K', '8-K/A', '424B2'
                    ]::text[], form
                ), cardinality(index_ciks), filed_on, accession_number
                FOR UPDATE SKIP LOCKED LIMIT 1
                """,
                (now,),
            ).fetchone()
            if row is None:
                return None
            attempt = int(row["attempts"]) + 1
            connection.execute(
                """
                UPDATE research_financing_jobs
                SET status = 'processing', claimed_at = %s, next_attempt_at = NULL,
                    completed_at = NULL, last_error_category = NULL,
                    terminal_reason = NULL, updated_at = %s
                WHERE accession_number = %s
                """,
                (now, now, row["accession_number"]),
            )
        return ClaimedFinancingJob(candidate=_candidate_from_row(row), attempt=attempt)

    def complete(
        self,
        claimed: ClaimedFinancingJob,
        receipt: FinancingFilingReceipt,
        routing: FinancingTier0Receipt,
        *,
        now: datetime,
    ) -> None:
        if claimed.candidate.accession_number != receipt.accession_number:
            raise ValueError("claimed financing accession does not match receipt")
        with self._connection() as connection:
            self._append_pair(connection, receipt, routing)
            result = connection.execute(
                """
                UPDATE research_financing_jobs
                SET status = 'completed', attempts = %s, claimed_at = NULL,
                    completed_at = %s, next_attempt_at = NULL,
                    resolved_issuer_cik = %s, resolved_issuer_name = %s,
                    last_error_category = NULL, terminal_reason = NULL, updated_at = %s
                WHERE accession_number = %s AND status = 'processing' AND attempts = %s
                """,
                (
                    claimed.attempt,
                    now,
                    receipt.issuer_cik,
                    receipt.issuer_name,
                    now,
                    receipt.accession_number,
                    claimed.attempt - 1,
                ),
            )
            if result.rowcount != 1:
                raise RuntimeError("financing job claim is absent or no longer current")

    def complete_no_terms(self, claimed: ClaimedFinancingJob, *, now: datetime) -> None:
        with self._connection() as connection:
            result = connection.execute(
                """
                UPDATE research_financing_jobs
                SET status = 'no_terms', attempts = %s, claimed_at = NULL,
                    completed_at = %s, next_attempt_at = NULL,
                    last_error_category = NULL, terminal_reason = 'no_supported_terms',
                    updated_at = %s
                WHERE accession_number = %s AND status = 'processing' AND attempts = %s
                """,
                (
                    claimed.attempt,
                    now,
                    now,
                    claimed.candidate.accession_number,
                    claimed.attempt - 1,
                ),
            )
            if result.rowcount != 1:
                raise RuntimeError("financing job claim is absent or no longer current")

    def fail(
        self,
        claimed: ClaimedFinancingJob,
        *,
        category: str,
        now: datetime,
        retry_delay: timedelta = timedelta(hours=1),
    ) -> str:
        if category not in {
            "metadata_unavailable",
            "primary_document_error",
            "parse_error",
            "persistence_error",
            "other",
        }:
            raise ValueError("financing failure category is not closed")
        terminal = claimed.attempt >= 3
        status = "failed" if terminal else "retry_wait"
        next_attempt_at = None if terminal else now + retry_delay
        completed_at = now if terminal else None
        with self._connection() as connection:
            result = connection.execute(
                """
                UPDATE research_financing_jobs
                SET status = %s, attempts = %s, claimed_at = NULL,
                    next_attempt_at = %s, completed_at = %s,
                    last_error_category = %s, terminal_reason = NULL, updated_at = %s
                WHERE accession_number = %s AND status = 'processing' AND attempts = %s
                """,
                (
                    status,
                    claimed.attempt,
                    next_attempt_at,
                    completed_at,
                    category,
                    now,
                    claimed.candidate.accession_number,
                    claimed.attempt - 1,
                ),
            )
            if result.rowcount != 1:
                raise RuntimeError("financing job claim is absent or no longer current")
        return status

    def recover_stale(self, *, now: datetime, lease: timedelta = timedelta(minutes=30)) -> int:
        if lease < timedelta(minutes=1):
            raise ValueError("financing claim lease must be at least one minute")
        with self._connection() as connection:
            result = connection.execute(
                """
                UPDATE research_financing_jobs
                SET status = 'retry_wait', claimed_at = NULL, next_attempt_at = %s,
                    completed_at = NULL, last_error_category = 'other',
                    terminal_reason = NULL, updated_at = %s
                WHERE status = 'processing' AND claimed_at < %s AND attempts < 3
                """,
                (now, now, now - lease),
            )
        return result.rowcount

    @staticmethod
    def _append_pair(
        connection: object,
        receipt: FinancingFilingReceipt,
        routing: FinancingTier0Receipt,
    ) -> None:
        if receipt.accession_number != routing.accession_number:
            raise ValueError("financing receipt and routing accession must match")
        if receipt.source_content_sha256 != routing.source_content_sha256:
            raise ValueError("financing receipt and routing source hash must match")
        receipt_record = receipt.model_dump(mode="json")
        routing_record = routing.model_dump(mode="json")
        stored = connection.execute(  # type: ignore[attr-defined]
            """
            SELECT r.record AS receipt_record, t.record AS routing_record
            FROM research_financing_receipts r
            JOIN research_financing_routing_receipts t USING (accession_number)
            WHERE r.accession_number = %s
            """,
            (receipt.accession_number,),
        ).fetchone()
        if stored is not None:
            _validate_replay(stored, receipt_record, routing_record)
            return
        connection.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO research_financing_receipts (
                accession_number, issuer_cik, issuer_name, form, accepted_at,
                retrieved_at, source_url, source_content_sha256, parser_version,
                term_count, record
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (accession_number) DO NOTHING
            """,
            (
                receipt.accession_number,
                receipt.issuer_cik,
                receipt.issuer_name,
                receipt.form.value,
                receipt.accepted_at,
                receipt.retrieved_at,
                str(receipt.source_url),
                receipt.source_content_sha256,
                receipt.parser_version,
                len(receipt.terms),
                Jsonb(receipt_record),
            ),
        )
        decision = routing.decision
        connection.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO research_financing_routing_receipts (
                accession_number, source_content_sha256, event_context, tier,
                outcome, reason, requires_model, routing_version, record
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (accession_number) DO NOTHING
            """,
            (
                routing.accession_number,
                routing.source_content_sha256,
                routing.event_context.value,
                int(decision.tier),
                decision.outcome.value,
                decision.reason.value,
                decision.requires_model,
                routing.routing_version,
                Jsonb(routing_record),
            ),
        )
        stored = connection.execute(  # type: ignore[attr-defined]
            """
            SELECT r.record AS receipt_record, t.record AS routing_record
            FROM research_financing_receipts r
            JOIN research_financing_routing_receipts t USING (accession_number)
            WHERE r.accession_number = %s
            """,
            (receipt.accession_number,),
        ).fetchone()
        if stored is None:
            raise RuntimeError("financing receipt pair was not persisted")
        _validate_replay(stored, receipt_record, routing_record)


def _candidate_from_row(row: dict[str, object]) -> FinancingDiscoveryCandidate:
    return FinancingDiscoveryCandidate.model_validate(
        {
            key: row[key]
            for key in (
                "accession_number",
                "index_ciks",
                "index_names",
                "form",
                "filed_on",
                "discovered_at",
                "source_index_url",
                "source_index_sha256",
            )
        }
    )


def _discovery_identity(candidate: FinancingDiscoveryCandidate) -> tuple[object, ...]:
    return (
        candidate.accession_number,
        candidate.index_ciks,
        candidate.index_names,
        candidate.form,
        candidate.filed_on,
        str(candidate.source_index_url),
    )


def _validate_replay(
    stored: dict[str, object],
    receipt_record: dict[str, object],
    routing_record: dict[str, object],
) -> None:
    if stored["receipt_record"] != receipt_record or stored["routing_record"] != routing_record:
        raise FinancingReplayConflict(
            "financing accession conflicts with immutable persisted history"
        )
