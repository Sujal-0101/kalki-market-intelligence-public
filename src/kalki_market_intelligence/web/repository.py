"""Read-only publication repository used by API and HTML views."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from kalki_market_intelligence.database import ConnectionFactory
from kalki_market_intelligence.predictions.contracts import PredictionRecord
from kalki_market_intelligence.prospective.science_store import PostgresOutcomeScienceRepository
from kalki_market_intelligence.radar.contracts import (
    RadarClassification,
    ResearchBrief,
    WorkerSnapshot,
)
from kalki_market_intelligence.radar.measurements import EngineeringMeasurementReceipt
from kalki_market_intelligence.radar.sec_links import (
    PublicSecFilingLinks,
    ValidatedSecFilingLinks,
    public_sec_filing_links,
)
from kalki_market_intelligence.web.contracts import (
    PublicScreenedFiling,
    PublicScreeningActivity,
    PublicScreeningReason,
    PublicScreeningWindow,
)
from kalki_market_intelligence.web.operations import (
    AccountingOperations,
    ConvergenceOperations,
    DetectorCount,
    EngineeringMeasurementsSnapshot,
    EngineeringMeasurementWindow,
    FinancingOperations,
    FunnelCurrent,
    FunnelSnapshot,
    FunnelWindow,
    NamedCount,
    OutcomeScienceOperations,
    OwnershipOperations,
    ScreeningReconciliation,
    ScreeningReconciliationWindow,
    outcome_science_operations,
)

DETECTOR_NAMES = (
    "share_growth",
    "liquidity",
    "going_concern",
    "reverse_split",
    "filing_diff",
    "xbrl_numeric",
    "source_authority",
    "convergence",
)

PUBLIC_SCREENING_REASONS = {
    "DETERMINISTIC_QUALIFICATION_NOT_MET": PublicScreeningReason.DETERMINISTIC_CRITERIA_NOT_MET,
    "NO_VALIDATED_FINDINGS": PublicScreeningReason.NO_VALIDATED_FINDINGS,
    "INSUFFICIENT_EVIDENCE": PublicScreeningReason.INSUFFICIENT_EVIDENCE,
    "VERIFICATION_DISAGREEMENT": PublicScreeningReason.VERIFICATION_DISAGREEMENT,
}


class ResearchRepository(Protocol):
    """Narrow query boundary that exposes no publication mutation method."""

    def list_predictions(
        self, *, limit: int | None = None, offset: int = 0
    ) -> tuple[PredictionRecord, ...]: ...

    def get_prediction(self, prediction_id: UUID) -> PredictionRecord | None: ...

    def list_publications(
        self, *, limit: int = 50, offset: int = 0
    ) -> tuple[ResearchBrief | PredictionRecord, ...]: ...

    def list_briefs(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        classification: RadarClassification | None = None,
        query: str | None = None,
    ) -> tuple[ResearchBrief, ...]: ...

    def get_brief(self, brief_id: UUID) -> ResearchBrief | None: ...

    def get_brief_sec_links(self, brief_id: UUID) -> PublicSecFilingLinks | None: ...

    def get_worker_snapshot(self) -> WorkerSnapshot | None: ...

    def get_funnel_snapshot(self) -> FunnelSnapshot | None: ...

    def list_screened_filings(
        self, *, limit: int = 50, offset: int = 0
    ) -> tuple[PublicScreenedFiling, ...]: ...

    def get_screening_activity(self) -> PublicScreeningActivity | None: ...

    def get_screening_reconciliation(self) -> ScreeningReconciliation | None: ...

    def get_ownership_operations(self) -> OwnershipOperations | None: ...

    def get_financing_operations(self) -> FinancingOperations | None: ...

    def get_accounting_operations(self) -> AccountingOperations | None: ...

    def get_convergence_operations(self) -> ConvergenceOperations | None: ...

    def get_outcome_science_operations(self) -> OutcomeScienceOperations | None: ...

    def get_engineering_measurements(self) -> EngineeringMeasurementsSnapshot | None: ...


class MemoryResearchRepository:
    """Immutable local/test repository with deterministic publication ordering."""

    def __init__(
        self,
        predictions: tuple[PredictionRecord, ...] = (),
        *,
        briefs: tuple[ResearchBrief, ...] = (),
        worker_snapshot: WorkerSnapshot | None = None,
        funnel_snapshot: FunnelSnapshot | None = None,
        screened_filings: tuple[PublicScreenedFiling, ...] = (),
        screening_activity: PublicScreeningActivity | None = None,
        screening_reconciliation: ScreeningReconciliation | None = None,
        ownership_operations: OwnershipOperations | None = None,
        financing_operations: FinancingOperations | None = None,
        accounting_operations: AccountingOperations | None = None,
        convergence_operations: ConvergenceOperations | None = None,
        outcome_science_operations: OutcomeScienceOperations | None = None,
        engineering_measurements: EngineeringMeasurementsSnapshot | None = None,
        sec_link_receipts: tuple[ValidatedSecFilingLinks, ...] = (),
    ) -> None:
        identifiers = tuple(item.prediction_id for item in predictions)
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("research repository prediction IDs must be unique")
        self._predictions = tuple(
            sorted(
                predictions,
                key=lambda item: (item.published_at, str(item.prediction_id)),
                reverse=True,
            )
        )
        self._by_id = {item.prediction_id: item for item in self._predictions}
        brief_ids = tuple(item.brief_id for item in briefs)
        if len(set(brief_ids)) != len(brief_ids):
            raise ValueError("research repository brief IDs must be unique")
        self._briefs = tuple(
            sorted(briefs, key=lambda item: (item.published_at, str(item.brief_id)), reverse=True)
        )
        self._brief_by_id = {item.brief_id: item for item in self._briefs}
        receipts_by_identity = {
            (item.accession_number, item.complete_submission_sha256): item
            for item in sec_link_receipts
        }
        if len(receipts_by_identity) != len(sec_link_receipts):
            raise ValueError("research repository SEC-link receipts must be unique")
        self._brief_sec_links = {
            item.brief_id: public_sec_filing_links(receipt)
            for item in self._briefs
            if (
                receipt := receipts_by_identity.get(
                    (item.accession_number, item.source_document_sha256)
                )
            )
            is not None
        }
        self._publications: tuple[ResearchBrief | PredictionRecord, ...] = tuple(
            sorted(
                (*self._briefs, *self._predictions),
                key=lambda item: (
                    item.published_at,
                    str(item.brief_id if isinstance(item, ResearchBrief) else item.prediction_id),
                    1 if isinstance(item, ResearchBrief) else 0,
                ),
                reverse=True,
            )
        )
        self._worker_snapshot = worker_snapshot
        self._funnel_snapshot = funnel_snapshot
        self._screened_filings = tuple(
            sorted(screened_filings, key=lambda item: item.screened_at, reverse=True)
        )
        self._screening_activity = screening_activity
        self._screening_reconciliation = screening_reconciliation
        self._ownership_operations = ownership_operations
        self._financing_operations = financing_operations
        self._accounting_operations = accounting_operations
        self._convergence_operations = convergence_operations
        self._outcome_science_operations = outcome_science_operations
        self._engineering_measurements = engineering_measurements

    def list_predictions(
        self, *, limit: int | None = None, offset: int = 0
    ) -> tuple[PredictionRecord, ...]:
        _validate_page(limit, offset)
        if limit is None:
            return self._predictions[offset:]
        return self._predictions[offset : offset + limit]

    def get_prediction(self, prediction_id: UUID) -> PredictionRecord | None:
        return self._by_id.get(prediction_id)

    def list_publications(
        self, *, limit: int = 50, offset: int = 0
    ) -> tuple[ResearchBrief | PredictionRecord, ...]:
        """Return every public dossier and forecast once in one UTC ordering."""

        _validate_page(limit, offset)
        return self._publications[offset : offset + limit]

    def list_briefs(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        classification: RadarClassification | None = None,
        query: str | None = None,
    ) -> tuple[ResearchBrief, ...]:
        _validate_page(limit, offset)
        normalized_query = _validate_query(query)
        selected = tuple(
            item
            for item in self._briefs
            if (classification is None or item.classification is classification)
            and (
                normalized_query is None
                or normalized_query in item.company_name.casefold()
                or (item.ticker is not None and normalized_query in item.ticker.casefold())
            )
        )
        return selected[offset : offset + limit]

    def get_brief(self, brief_id: UUID) -> ResearchBrief | None:
        return self._brief_by_id.get(brief_id)

    def get_brief_sec_links(self, brief_id: UUID) -> PublicSecFilingLinks | None:
        return self._brief_sec_links.get(brief_id)

    def get_worker_snapshot(self) -> WorkerSnapshot | None:
        return self._worker_snapshot

    def get_funnel_snapshot(self) -> FunnelSnapshot | None:
        return self._funnel_snapshot

    def list_screened_filings(
        self, *, limit: int = 50, offset: int = 0
    ) -> tuple[PublicScreenedFiling, ...]:
        _validate_page(limit, offset)
        return self._screened_filings[offset : offset + limit]

    def get_screening_activity(self) -> PublicScreeningActivity | None:
        return self._screening_activity

    def get_screening_reconciliation(self) -> ScreeningReconciliation | None:
        return self._screening_reconciliation

    def get_ownership_operations(self) -> OwnershipOperations | None:
        return self._ownership_operations

    def get_financing_operations(self) -> FinancingOperations | None:
        return self._financing_operations

    def get_accounting_operations(self) -> AccountingOperations | None:
        return self._accounting_operations

    def get_convergence_operations(self) -> ConvergenceOperations | None:
        return self._convergence_operations

    def get_outcome_science_operations(self) -> OutcomeScienceOperations | None:
        return self._outcome_science_operations

    def get_engineering_measurements(self) -> EngineeringMeasurementsSnapshot | None:
        return self._engineering_measurements


class PostgresResearchRepository:
    """Read and revalidate immutable prediction JSON from PostgreSQL."""

    def __init__(self, connection: ConnectionFactory) -> None:
        self._connection = connection

    def list_predictions(
        self, *, limit: int | None = None, offset: int = 0
    ) -> tuple[PredictionRecord, ...]:
        _validate_page(limit, offset)
        suffix = "" if limit is None else " LIMIT %s"
        parameters: tuple[object, ...] = () if limit is None else (limit,)
        if offset:
            suffix += " OFFSET %s"
            parameters += (offset,)
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT record
                FROM predictions
                ORDER BY published_at DESC, prediction_id DESC
                {suffix}
                """,
                parameters,
            ).fetchall()
        return tuple(PredictionRecord.model_validate(row["record"]) for row in rows)

    def get_prediction(self, prediction_id: UUID) -> PredictionRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT record FROM predictions WHERE prediction_id = %s",
                (prediction_id,),
            ).fetchone()
        return None if row is None else PredictionRecord.model_validate(row["record"])

    def list_publications(
        self, *, limit: int = 50, offset: int = 0
    ) -> tuple[ResearchBrief | PredictionRecord, ...]:
        """List only immutable public tables, excluding all private human results."""

        _validate_page(limit, offset)
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT publication_type, record
                FROM (
                    SELECT 'dossier' AS publication_type, brief_id AS publication_id,
                           published_at, record
                    FROM research_briefs
                    UNION ALL
                    SELECT 'forecast' AS publication_type, prediction_id AS publication_id,
                           published_at, record
                    FROM predictions
                ) AS public_library
                ORDER BY published_at DESC, publication_id DESC,
                         CASE publication_type WHEN 'dossier' THEN 0 ELSE 1 END
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            ).fetchall()
        return tuple(
            ResearchBrief.model_validate(row["record"])
            if row["publication_type"] == "dossier"
            else PredictionRecord.model_validate(row["record"])
            for row in rows
        )

    def list_briefs(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        classification: RadarClassification | None = None,
        query: str | None = None,
    ) -> tuple[ResearchBrief, ...]:
        _validate_page(limit, offset)
        normalized_query = _validate_query(query)
        clauses: list[str] = []
        parameters: list[object] = []
        if classification is not None:
            clauses.append("classification = %s")
            parameters.append(classification.value)
        if normalized_query is not None:
            clauses.append("(lower(company_name) LIKE %s OR lower(coalesce(ticker, '')) LIKE %s)")
            pattern = f"%{normalized_query}%"
            parameters.extend((pattern, pattern))
        where = "" if not clauses else " WHERE " + " AND ".join(clauses)
        parameters.extend((limit, offset))
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT record
                FROM research_briefs
                {where}
                ORDER BY published_at DESC, brief_id DESC
                LIMIT %s OFFSET %s
                """,
                tuple(parameters),
            ).fetchall()
        return tuple(ResearchBrief.model_validate(row["record"]) for row in rows)

    def get_brief(self, brief_id: UUID) -> ResearchBrief | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT record FROM research_briefs WHERE brief_id = %s", (brief_id,)
            ).fetchone()
        return None if row is None else ResearchBrief.model_validate(row["record"])

    def get_brief_sec_links(self, brief_id: UUID) -> PublicSecFilingLinks | None:
        """Return only URLs from the stored receipt linked to this immutable brief."""

        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT l.record
                FROM research_briefs b
                JOIN research_sec_link_receipts l ON l.receipt_id = b.sec_link_receipt_id
                WHERE b.brief_id = %s
                """,
                (brief_id,),
            ).fetchone()
        if row is None:
            return None
        return public_sec_filing_links(ValidatedSecFilingLinks.model_validate(row["record"]))

    def get_worker_snapshot(self) -> WorkerSnapshot | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT worker_name, state, heartbeat_at, last_success_at, next_run_at,
                       last_error_code, discovered_count, pending_count, published_count,
                       discord_enabled, model_name, source_name,
                       verifier_enabled, verifier_model_name,
                       coalesce(c.verifier_reviews, 0) AS verifier_reviews,
                       coalesce(c.verifier_approvals, 0) AS verifier_approvals,
                       coalesce(c.verifier_challenges, 0) AS verifier_challenges
                FROM research_worker_status s
                LEFT JOIN research_operation_counters c USING (worker_name)
                WHERE s.worker_name = 'filing-radar'
                """
            ).fetchone()
        return None if row is None else WorkerSnapshot.model_validate(row)

    def list_screened_filings(
        self, *, limit: int = 50, offset: int = 0
    ) -> tuple[PublicScreenedFiling, ...]:
        """Select only safe autonomous identity and closed screened-out reasons."""

        _validate_page(limit, offset)
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT c.ticker, c.company_name, c.filing_form, c.filed_at,
                       d.decided_at AS screened_at, d.reason, c.source_url
                FROM research_autonomous_screening_decisions d
                JOIN research_candidates c USING (accession_number)
                WHERE d.disposition = 'SCREENED_OUT'
                ORDER BY d.decided_at DESC, d.decision_id DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            ).fetchall()
        return tuple(
            PublicScreenedFiling(
                ticker=row["ticker"],
                company_name=row["company_name"],
                filing_form=row["filing_form"],
                filed_at=row["filed_at"],
                screened_at=row["screened_at"],
                reason=PUBLIC_SCREENING_REASONS[row["reason"]],
                source_url=row["source_url"],
            )
            for row in rows
        )

    def get_screening_activity(self) -> PublicScreeningActivity | None:
        """Return prospective 24-hour and 7-day terminal decision counts."""

        with self._connection() as connection:
            rows = connection.execute(
                """
                WITH bounds AS (SELECT clock_timestamp() AS observed_at),
                     windows(hours) AS (VALUES (24), (168))
                SELECT w.hours, b.observed_at, s.started_at AS telemetry_started_at,
                       s.started_at <= b.observed_at - w.hours * interval '1 hour'
                           AS telemetry_complete,
                       count(d.decision_id) AS processed,
                       count(d.decision_id) FILTER (
                           WHERE cardinality(d.analyst_attempt_ids) > 0
                       ) AS completed_deep_analysis,
                       count(d.decision_id) FILTER (
                           WHERE d.disposition = 'SCREENED_OUT'
                       ) AS screened_out,
                       count(d.decision_id) FILTER (
                           WHERE d.disposition = 'QUALIFIED'
                       ) AS qualified,
                       count(d.decision_id) FILTER (
                           WHERE d.disposition = 'ANALYSIS_INCOMPLETE'
                       ) AS analysis_incomplete
                FROM windows w CROSS JOIN bounds b
                CROSS JOIN research_autonomous_screening_state s
                LEFT JOIN research_autonomous_screening_decisions d
                  ON d.decided_at >= b.observed_at - w.hours * interval '1 hour'
                GROUP BY w.hours, b.observed_at, s.started_at
                ORDER BY w.hours
                """
            ).fetchall()
        if len(rows) != 2:
            return None
        return PublicScreeningActivity(
            observed_at=rows[0]["observed_at"],
            telemetry_started_at=rows[0]["telemetry_started_at"],
            windows=tuple(
                PublicScreeningWindow(
                    hours=row["hours"],
                    telemetry_complete=row["telemetry_complete"],
                    processed=row["processed"],
                    completed_deep_analysis=row["completed_deep_analysis"],
                    screened_out=row["screened_out"],
                    qualified=row["qualified"],
                    analysis_incomplete=row["analysis_incomplete"],
                )
                for row in rows
            ),  # type: ignore[arg-type]
        )

    def get_screening_reconciliation(self) -> ScreeningReconciliation | None:
        """Return private terminal reasons and queue/publication reconciliation."""

        with self._connection() as connection:
            rows = connection.execute(
                """
                WITH bounds AS (SELECT clock_timestamp() AS observed_at),
                     windows(hours) AS (VALUES (24), (48), (168))
                SELECT w.hours, b.observed_at, s.started_at AS telemetry_started_at,
                       s.started_at <= b.observed_at - w.hours * interval '1 hour'
                           AS telemetry_complete,
                       count(d.decision_id) FILTER (
                           WHERE d.disposition = 'QUALIFIED'
                       ) AS qualified,
                       count(d.decision_id) FILTER (
                           WHERE d.disposition = 'SCREENED_OUT'
                       ) AS screened_out,
                       count(d.decision_id) FILTER (
                           WHERE d.disposition = 'ANALYSIS_INCOMPLETE'
                       ) AS analysis_incomplete
                FROM windows w CROSS JOIN bounds b
                CROSS JOIN research_autonomous_screening_state s
                LEFT JOIN research_autonomous_screening_decisions d
                  ON d.decided_at >= b.observed_at - w.hours * interval '1 hour'
                GROUP BY w.hours, b.observed_at, s.started_at
                ORDER BY w.hours
                """
            ).fetchall()
            reason_rows = connection.execute(
                """
                WITH bounds AS (SELECT clock_timestamp() AS observed_at),
                     windows(hours) AS (VALUES (24), (48), (168))
                SELECT w.hours, d.reason AS name, count(*) AS count
                FROM windows w CROSS JOIN bounds b
                JOIN research_autonomous_screening_decisions d
                  ON d.decided_at >= b.observed_at - w.hours * interval '1 hour'
                GROUP BY w.hours, d.reason
                ORDER BY w.hours, d.reason
                """
            ).fetchall()
            current = connection.execute(
                """
                SELECT
                    count(*) FILTER (WHERE status = 'retry_wait') AS retry_wait,
                    count(*) FILTER (WHERE status = 'published') AS published,
                    count(*) FILTER (WHERE status = 'quarantined') AS quarantined,
                    count(*) FILTER (WHERE status = 'failed') AS failed,
                    (SELECT count(*) FROM research_notification_deliveries
                     WHERE status = 'sent') AS discord_sent,
                    (SELECT count(*) FROM research_notification_deliveries
                     WHERE status = 'duplicate') AS discord_duplicates,
                    count(*) FILTER (
                        WHERE status IN ('skipped', 'published', 'quarantined', 'failed')
                          AND NOT EXISTS (
                              SELECT 1 FROM research_autonomous_screening_decisions d
                              WHERE d.accession_number = research_candidates.accession_number
                          )
                    ) AS legacy_terminal_without_decision
                FROM research_candidates
                """
            ).fetchone()
        if current is None or len(rows) != 3:
            return None
        reasons: dict[int, list[NamedCount]] = {24: [], 48: [], 168: []}
        for row in reason_rows:
            reasons[row["hours"]].append(NamedCount(name=row["name"], count=row["count"]))
        return ScreeningReconciliation(
            observed_at=rows[0]["observed_at"].isoformat(),
            telemetry_started_at=rows[0]["telemetry_started_at"].isoformat(),
            windows=tuple(
                ScreeningReconciliationWindow(
                    hours=row["hours"],
                    telemetry_complete=row["telemetry_complete"],
                    qualified=row["qualified"],
                    screened_out=row["screened_out"],
                    analysis_incomplete=row["analysis_incomplete"],
                    reasons=tuple(reasons[row["hours"]]),
                )
                for row in rows
            ),
            retry_wait=current["retry_wait"],
            published=current["published"],
            quarantined=current["quarantined"],
            failed=current["failed"],
            discord_sent=current["discord_sent"],
            discord_duplicates=current["discord_duplicates"],
            legacy_terminal_without_decision=current["legacy_terminal_without_decision"],
        )

    def get_ownership_operations(self) -> OwnershipOperations | None:
        """Return bounded private ownership queue and immutable receipt counts."""

        with self._connection() as connection:
            current = connection.execute(
                """
                SELECT clock_timestamp() AS observed_at, s.started_at,
                    count(j.*) FILTER (WHERE j.status = 'pending') AS pending,
                    count(j.*) FILTER (WHERE j.status = 'processing') AS processing,
                    count(j.*) FILTER (WHERE j.status = 'retry_wait') AS retry_wait,
                    count(j.*) FILTER (WHERE j.status = 'completed') AS completed,
                    count(j.*) FILTER (WHERE j.status = 'failed') AS failed,
                    extract(epoch FROM clock_timestamp() - min(j.discovered_at) FILTER (
                        WHERE j.status IN ('pending', 'processing', 'retry_wait')
                    )) AS oldest_backlog_seconds,
                    (SELECT count(*) FROM research_ownership_receipts) AS receipt_count,
                    (SELECT count(*) FROM research_ownership_routing_receipts
                     WHERE requires_model = false) AS model_free_retained,
                    (SELECT count(*) FROM research_ownership_routing_receipts
                     WHERE requires_model = true) AS escalated_for_review
                FROM research_ownership_state s
                LEFT JOIN research_ownership_jobs j ON true
                GROUP BY s.started_at
                """
            ).fetchone()
            form_rows = connection.execute(
                """
                SELECT form AS name, count(*) AS count
                FROM research_ownership_receipts
                GROUP BY form ORDER BY form
                """
            ).fetchall()
            failure_rows = connection.execute(
                """
                SELECT last_error_category AS name, count(*) AS count
                FROM research_ownership_jobs
                WHERE last_error_category IS NOT NULL
                GROUP BY last_error_category ORDER BY last_error_category
                """
            ).fetchall()
        if current is None:
            return None
        return OwnershipOperations(
            observed_at=current["observed_at"].isoformat(),
            telemetry_started_at=current["started_at"].isoformat(),
            pending=current["pending"],
            processing=current["processing"],
            retry_wait=current["retry_wait"],
            completed=current["completed"],
            failed=current["failed"],
            receipt_count=current["receipt_count"],
            model_free_retained=current["model_free_retained"],
            escalated_for_review=current["escalated_for_review"],
            oldest_backlog_seconds=current["oldest_backlog_seconds"],
            forms=tuple(NamedCount(name=row["name"], count=row["count"]) for row in form_rows),
            failure_categories=tuple(
                NamedCount(name=row["name"], count=row["count"]) for row in failure_rows
            ),
        )

    def get_financing_operations(self) -> FinancingOperations | None:
        """Return aggregate-only financing queue, receipt, and route counts."""

        with self._connection() as connection:
            current = connection.execute(
                """
                SELECT clock_timestamp() AS observed_at, s.started_at,
                    count(j.*) FILTER (WHERE j.status = 'pending') AS pending,
                    count(j.*) FILTER (WHERE j.status = 'processing') AS processing,
                    count(j.*) FILTER (WHERE j.status = 'retry_wait') AS retry_wait,
                    count(j.*) FILTER (WHERE j.status = 'completed') AS completed,
                    count(j.*) FILTER (WHERE j.status = 'no_terms') AS no_terms,
                    count(j.*) FILTER (WHERE j.status = 'failed') AS failed,
                    extract(epoch FROM clock_timestamp() - min(j.discovered_at) FILTER (
                        WHERE j.status IN ('pending', 'processing', 'retry_wait')
                    )) AS oldest_backlog_seconds,
                    (SELECT count(*) FROM research_financing_receipts) AS receipt_count,
                    (SELECT count(*) FROM research_financing_routing_receipts
                     WHERE requires_model = false) AS model_free_retained
                FROM research_financing_state s
                LEFT JOIN research_financing_jobs j ON true
                GROUP BY s.started_at
                """
            ).fetchone()
            form_rows = connection.execute(
                """
                SELECT form AS name, count(*) AS count
                FROM research_financing_receipts GROUP BY form ORDER BY form
                """
            ).fetchall()
            context_rows = connection.execute(
                """
                SELECT event_context AS name, count(*) AS count
                FROM research_financing_routing_receipts
                GROUP BY event_context ORDER BY event_context
                """
            ).fetchall()
            failure_rows = connection.execute(
                """
                SELECT last_error_category AS name, count(*) AS count
                FROM research_financing_jobs
                WHERE last_error_category IS NOT NULL
                GROUP BY last_error_category ORDER BY last_error_category
                """
            ).fetchall()
        if current is None:
            return None
        return FinancingOperations(
            observed_at=current["observed_at"].isoformat(),
            telemetry_started_at=current["started_at"].isoformat(),
            pending=current["pending"],
            processing=current["processing"],
            retry_wait=current["retry_wait"],
            completed=current["completed"],
            no_terms=current["no_terms"],
            failed=current["failed"],
            receipt_count=current["receipt_count"],
            model_free_retained=current["model_free_retained"],
            oldest_backlog_seconds=current["oldest_backlog_seconds"],
            forms=tuple(NamedCount(name=row["name"], count=row["count"]) for row in form_rows),
            contexts=tuple(
                NamedCount(name=row["name"], count=row["count"]) for row in context_rows
            ),
            failure_categories=tuple(
                NamedCount(name=row["name"], count=row["count"]) for row in failure_rows
            ),
        )

    def get_accounting_operations(self) -> AccountingOperations | None:
        """Return aggregate-only accounting queue, receipt, and route counts."""

        with self._connection() as connection:
            current = connection.execute(
                """
                SELECT clock_timestamp() AS observed_at, s.started_at,
                    count(j.*) FILTER (WHERE j.status = 'pending') AS pending,
                    count(j.*) FILTER (WHERE j.status = 'processing') AS processing,
                    count(j.*) FILTER (WHERE j.status = 'retry_wait') AS retry_wait,
                    count(j.*) FILTER (WHERE j.status = 'completed') AS completed,
                    count(j.*) FILTER (WHERE j.status = 'no_events') AS no_events,
                    count(j.*) FILTER (WHERE j.status = 'failed') AS failed,
                    extract(epoch FROM clock_timestamp() - min(j.discovered_at) FILTER (
                        WHERE j.status IN ('pending', 'processing', 'retry_wait')
                    )) AS oldest_backlog_seconds,
                    (SELECT count(*) FROM research_accounting_receipts) AS receipt_count,
                    (SELECT count(*) FROM research_accounting_routing_receipts
                     WHERE requires_model = false) AS model_free_retained
                FROM research_accounting_state s
                LEFT JOIN research_accounting_jobs j ON true
                GROUP BY s.started_at
                """
            ).fetchone()
            form_rows = connection.execute(
                """
                SELECT form AS name, count(*) AS count
                FROM research_accounting_receipts GROUP BY form ORDER BY form
                """
            ).fetchall()
            event_rows = connection.execute(
                """
                SELECT event->>'event_type' AS name, count(*) AS count
                FROM research_accounting_receipts r,
                     LATERAL jsonb_array_elements(r.record->'events') event
                GROUP BY event->>'event_type' ORDER BY event->>'event_type'
                """
            ).fetchall()
            comparison_rows = connection.execute(
                """
                SELECT event->>'comparison' AS name, count(*) AS count
                FROM research_accounting_receipts r,
                     LATERAL jsonb_array_elements(r.record->'events') event
                GROUP BY event->>'comparison' ORDER BY event->>'comparison'
                """
            ).fetchall()
            failure_rows = connection.execute(
                """
                SELECT last_error_category AS name, count(*) AS count
                FROM research_accounting_jobs
                WHERE last_error_category IS NOT NULL
                GROUP BY last_error_category ORDER BY last_error_category
                """
            ).fetchall()
        if current is None:
            return None
        return AccountingOperations(
            observed_at=current["observed_at"].isoformat(),
            telemetry_started_at=current["started_at"].isoformat(),
            pending=current["pending"],
            processing=current["processing"],
            retry_wait=current["retry_wait"],
            completed=current["completed"],
            no_events=current["no_events"],
            failed=current["failed"],
            receipt_count=current["receipt_count"],
            model_free_retained=current["model_free_retained"],
            oldest_backlog_seconds=current["oldest_backlog_seconds"],
            forms=tuple(NamedCount(name=row["name"], count=row["count"]) for row in form_rows),
            event_types=tuple(
                NamedCount(name=row["name"], count=row["count"]) for row in event_rows
            ),
            comparisons=tuple(
                NamedCount(name=row["name"], count=row["count"]) for row in comparison_rows
            ),
            failure_categories=tuple(
                NamedCount(name=row["name"], count=row["count"]) for row in failure_rows
            ),
        )

    def get_convergence_operations(self) -> ConvergenceOperations | None:
        """Return only closed aggregate counts from private contradiction receipts."""

        with self._connection() as connection:
            current = connection.execute(
                """
                SELECT clock_timestamp() AS observed_at, count(*) AS receipt_count
                FROM research_contradiction_receipts
                """
            ).fetchone()
            family_rows = connection.execute(
                """
                SELECT family AS name, count(*) AS count
                FROM research_contradiction_receipts
                GROUP BY family ORDER BY family
                """
            ).fetchall()
            disposition_rows = connection.execute(
                """
                SELECT disposition AS name, count(*) AS count
                FROM research_contradiction_receipts
                GROUP BY disposition ORDER BY disposition
                """
            ).fetchall()
            source_rows = connection.execute(
                """
                SELECT source AS name, count(*) AS count
                FROM (
                    SELECT CASE
                        WHEN record->'claim'->>'source_record_id'
                            ~ '^xbrl-liquidity:[0-9]{10}-[0-9]{2}-[0-9]{6}$'
                            AND family = 'LIQUIDITY' THEN 'XBRL_LIQUIDITY'
                        WHEN record->'claim'->>'source_record_id'
                            ~ '^financing-routing:[0-9]{10}-[0-9]{2}-[0-9]{6}$'
                            AND family = 'DILUTION' THEN 'FINANCING'
                        WHEN record->'claim'->>'source_record_id'
                            ~ '^ownership-routing:[0-9]{10}-[0-9]{2}-[0-9]{6}$'
                            AND family = 'INSIDER'
                            AND reason = 'PLANNED_SALE_IS_NOT_EXECUTED_TRANSACTION'
                            THEN 'OWNERSHIP_FORM_144'
                        WHEN record->'claim'->>'source_record_id'
                            ~ '^ownership-routing:[0-9]{10}-[0-9]{2}-[0-9]{6}$'
                            AND family = 'INSIDER' THEN 'OWNERSHIP_SECTION_16'
                        ELSE 'UNKNOWN'
                    END AS source
                    FROM research_contradiction_receipts
                ) classified
                GROUP BY source ORDER BY source
                """
            ).fetchall()
        if current is None:
            return None
        return ConvergenceOperations(
            observed_at=current["observed_at"].isoformat(),
            receipt_count=current["receipt_count"],
            families=tuple(NamedCount(name=row["name"], count=row["count"]) for row in family_rows),
            dispositions=tuple(
                NamedCount(name=row["name"], count=row["count"]) for row in disposition_rows
            ),
            sources=tuple(NamedCount(name=row["name"], count=row["count"]) for row in source_rows),
        )

    def get_outcome_science_operations(self) -> OutcomeScienceOperations | None:
        """Return aggregate-only private science state at one database cutoff."""

        with self._connection() as connection:
            row = connection.execute("SELECT clock_timestamp() AS observed_at").fetchone()
        if row is None:
            return None
        observed_at = row["observed_at"]
        if not isinstance(observed_at, datetime):
            return None
        snapshot = PostgresOutcomeScienceRepository(self._connection).snapshot_at(
            knowledge_cutoff_at=observed_at.astimezone(UTC)
        )
        return outcome_science_operations(snapshot)

    def get_engineering_measurements(self) -> EngineeringMeasurementsSnapshot | None:
        """Return only the latest closed private measurement receipts."""

        with self._connection() as connection:
            state = connection.execute(
                """
                SELECT started_at FROM research_engineering_measurement_state
                WHERE singleton
                """
            ).fetchone()
            rows = connection.execute(
                """
                SELECT DISTINCT ON (metric_name, window_hours) window_hours, record
                FROM (
                    SELECT metric_name,
                           CASE WHEN window_started_at = window_ended_at THEN 0
                                ELSE round(extract(epoch FROM (
                                    window_ended_at - window_started_at
                                )) / 3600)::integer END AS window_hours,
                           measured_at, receipt_id, record
                    FROM research_engineering_measurements
                    WHERE metric_version = '1.0.0'
                ) latest
                ORDER BY metric_name, window_hours, measured_at DESC, receipt_id DESC
                """
            ).fetchall()
        if state is None:
            return None
        receipts = tuple(
            (row["window_hours"], EngineeringMeasurementReceipt.model_validate(row["record"]))
            for row in rows
        )
        windows = tuple(
            EngineeringMeasurementWindow(
                hours=hours,
                measurements=tuple(
                    sorted(
                        (receipt for window, receipt in receipts if window == hours),
                        key=lambda item: item.metric_name.value,
                    )
                ),
            )
            for hours in (24, 168)
        )
        gauges = tuple(
            sorted(
                (receipt for window, receipt in receipts if window == 0),
                key=lambda item: item.metric_name.value,
            )
        )
        observed_at = max(
            (receipt.measured_at for _, receipt in receipts),
            default=state["started_at"],
        )
        return EngineeringMeasurementsSnapshot(
            observed_at=observed_at.isoformat(),
            telemetry_started_at=state["started_at"].isoformat(),
            windows=windows,
            gauges=gauges,
        )

    def get_funnel_snapshot(self) -> FunnelSnapshot | None:
        """Return aggregate-only application metrics for three fixed UTC windows."""

        with self._connection() as connection:
            rows = connection.execute(
                """
                WITH bounds AS (SELECT clock_timestamp() AS observed_at),
                     windows(hours) AS (VALUES (24), (48), (168))
                SELECT w.hours, b.observed_at, t.started_at AS telemetry_started_at,
                    t.started_at <= b.observed_at - w.hours * interval '1 hour'
                        AS telemetry_complete,
                    r.terminal_sec_polls + e.unterminated_sec_polls AS sec_polls_attempted,
                    e.unterminated_sec_polls, r.terminal_sec_polls, r.completed_sec_polls,
                    r.degraded_sec_polls, r.failed_sec_polls, r.discovered_rows,
                    c.unique_candidates, e.processing_transitions,
                    e.retry_wait_transitions, e.skipped_transitions,
                    e.failed_transitions, e.retained_transitions,
                    e.escalated_transitions, e.retrieved, e.parsed, e.normalized,
                    e.stale_recoveries, a.analyst_invocations, a.qwen_attempts,
                    a.valid_contracts, a.invalid_contracts, a.runtime_failures,
                    a.timeouts, a.pipeline_retry_attempts,
                    a.pipeline_retry_successes, a.work_item_retry_attempts,
                    a.work_item_retry_successes, a.latency_sample_size,
                    a.latency_minimum_ms, a.latency_p50_ms, a.latency_p95_ms,
                    a.latency_maximum_ms, v.verifier_accepted, v.verifier_rejected,
                    v.verifier_rejected AS quarantined, p.published, n.discord_sent,
                    n.discord_duplicates, h.human_leads, h.human_results,
                    h.human_delivered, h.human_delivery_failed, e.human_duplicates
                FROM windows w CROSS JOIN bounds b
                CROSS JOIN research_funnel_telemetry_state t
                LEFT JOIN LATERAL (
                    SELECT count(*) AS terminal_sec_polls,
                        count(*) FILTER (WHERE state = 'completed') AS completed_sec_polls,
                        count(*) FILTER (WHERE state = 'degraded') AS degraded_sec_polls,
                        count(*) FILTER (WHERE state = 'failed') AS failed_sec_polls,
                        coalesce(sum((record->>'discovered_count')::integer), 0)
                            AS discovered_rows
                    FROM research_runs
                    WHERE started_at >= b.observed_at - w.hours * interval '1 hour'
                ) r ON true
                LEFT JOIN LATERAL (
                    SELECT count(*) AS unique_candidates FROM research_candidates
                    WHERE discovered_at >= b.observed_at - w.hours * interval '1 hour'
                ) c ON true
                LEFT JOIN LATERAL (
                    SELECT
                        count(*) FILTER (
                            WHERE stage = 'sec_poll_attempted' AND terminal.run_id IS NULL
                        ) AS unterminated_sec_polls,
                        coalesce(sum(e.count) FILTER (WHERE stage = 'candidate_processing'), 0)
                            AS processing_transitions,
                        coalesce(sum(e.count) FILTER (WHERE stage = 'candidate_retry_wait'), 0)
                            AS retry_wait_transitions,
                        coalesce(sum(e.count) FILTER (WHERE stage = 'candidate_skipped'), 0)
                            AS skipped_transitions,
                        coalesce(sum(e.count) FILTER (WHERE stage = 'candidate_failed'), 0)
                            AS failed_transitions,
                        coalesce(sum(e.count) FILTER (WHERE stage = 'tier_retained'), 0)
                            AS retained_transitions,
                        coalesce(sum(e.count) FILTER (WHERE stage = 'tier_escalated'), 0)
                            AS escalated_transitions,
                        coalesce(sum(e.count) FILTER (WHERE stage = 'candidate_retrieved'), 0)
                            AS retrieved,
                        coalesce(sum(e.count) FILTER (WHERE stage = 'candidate_parsed'), 0)
                            AS parsed,
                        coalesce(sum(e.count) FILTER (
                            WHERE stage = 'companyfacts_normalized'
                        ), 0) AS normalized,
                        coalesce(sum(e.count) FILTER (WHERE stage = 'stale_recovered'), 0)
                            AS stale_recoveries,
                        coalesce(sum(e.count) FILTER (WHERE stage = 'human_duplicate'), 0)
                            AS human_duplicates
                    FROM research_pipeline_events e
                    LEFT JOIN research_runs terminal ON terminal.run_id = e.run_id
                    WHERE e.occurred_at >= b.observed_at - w.hours * interval '1 hour'
                ) e ON true
                LEFT JOIN LATERAL (
                    SELECT count(DISTINCT invocation_id) AS analyst_invocations,
                        count(*) AS qwen_attempts,
                        count(*) FILTER (WHERE outcome = 'accepted') AS valid_contracts,
                        count(*) FILTER (WHERE outcome = 'rejected') AS invalid_contracts,
                        count(*) FILTER (WHERE outcome = 'runtime_error') AS runtime_failures,
                        count(*) FILTER (WHERE failure_category = 'timeout') AS timeouts,
                        count(*) FILTER (WHERE attempt_number > 1) AS pipeline_retry_attempts,
                        count(*) FILTER (
                            WHERE attempt_number > 1 AND outcome = 'accepted'
                        ) AS pipeline_retry_successes,
                        count(*) FILTER (
                            WHERE work_attempt > 1 AND attempt_number = 1
                        ) AS work_item_retry_attempts,
                        count(*) FILTER (
                            WHERE work_attempt > 1 AND attempt_number = 1
                              AND outcome = 'accepted'
                        ) AS work_item_retry_successes,
                        count(*) FILTER (WHERE state = 'completed'
                            AND failure_path IS DISTINCT FROM 'worker.processing_lease_expired')
                            AS latency_sample_size,
                        min(latency_ms) FILTER (WHERE state = 'completed'
                            AND failure_path IS DISTINCT FROM 'worker.processing_lease_expired')
                            AS latency_minimum_ms,
                        percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms)
                            FILTER (WHERE state = 'completed'
                                AND failure_path IS DISTINCT FROM
                                    'worker.processing_lease_expired') AS latency_p50_ms,
                        percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)
                            FILTER (WHERE state = 'completed'
                                AND failure_path IS DISTINCT FROM
                                    'worker.processing_lease_expired') AS latency_p95_ms,
                        max(latency_ms) FILTER (WHERE state = 'completed'
                            AND failure_path IS DISTINCT FROM 'worker.processing_lease_expired')
                            AS latency_maximum_ms
                    FROM research_analyst_attempts
                    WHERE started_at >= b.observed_at - w.hours * interval '1 hour'
                ) a ON true
                LEFT JOIN LATERAL (
                    SELECT count(*) FILTER (WHERE disposition = 'approved')
                               AS verifier_accepted,
                           count(*) FILTER (WHERE disposition <> 'approved')
                               AS verifier_rejected
                    FROM research_verification_dispositions
                    WHERE decided_at >= b.observed_at - w.hours * interval '1 hour'
                ) v ON true
                LEFT JOIN LATERAL (
                    SELECT count(*) AS published FROM research_briefs
                    WHERE published_at >= b.observed_at - w.hours * interval '1 hour'
                ) p ON true
                LEFT JOIN LATERAL (
                    SELECT count(*) FILTER (WHERE status = 'sent') AS discord_sent,
                           count(*) FILTER (WHERE status = 'duplicate') AS discord_duplicates
                    FROM research_notification_deliveries
                    WHERE completed_at >= b.observed_at - w.hours * interval '1 hour'
                ) n ON true
                LEFT JOIN LATERAL (
                    SELECT
                        (SELECT count(*) FROM research_human_leads
                         WHERE submitted_at >= b.observed_at - w.hours * interval '1 hour')
                            AS human_leads,
                        (SELECT count(*) FROM research_human_results
                         WHERE created_at >= b.observed_at - w.hours * interval '1 hour')
                            AS human_results,
                        (SELECT count(*) FROM research_human_result_deliveries
                         WHERE updated_at >= b.observed_at - w.hours * interval '1 hour'
                           AND status = 'delivered') AS human_delivered,
                        (SELECT count(*) FROM research_human_result_deliveries
                         WHERE updated_at >= b.observed_at - w.hours * interval '1 hour'
                           AND status = 'failed') AS human_delivery_failed
                ) h ON true
                ORDER BY w.hours
                """
            ).fetchall()
            categories = connection.execute(
                """
                WITH bounds AS (SELECT clock_timestamp() AS observed_at),
                     windows(hours) AS (VALUES (24), (48), (168)),
                     failures AS (
                        SELECT started_at AS occurred_at,
                               'analyst:' || failure_category AS name, 1 AS count
                        FROM research_analyst_attempts WHERE failure_category IS NOT NULL
                        UNION ALL
                        SELECT occurred_at, 'candidate:' || failure_category, count
                        FROM research_pipeline_events WHERE failure_category IS NOT NULL
                     )
                SELECT w.hours, f.name, sum(f.count)::bigint AS count
                FROM windows w CROSS JOIN bounds b JOIN failures f
                  ON f.occurred_at >= b.observed_at - w.hours * interval '1 hour'
                GROUP BY w.hours, f.name ORDER BY w.hours, f.name
                """
            ).fetchall()
            detector_rows = connection.execute(
                """
                WITH bounds AS (SELECT clock_timestamp() AS observed_at),
                     windows(hours) AS (VALUES (24), (48), (168))
                SELECT w.hours, d.detector_name AS name,
                    count(*) FILTER (WHERE d.invoked) AS invoked,
                    count(*) FILTER (WHERE d.status = 'positive') AS positive,
                    count(*) FILTER (WHERE d.status = 'negative') AS negative,
                    count(*) FILTER (WHERE d.status = 'unknown') AS unknown,
                    count(*) FILTER (WHERE d.status = 'not_assessed') AS not_assessed,
                    count(*) FILTER (WHERE d.status = 'insufficient_evidence')
                        AS insufficient_evidence,
                    count(*) FILTER (WHERE d.contributed_to_escalation)
                        AS escalation_contributions
                FROM windows w CROSS JOIN bounds b JOIN research_detector_receipts d
                  ON d.observed_at >= b.observed_at - w.hours * interval '1 hour'
                GROUP BY w.hours, d.detector_name ORDER BY w.hours, d.detector_name
                """
            ).fetchall()
            current = connection.execute(
                """
                SELECT clock_timestamp() AS observed_at,
                    count(*) FILTER (WHERE status = 'pending') AS pending,
                    count(*) FILTER (WHERE status = 'processing') AS processing,
                    count(*) FILTER (WHERE status = 'retry_wait') AS retry_wait,
                    count(*) FILTER (WHERE status = 'skipped') AS skipped,
                    count(*) FILTER (WHERE status = 'published') AS published,
                    count(*) FILTER (WHERE status = 'quarantined') AS quarantined,
                    count(*) FILTER (WHERE status = 'failed') AS failed,
                    count(*) FILTER (WHERE tier_outcome = 'retain') AS retained,
                    count(*) FILTER (WHERE tier_outcome = 'escalate') AS escalated,
                    count(*) FILTER (
                        WHERE status IN ('pending', 'processing', 'retry_wait')
                    ) AS backlog_depth,
                    extract(epoch FROM clock_timestamp() - min(discovered_at) FILTER (
                        WHERE status IN ('pending', 'processing', 'retry_wait')
                    )) AS oldest_backlog_seconds
                FROM research_candidates
                """
            ).fetchone()
        if current is None or len(rows) != 3:
            return None
        category_map: dict[int, list[NamedCount]] = {24: [], 48: [], 168: []}
        for category in categories:
            category_map[category["hours"]].append(
                NamedCount(name=category["name"], count=category["count"])
            )
        detector_map: dict[int, dict[str, DetectorCount]] = {24: {}, 48: {}, 168: {}}
        for detector in detector_rows:
            detector_map[detector["hours"]][detector["name"]] = DetectorCount(
                **{
                    key: detector[key]
                    for key in (
                        "name",
                        "invoked",
                        "positive",
                        "negative",
                        "unknown",
                        "not_assessed",
                        "insufficient_evidence",
                        "escalation_contributions",
                    )
                }
            )
        windows = tuple(
            FunnelWindow(
                **{
                    key: value
                    for key, value in row.items()
                    if key not in {"observed_at", "telemetry_started_at", "hours"}
                },
                hours=row["hours"],
                latency_sample_label=(
                    "small_n" if row["latency_sample_size"] < 30 else "descriptive"
                ),
                failure_categories=tuple(category_map[row["hours"]]),
                detectors=tuple(
                    detector_map[row["hours"]].get(
                        name,
                        DetectorCount(
                            name=name,
                            invoked=0,
                            positive=0,
                            negative=0,
                            unknown=0,
                            not_assessed=0,
                            insufficient_evidence=0,
                            escalation_contributions=0,
                        ),
                    )
                    for name in DETECTOR_NAMES
                ),
            )
            for row in rows
        )
        return FunnelSnapshot(
            observed_at=current["observed_at"].isoformat(),
            telemetry_started_at=rows[0]["telemetry_started_at"].isoformat(),
            windows=windows,
            current=FunnelCurrent(
                **{
                    key: current[key]
                    for key in (
                        "pending",
                        "processing",
                        "retry_wait",
                        "skipped",
                        "published",
                        "quarantined",
                        "failed",
                        "retained",
                        "escalated",
                        "backlog_depth",
                        "oldest_backlog_seconds",
                    )
                }
            ),
            unavailable_metrics=(),
        )


def _validate_page(limit: int | None, offset: int) -> None:
    if limit is not None and (limit < 1 or limit > 500):
        raise ValueError("research page limit must be between one and 500")
    if offset < 0 or offset > 100_000:
        raise ValueError("research page offset must be between zero and 100000")


def _validate_query(query: str | None) -> str | None:
    if query is None:
        return None
    normalized = query.strip().casefold()
    if not normalized:
        return None
    if len(normalized) > 64 or any(ord(character) < 32 for character in normalized):
        raise ValueError("research query must contain at most 64 printable characters")
    return normalized
