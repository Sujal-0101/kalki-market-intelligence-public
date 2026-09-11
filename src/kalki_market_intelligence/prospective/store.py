"""Restart-safe PostgreSQL persistence for prospective outcome jobs."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from psycopg.types.json import Jsonb

from kalki_market_intelligence.database import ConnectionFactory
from kalki_market_intelligence.prospective.contracts import (
    ClaimedProspectiveOutcome,
    OutcomeJobStatus,
    OutcomeStatus,
    ProspectiveOutcome,
    ProspectiveOutcomeAttempt,
    ProspectiveOutcomePlan,
    ProspectivePublication,
)


def outcome_plan_id(plan: ProspectiveOutcomePlan) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"prospective-plan:{plan.publication_id}:{int(plan.horizon)}:{plan.provider_name}",
    )


class PostgresProspectiveOutcomeStore:
    def __init__(self, connection: ConnectionFactory) -> None:
        self._connection = connection

    def enroll(self, plan: ProspectiveOutcomePlan, *, now: datetime) -> bool:
        """Insert one immutable plan plus its job, or leave the existing key unchanged."""

        plan_id = outcome_plan_id(plan)
        with self._connection() as connection, connection.transaction():
            inserted = connection.execute(
                """
                INSERT INTO research_prospective_outcome_plans (
                    plan_id, publication_id, horizon, provider_name, published_at,
                    asset_symbol, asset_mic, benchmark_symbol, benchmark_mic,
                    calendar_name, currency,
                    publication_session_date, reference_session_date,
                    reference_session_close_at, target_session_date,
                    target_session_close_at, origin, enrolled_at, methodology_version,
                    provider_terms_version, provider_use_mode, record
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (publication_id, horizon, provider_name) DO NOTHING
                RETURNING plan_id
                """,
                (
                    plan_id,
                    plan.publication_id,
                    int(plan.horizon),
                    plan.provider_name,
                    plan.published_at,
                    plan.asset_symbol,
                    plan.asset_mic,
                    plan.benchmark_symbol,
                    plan.benchmark_mic,
                    plan.calendar_name,
                    plan.currency.value,
                    plan.publication_session_date,
                    plan.reference_session_date,
                    plan.reference_session_close_at,
                    plan.target_session_date,
                    plan.target_session_close_at,
                    plan.origin.value,
                    plan.enrolled_at,
                    plan.methodology_version,
                    plan.provider_terms_version,
                    plan.provider_use_mode,
                    Jsonb(plan.model_dump(mode="json")),
                ),
            ).fetchone()
            if inserted is None:
                return False
            connection.execute(
                """
                INSERT INTO research_prospective_outcome_jobs (
                    plan_id, status, attempts, next_attempt_at, updated_at
                ) VALUES (%s, 'pending', 0, %s, %s)
                """,
                (
                    plan_id,
                    max(now, plan.target_session_close_at + timedelta(hours=12)),
                    now,
                ),
            )
        return True

    def publications_for_enrollment(
        self, *, limit: int = 100
    ) -> tuple[ProspectivePublication, ...]:
        if not 1 <= limit <= 500:
            raise ValueError("prospective enrollment limit must be 1-500")
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT b.brief_id, b.published_at, b.ticker, b.record->>'exchange' AS exchange
                FROM research_briefs b
                LEFT JOIN research_prospective_outcome_plans p
                  ON p.publication_id = b.brief_id AND p.provider_name = 'twelve_data'
                GROUP BY b.brief_id, b.published_at, b.ticker, b.record
                HAVING count(p.plan_id) < 3
                ORDER BY b.published_at, b.brief_id
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
        return tuple(
            ProspectivePublication(
                publication_id=row["brief_id"],
                published_at=row["published_at"],
                ticker=row["ticker"],
                exchange=row["exchange"],
            )
            for row in rows
        )

    def claim_due(self, *, now: datetime) -> ClaimedProspectiveOutcome | None:
        with self._connection() as connection, connection.transaction():
            row = connection.execute(
                """
                SELECT j.plan_id, j.attempts, p.record
                FROM research_prospective_outcome_jobs j
                JOIN research_prospective_outcome_plans p USING (plan_id)
                WHERE j.status IN ('pending', 'retry_wait')
                  AND j.attempts < 6
                  AND j.next_attempt_at <= %s
                  AND p.target_session_close_at <= %s
                ORDER BY p.target_session_close_at, p.publication_id, p.horizon
                FOR UPDATE OF j SKIP LOCKED
                LIMIT 1
                """,
                (now, now),
            ).fetchone()
            if row is None:
                return None
            attempt_number = int(row["attempts"]) + 1
            connection.execute(
                """
                UPDATE research_prospective_outcome_jobs
                SET status = 'processing', claimed_at = %s,
                    next_attempt_at = NULL, last_error_code = NULL, updated_at = %s
                WHERE plan_id = %s
                """,
                (now, now, row["plan_id"]),
            )
        return ClaimedProspectiveOutcome(
            plan_id=row["plan_id"],
            plan=ProspectiveOutcomePlan.model_validate(row["record"]),
            attempt_number=attempt_number,
            claimed_at=now,
        )

    def retry_with_attempt(
        self,
        plan_id: UUID,
        attempt: ProspectiveOutcomeAttempt,
        *,
        now: datetime,
        next_attempt_at: datetime,
    ) -> None:
        if attempt.error_code is None or attempt.attempt_number >= 6:
            raise ValueError("retry receipt must be failed and below the attempt ceiling")
        with self._connection() as connection, connection.transaction():
            connection.execute(
                """
                INSERT INTO research_prospective_outcome_attempts (
                    attempt_id, plan_id, attempt_number, started_at, completed_at,
                    status, error_code, record
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    attempt.attempt_id,
                    plan_id,
                    attempt.attempt_number,
                    attempt.started_at,
                    attempt.completed_at,
                    attempt.status.value,
                    attempt.error_code,
                    Jsonb(attempt.model_dump(mode="json")),
                ),
            )
            result = connection.execute(
                """
                UPDATE research_prospective_outcome_jobs
                SET status = 'retry_wait', attempts = %s, claimed_at = NULL,
                    next_attempt_at = %s, last_error_code = %s, updated_at = %s
                WHERE plan_id = %s AND status = 'processing' AND attempts = %s
                """,
                (
                    attempt.attempt_number,
                    next_attempt_at,
                    attempt.error_code,
                    now,
                    plan_id,
                    attempt.attempt_number - 1,
                ),
            )
            if result.rowcount != 1:
                raise ValueError("prospective outcome job is not retryable")

    def attempts_for_plan(self, plan_id: UUID) -> tuple[ProspectiveOutcomeAttempt, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT record FROM research_prospective_outcome_attempts
                WHERE plan_id = %s ORDER BY attempt_number
                """,
                (plan_id,),
            ).fetchall()
        return tuple(ProspectiveOutcomeAttempt.model_validate(row["record"]) for row in rows)

    def complete_with_attempt(
        self,
        outcome: ProspectiveOutcome,
        attempt: ProspectiveOutcomeAttempt,
    ) -> None:
        plan_id = outcome_plan_id(outcome.plan)
        if outcome.attempts[-1] != attempt:
            raise ValueError("terminal receipt must be the final outcome attempt")
        terminal = (
            OutcomeJobStatus.COMPLETED
            if outcome.status is OutcomeStatus.COMPLETED
            else OutcomeJobStatus.DATA_UNAVAILABLE
        )
        with self._connection() as connection, connection.transaction():
            connection.execute(
                """
                INSERT INTO research_prospective_outcome_attempts (
                    attempt_id, plan_id, attempt_number, started_at, completed_at,
                    status, error_code, record
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    attempt.attempt_id,
                    plan_id,
                    attempt.attempt_number,
                    attempt.started_at,
                    attempt.completed_at,
                    attempt.status.value,
                    attempt.error_code,
                    Jsonb(attempt.model_dump(mode="json")),
                ),
            )
            observations = outcome.observations
            connection.execute(
                """
                INSERT INTO research_prospective_outcomes (
                    outcome_id, plan_id, publication_id, horizon, provider_name,
                    status, origin, authority, asset_reference_close,
                    asset_target_close, benchmark_reference_close,
                    benchmark_target_close, asset_return, benchmark_return,
                    benchmark_relative_return, calculation_version, evaluated_at,
                    appended_at, record
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, 'SUPPORTING', %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    outcome.outcome_id,
                    plan_id,
                    outcome.plan.publication_id,
                    int(outcome.plan.horizon),
                    outcome.plan.provider_name,
                    outcome.status.value,
                    outcome.plan.origin.value,
                    observations.asset_reference.close
                    if observations.asset_reference is not None
                    else None,
                    observations.asset_target.close
                    if observations.asset_target is not None
                    else None,
                    observations.benchmark_reference.close
                    if observations.benchmark_reference is not None
                    else None,
                    observations.benchmark_target.close
                    if observations.benchmark_target is not None
                    else None,
                    outcome.asset_return,
                    outcome.benchmark_return,
                    outcome.benchmark_relative_return,
                    outcome.calculation_version,
                    outcome.evaluated_at,
                    outcome.appended_at,
                    Jsonb(outcome.model_dump(mode="json")),
                ),
            )
            result = connection.execute(
                """
                UPDATE research_prospective_outcome_jobs
                SET status = %s, attempts = %s, claimed_at = NULL, next_attempt_at = NULL,
                    last_error_code = NULL, updated_at = %s
                WHERE plan_id = %s AND status = 'processing' AND attempts = %s
                """,
                (
                    terminal.value,
                    attempt.attempt_number,
                    outcome.appended_at,
                    plan_id,
                    attempt.attempt_number - 1,
                ),
            )
            if result.rowcount != 1:
                raise ValueError("prospective outcome job was not processing")

    def requeue_stale(self, *, now: datetime, lease_seconds: int = 900) -> int:
        if not 60 <= lease_seconds <= 7_200:
            raise ValueError("prospective outcome lease must be 60-7200 seconds")
        threshold = now - timedelta(seconds=lease_seconds)
        with self._connection() as connection:
            result = connection.execute(
                """
                UPDATE research_prospective_outcome_jobs
                SET status = 'retry_wait', claimed_at = NULL, next_attempt_at = %s,
                    last_error_code = 'processing_lease_expired', updated_at = %s
                WHERE status = 'processing' AND claimed_at <= %s AND attempts < 6
                """,
                (now, now, threshold),
            )
        return result.rowcount
