"""Append-only PostgreSQL persistence for SEC ownership intelligence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from psycopg.types.json import Jsonb

from kalki_market_intelligence.database import ConnectionFactory
from kalki_market_intelligence.forensics.ownership import OwnershipTier0Receipt
from kalki_market_intelligence.providers.sec.ownership import (
    OwnershipDiscoveryCandidate,
    OwnershipFilingReceipt,
    OwnershipForm,
)


class OwnershipReplayConflict(RuntimeError):
    """An accession was replayed with content that differs from immutable history."""


@dataclass(frozen=True, slots=True)
class ClaimedOwnershipJob:
    candidate: OwnershipDiscoveryCandidate
    attempt: int


class PostgresOwnershipStore:
    def __init__(self, connection: ConnectionFactory) -> None:
        self._connection = connection

    def append(
        self,
        receipt: OwnershipFilingReceipt,
        routing: OwnershipTier0Receipt,
    ) -> None:
        """Atomically append or verify one idempotent receipt/routing pair."""

        if receipt.accession_number != routing.accession_number:
            raise ValueError("ownership receipt and routing accession must match")
        if receipt.source_content_sha256 != routing.source_content_sha256:
            raise ValueError("ownership receipt and routing source hash must match")
        with self._connection() as connection:
            self._append_pair(connection, receipt, routing)

    def discover(
        self,
        candidates: tuple[OwnershipDiscoveryCandidate, ...],
        *,
        maximum_backlog: int,
    ) -> int:
        """Fill a separate bounded queue without touching deep-analysis candidates."""

        if not 1 <= maximum_backlog <= 1_000:
            raise ValueError("ownership backlog limit must be between one and 1000")
        inserted = 0
        with self._connection() as connection:
            active = connection.execute(
                """
                SELECT count(*) AS count FROM research_ownership_jobs
                WHERE status IN ('pending', 'processing', 'retry_wait')
                """
            ).fetchone()
            if active is None:
                raise RuntimeError("ownership backlog count is unavailable")
            capacity = maximum_backlog - int(active["count"])
            for candidate in sorted(
                candidates,
                key=lambda item: (item.filed_on, item.accession_number),
            ):
                if capacity <= 0:
                    break
                result = connection.execute(
                    """
                    INSERT INTO research_ownership_jobs (
                        accession_number, first_index_cik, first_index_name,
                        index_ciks, index_names, form, filed_on,
                        discovered_at, source_index_url, source_index_sha256, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (accession_number) DO NOTHING
                    """,
                    (
                        candidate.accession_number,
                        candidate.index_ciks[0],
                        candidate.index_names[0],
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
                    FROM research_ownership_jobs
                    WHERE accession_number = %s
                    """,
                    (candidate.accession_number,),
                ).fetchone()
                if stored is None or _discovery_identity(_candidate_from_row(stored)) != (
                    _discovery_identity(candidate)
                ):
                    raise OwnershipReplayConflict(
                        "ownership discovery conflicts with immutable accession identity"
                    )
        return inserted

    def claim(self, *, now: datetime) -> ClaimedOwnershipJob | None:
        """Claim one due job without consuming its attempt before work finishes."""

        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT accession_number, index_ciks, index_names, form, filed_on,
                       discovered_at, source_index_url, source_index_sha256, attempts
                FROM research_ownership_jobs
                WHERE attempts < 3 AND (
                    status = 'pending'
                    OR (status = 'retry_wait' AND next_attempt_at <= %s)
                )
                ORDER BY filed_on, accession_number
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """,
                (now,),
            ).fetchone()
            if row is None:
                return None
            attempt = int(row["attempts"]) + 1
            connection.execute(
                """
                UPDATE research_ownership_jobs
                SET status = 'processing', claimed_at = %s,
                    next_attempt_at = NULL, completed_at = NULL,
                    last_error_category = NULL, updated_at = %s
                WHERE accession_number = %s
                """,
                (now, now, row["accession_number"]),
            )
        return ClaimedOwnershipJob(candidate=_candidate_from_row(row), attempt=attempt)

    def previous_schedule_form(
        self,
        *,
        receipt: OwnershipFilingReceipt,
    ) -> OwnershipForm | None:
        """Find an earlier Schedule for the same issuer and reporting-owner set."""

        current_identity = _beneficial_owner_identity(receipt)
        if not current_identity:
            return None

        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT record FROM research_ownership_receipts
                WHERE issuer_cik = %s AND accepted_at < %s
                  AND form IN (
                    'SCHEDULE 13D', 'SCHEDULE 13D/A',
                    'SCHEDULE 13G', 'SCHEDULE 13G/A'
                  )
                ORDER BY accepted_at DESC, accession_number DESC
                LIMIT 100
                """,
                (receipt.issuer_cik, receipt.accepted_at),
            ).fetchall()
        for row in rows:
            previous = OwnershipFilingReceipt.model_validate(row["record"])
            if _beneficial_owner_identity(previous) == current_identity:
                return previous.form
        return None

    def complete(
        self,
        claimed: ClaimedOwnershipJob,
        receipt: OwnershipFilingReceipt,
        routing: OwnershipTier0Receipt,
        *,
        now: datetime,
    ) -> None:
        """Atomically retain immutable evidence/routing and close its queue head."""

        if claimed.candidate.accession_number != receipt.accession_number:
            raise ValueError("claimed ownership accession does not match receipt")
        with self._connection() as connection:
            self._append_pair(connection, receipt, routing)
            result = connection.execute(
                """
                UPDATE research_ownership_jobs
                SET status = 'completed', attempts = %s, claimed_at = NULL, completed_at = %s,
                    next_attempt_at = NULL, last_error_category = NULL,
                    resolved_issuer_cik = %s, resolved_issuer_name = %s, updated_at = %s
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
                raise RuntimeError("ownership job claim is absent or no longer current")

    def fail(
        self,
        claimed: ClaimedOwnershipJob,
        *,
        category: str,
        now: datetime,
        retry_delay: timedelta = timedelta(hours=1),
    ) -> str:
        """Record only a closed failure category; never persist exception text."""

        if category not in {
            "metadata_unavailable",
            "primary_document_error",
            "parse_error",
            "persistence_error",
            "other",
        }:
            raise ValueError("ownership failure category is not closed")
        terminal = claimed.attempt >= 3
        status = "failed" if terminal else "retry_wait"
        next_attempt_at = None if terminal else now + retry_delay
        with self._connection() as connection:
            result = connection.execute(
                """
                UPDATE research_ownership_jobs
                SET status = %s, attempts = %s, claimed_at = NULL, next_attempt_at = %s,
                    completed_at = NULL, last_error_category = %s, updated_at = %s
                WHERE accession_number = %s AND status = 'processing' AND attempts = %s
                """,
                (
                    status,
                    claimed.attempt,
                    next_attempt_at,
                    category,
                    now,
                    claimed.candidate.accession_number,
                    claimed.attempt - 1,
                ),
            )
            if result.rowcount != 1:
                raise RuntimeError("ownership job claim is absent or no longer current")
        return status

    def recover_stale(self, *, now: datetime, lease: timedelta = timedelta(minutes=30)) -> int:
        """Recover abandoned claims without mutating terminal ownership history."""

        if lease < timedelta(minutes=1):
            raise ValueError("ownership claim lease must be at least one minute")
        with self._connection() as connection:
            result = connection.execute(
                """
                UPDATE research_ownership_jobs
                SET status = 'retry_wait', claimed_at = NULL,
                    next_attempt_at = %s,
                    completed_at = NULL, last_error_category = 'other', updated_at = %s
                WHERE status = 'processing' AND claimed_at < %s AND attempts < 3
                """,
                (now, now, now - lease),
            )
        return result.rowcount

    @staticmethod
    def _append_pair(
        connection: object,
        receipt: OwnershipFilingReceipt,
        routing: OwnershipTier0Receipt,
    ) -> None:
        if receipt.accession_number != routing.accession_number:
            raise ValueError("ownership receipt and routing accession must match")
        if receipt.source_content_sha256 != routing.source_content_sha256:
            raise ValueError("ownership receipt and routing source hash must match")
        receipt_record = receipt.model_dump(mode="json")
        routing_record = routing.model_dump(mode="json")
        decision = routing.decision
        stored = connection.execute(  # type: ignore[attr-defined]
            """
            SELECT r.record AS receipt_record, t.record AS routing_record
            FROM research_ownership_receipts r
            JOIN research_ownership_routing_receipts t USING (accession_number)
            WHERE r.accession_number = %s
            """,
            (receipt.accession_number,),
        ).fetchone()
        if stored is not None:
            _validate_replay(stored, receipt_record, routing_record)
            return
        connection.execute(  # type: ignore[attr-defined]
            """
                INSERT INTO research_ownership_receipts (
                    accession_number, issuer_cik, form, period_or_event_date,
                    accepted_at, retrieved_at, source_url, source_content_sha256,
                    parser_version, record
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (accession_number) DO NOTHING
                """,
            (
                receipt.accession_number,
                receipt.issuer_cik,
                receipt.form.value,
                receipt.period_or_event_date,
                receipt.accepted_at,
                receipt.retrieved_at,
                str(receipt.source_url),
                receipt.source_content_sha256,
                receipt.parser_version,
                Jsonb(receipt_record),
            ),
        )
        connection.execute(  # type: ignore[attr-defined]
            """
                INSERT INTO research_ownership_routing_receipts (
                    accession_number, source_content_sha256, event_context,
                    schedule_transition, tier, outcome, reason, requires_model,
                    routing_version, record
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (accession_number) DO NOTHING
                """,
            (
                routing.accession_number,
                routing.source_content_sha256,
                routing.event_context.value,
                routing.schedule_transition.value,
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
                FROM research_ownership_receipts r
                JOIN research_ownership_routing_receipts t USING (accession_number)
                WHERE r.accession_number = %s
                """,
            (receipt.accession_number,),
        ).fetchone()
        if stored is None:
            raise RuntimeError("ownership receipt pair was not persisted")
        _validate_replay(stored, receipt_record, routing_record)


def _candidate_from_row(row: dict[str, object]) -> OwnershipDiscoveryCandidate:
    return OwnershipDiscoveryCandidate.model_validate(
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


def _discovery_identity(candidate: OwnershipDiscoveryCandidate) -> tuple[object, ...]:
    """Compare stable row identity while retaining the first observed index receipt.

    A daily index can grow under the same URL during the filing day, so its complete
    document hash and retrieval time may legitimately differ on a later poll.
    """

    return (
        candidate.accession_number,
        candidate.index_ciks,
        candidate.index_names,
        candidate.form,
        candidate.filed_on,
        str(candidate.source_index_url),
    )


def _beneficial_owner_identity(receipt: OwnershipFilingReceipt) -> tuple[str, ...]:
    """Return an exact closed identity set for conservative Schedule transitions."""

    return tuple(
        sorted(
            {
                f"cik:{owner.cik}"
                if owner.cik is not None
                else f"name:{' '.join(owner.name.casefold().split())}"
                for owner in receipt.beneficial_owners
            }
        )
    )


def _validate_replay(
    stored: dict[str, object],
    receipt_record: dict[str, object],
    routing_record: dict[str, object],
) -> None:
    if stored["receipt_record"] != receipt_record or stored["routing_record"] != routing_record:
        raise OwnershipReplayConflict(
            "ownership accession conflicts with immutable persisted history"
        )
