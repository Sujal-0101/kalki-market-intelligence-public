"""Append-only PostgreSQL persistence for SEC accounting intelligence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from psycopg.types.json import Jsonb

from kalki_market_intelligence.database import ConnectionFactory
from kalki_market_intelligence.forensics.accounting import (
    AccountingFilingReceipt,
    AccountingTier0Receipt,
)
from kalki_market_intelligence.providers.sec.accounting import AccountingDiscoveryCandidate

ACCOUNTING_FORM_PRIORITY = {
    "NT 10-K": 0,
    "NT 10-Q": 1,
    "10-K": 2,
    "10-K/A": 3,
    "10-Q": 4,
    "10-Q/A": 5,
    "8-K": 6,
    "8-K/A": 7,
}


class AccountingReplayConflict(RuntimeError):
    """An accession conflicts with immutable accounting history."""


@dataclass(frozen=True, slots=True)
class ClaimedAccountingJob:
    candidate: AccountingDiscoveryCandidate
    attempt: int


class PostgresAccountingStore:
    def __init__(self, connection: ConnectionFactory) -> None:
        self._connection = connection

    def append(
        self,
        receipt: AccountingFilingReceipt,
        routing: AccountingTier0Receipt,
    ) -> None:
        with self._connection() as connection:
            self._append_pair(connection, receipt, routing)

    def prior_receipts(
        self,
        *,
        issuer_cik: str,
        accepted_before: datetime,
        retrieved_by: datetime,
        limit: int = 32,
    ) -> tuple[AccountingFilingReceipt, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("accounting prior receipt limit must be between one and 100")
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT record FROM research_accounting_receipts
                WHERE issuer_cik = %s AND accepted_at < %s AND retrieved_at <= %s
                ORDER BY accepted_at DESC, accession_number DESC LIMIT %s
                """,
                (issuer_cik, accepted_before, retrieved_by, limit),
            ).fetchall()
        receipts = tuple(AccountingFilingReceipt.model_validate(row["record"]) for row in rows)
        return tuple(reversed(receipts))

    def discover(
        self,
        candidates: tuple[AccountingDiscoveryCandidate, ...],
        *,
        maximum_backlog: int,
    ) -> int:
        if not 1 <= maximum_backlog <= 1_000:
            raise ValueError("accounting backlog limit must be between one and 1000")
        inserted = 0
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT count(*) AS count FROM research_accounting_jobs
                WHERE status IN ('pending', 'processing', 'retry_wait')
                """
            ).fetchone()
            if row is None:
                raise RuntimeError("accounting backlog count is unavailable")
            capacity = maximum_backlog - int(row["count"])
            for candidate in sorted(
                candidates,
                key=lambda item: (
                    ACCOUNTING_FORM_PRIORITY[item.form.value],
                    item.filed_on,
                    item.accession_number,
                ),
            ):
                if capacity <= 0:
                    break
                result = connection.execute(
                    """
                    INSERT INTO research_accounting_jobs (
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
                    FROM research_accounting_jobs WHERE accession_number = %s
                    """,
                    (candidate.accession_number,),
                ).fetchone()
                if stored is None or _discovery_identity(_candidate_from_row(stored)) != (
                    _discovery_identity(candidate)
                ):
                    raise AccountingReplayConflict(
                        "accounting discovery conflicts with immutable accession identity"
                    )
        return inserted

    def claim(self, *, now: datetime) -> ClaimedAccountingJob | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT accession_number, index_ciks, index_names, form, filed_on,
                       discovered_at, source_index_url, source_index_sha256, attempts
                FROM research_accounting_jobs
                WHERE attempts < 3 AND (
                    status = 'pending' OR (status = 'retry_wait' AND next_attempt_at <= %s)
                )
                ORDER BY array_position(
                    ARRAY[
                        'NT 10-K', 'NT 10-Q', '10-K', '10-K/A',
                        '10-Q', '10-Q/A', '8-K', '8-K/A'
                    ]::text[], form
                ), filed_on, accession_number
                FOR UPDATE SKIP LOCKED LIMIT 1
                """,
                (now,),
            ).fetchone()
            if row is None:
                return None
            attempt = int(row["attempts"]) + 1
            connection.execute(
                """
                UPDATE research_accounting_jobs
                SET status = 'processing', claimed_at = %s, next_attempt_at = NULL,
                    completed_at = NULL, last_error_category = NULL,
                    terminal_reason = NULL, updated_at = %s
                WHERE accession_number = %s
                """,
                (now, now, row["accession_number"]),
            )
        return ClaimedAccountingJob(candidate=_candidate_from_row(row), attempt=attempt)

    def complete(
        self,
        claimed: ClaimedAccountingJob,
        receipt: AccountingFilingReceipt,
        routing: AccountingTier0Receipt,
        *,
        now: datetime,
    ) -> None:
        if claimed.candidate.accession_number != receipt.accession_number:
            raise ValueError("claimed accounting accession does not match receipt")
        with self._connection() as connection:
            self._append_pair(connection, receipt, routing)
            result = connection.execute(
                """
                UPDATE research_accounting_jobs
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
                raise RuntimeError("accounting job claim is absent or no longer current")

    def complete_no_events(self, claimed: ClaimedAccountingJob, *, now: datetime) -> None:
        with self._connection() as connection:
            result = connection.execute(
                """
                UPDATE research_accounting_jobs
                SET status = 'no_events', attempts = %s, claimed_at = NULL,
                    completed_at = %s, next_attempt_at = NULL,
                    last_error_category = NULL, terminal_reason = 'no_supported_events',
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
                raise RuntimeError("accounting job claim is absent or no longer current")

    def fail(
        self,
        claimed: ClaimedAccountingJob,
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
            raise ValueError("accounting failure category is not closed")
        terminal = claimed.attempt >= 3
        status = "failed" if terminal else "retry_wait"
        next_attempt_at = None if terminal else now + retry_delay
        completed_at = now if terminal else None
        with self._connection() as connection:
            result = connection.execute(
                """
                UPDATE research_accounting_jobs
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
                raise RuntimeError("accounting job claim is absent or no longer current")
        return status

    def recover_stale(self, *, now: datetime, lease: timedelta = timedelta(minutes=30)) -> int:
        if lease < timedelta(minutes=1):
            raise ValueError("accounting claim lease must be at least one minute")
        with self._connection() as connection:
            result = connection.execute(
                """
                UPDATE research_accounting_jobs
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
        receipt: AccountingFilingReceipt,
        routing: AccountingTier0Receipt,
    ) -> None:
        if receipt.accession_number != routing.accession_number:
            raise ValueError("accounting receipt and routing accession must match")
        if receipt.source_content_sha256 != routing.source_content_sha256:
            raise ValueError("accounting receipt and routing source hash must match")
        receipt_record = receipt.model_dump(mode="json")
        routing_record = routing.model_dump(mode="json")
        stored = connection.execute(  # type: ignore[attr-defined]
            """
            SELECT r.record AS receipt_record, t.record AS routing_record
            FROM research_accounting_receipts r
            JOIN research_accounting_routing_receipts t USING (accession_number)
            WHERE r.accession_number = %s
            """,
            (receipt.accession_number,),
        ).fetchone()
        if stored is not None:
            _validate_replay(stored, receipt_record, routing_record)
            return
        connection.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO research_accounting_receipts (
                receipt_id, accession_number, issuer_cik, issuer_name, form,
                accepted_at, retrieved_at, source_url, source_content_sha256,
                parser_version, prior_search_complete, event_count, record
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (accession_number) DO NOTHING
            """,
            (
                receipt.receipt_id,
                receipt.accession_number,
                receipt.issuer_cik,
                receipt.issuer_name,
                receipt.form.value,
                receipt.accepted_at,
                receipt.retrieved_at,
                str(receipt.source_url),
                receipt.source_content_sha256,
                receipt.parser_version,
                receipt.prior_search_complete,
                len(receipt.events),
                Jsonb(receipt_record),
            ),
        )
        decision = routing.decision
        connection.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO research_accounting_routing_receipts (
                accession_number, source_content_sha256, event_types, tier,
                outcome, reason, requires_model, routing_version, record
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (accession_number) DO NOTHING
            """,
            (
                routing.accession_number,
                routing.source_content_sha256,
                [item.value for item in routing.event_types],
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
            FROM research_accounting_receipts r
            JOIN research_accounting_routing_receipts t USING (accession_number)
            WHERE r.accession_number = %s
            """,
            (receipt.accession_number,),
        ).fetchone()
        if stored is None:
            raise RuntimeError("accounting receipt pair was not persisted")
        _validate_replay(stored, receipt_record, routing_record)


def _candidate_from_row(row: dict[str, object]) -> AccountingDiscoveryCandidate:
    return AccountingDiscoveryCandidate.model_validate(
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


def _discovery_identity(candidate: AccountingDiscoveryCandidate) -> tuple[object, ...]:
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
        raise AccountingReplayConflict(
            "accounting accession conflicts with immutable persisted history"
        )
