"""Durable PostgreSQL state for discovery, publication, runs, and visibility."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from kalki_market_intelligence.analysis.attempts import (
    AnalystAttemptOrigin,
    AnalystAttemptReceipt,
    AnalystAttemptStart,
    interrupted_analyst_attempt_receipt,
)
from kalki_market_intelligence.analysis.contracts import AnalystReconsideration
from kalki_market_intelligence.database import ConnectionFactory
from kalki_market_intelligence.forensics.detectors import ForensicStatus
from kalki_market_intelligence.forensics.filing_change import (
    FilingChangeSelectionReceipt,
    FilingChangeSnapshot,
    compare_and_select_filing_changes,
)
from kalki_market_intelligence.forensics.novelty import (
    EventCategory,
    EventDisclosure,
    EventLineageReceipt,
)
from kalki_market_intelligence.forensics.tiers import TierDecision, TierOutcome
from kalki_market_intelligence.notifications.contracts import NotificationDelivery
from kalki_market_intelligence.radar.contracts import (
    FilingCandidate,
    PublicationGateMode,
    RadarRun,
    ResearchBrief,
    WorkerSnapshot,
)
from kalki_market_intelligence.radar.focus import (
    FocusMembershipEvent,
    FocusUniverseSnapshot,
    project_focus_universe,
)
from kalki_market_intelligence.radar.measurement_runtime import (
    MEASUREMENT_CADENCE_SECONDS,
    AnalystCallObservation,
    DeliveryObservation,
    EngineeringMeasurementInput,
    HostResourceObservation,
    PublicationObservation,
    QueueObservation,
    TerminalDecisionObservation,
    build_runtime_engineering_measurements,
)
from kalki_market_intelligence.radar.measurements import (
    EngineeringMeasurementReceipt,
    FilingLatencyReceipt,
    build_filing_latency_receipt,
)
from kalki_market_intelligence.radar.screening import (
    AutonomousScreeningDecision,
    ScreeningDisposition,
)
from kalki_market_intelligence.radar.sec_links import ValidatedSecFilingLinks
from kalki_market_intelligence.radar.telemetry import (
    DetectorName,
    DetectorReceipt,
    PipelineEvent,
    PipelineFailureCategory,
    PipelineStage,
)
from kalki_market_intelligence.research.feedback import HumanResearchFeedback
from kalki_market_intelligence.research.intake import HumanLeadStatus, HumanResearchLead
from kalki_market_intelligence.research.results import HumanResearchResult
from kalki_market_intelligence.verification.contracts import (
    VerificationDisposition,
    VerificationOutcome,
    VerifierAudit,
)
from kalki_market_intelligence.web.operations import collect_resources

OPERATION_COUNTERS = frozenset(
    {
        "analyst_candidates",
        "deterministic_rejections",
        "verifier_reviews",
        "verifier_approvals",
        "verifier_challenges",
        "analyst_retries",
        "verifier_persistent_disagreements",
        "verifier_errors",
        "final_publications",
    }
)


@dataclass(frozen=True, slots=True)
class ClaimedCandidate:
    candidate: FilingCandidate
    attempts: int
    reconsideration: AnalystReconsideration | None
    first_audit: VerifierAudit | None


class EventNoveltyReplayConflict(RuntimeError):
    """An immutable event identity was replayed with different closed content."""


class FocusMembershipReplayConflict(RuntimeError):
    """An immutable Focus event identity was replayed with different content."""


class SecLinkReceiptReplayConflict(RuntimeError):
    """An immutable SEC-link receipt identity was replayed with different content."""


class EngineeringMeasurementReplayConflict(RuntimeError):
    """An immutable measurement identity was replayed with different content."""


class FilingChangeReplayConflict(RuntimeError):
    """An immutable filing-change identity was replayed with different content."""


class PostgresRadarStore:
    def __init__(self, connection: ConnectionFactory) -> None:
        self._connection = connection

    def start_analyst_attempt(self, attempt: AnalystAttemptStart) -> None:
        """Insert identity and bounded sizes before invoking the local model."""

        context = attempt.context
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO research_analyst_attempts (
                    attempt_id, invocation_id, origin, candidate_accession_number,
                    lead_id, ticker, cik, accession_number, filing_form, work_attempt,
                    semantic_retry, provider_name, model_name, model_digest,
                    prompt_version, output_schema_version, validation_version, role,
                    attempt_number, started_at, input_evidence_count,
                    input_evidence_characters, system_prompt_characters,
                    user_prompt_characters, context_tokens, maximum_output_tokens,
                    state, record
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, 'started', %s
                )
                """,
                (
                    attempt.attempt_id,
                    attempt.invocation_id,
                    context.origin.value,
                    context.candidate_accession_number,
                    context.lead_id,
                    context.ticker,
                    context.cik,
                    context.accession_number,
                    context.filing_form,
                    context.work_attempt,
                    context.semantic_retry,
                    attempt.provider_name,
                    attempt.model_name,
                    attempt.model_digest,
                    attempt.prompt_version,
                    attempt.output_schema_version,
                    attempt.validation_version,
                    attempt.role.value,
                    attempt.attempt_number,
                    attempt.started_at,
                    attempt.input_evidence_count,
                    attempt.input_evidence_characters,
                    attempt.system_prompt_characters,
                    attempt.user_prompt_characters,
                    attempt.context_tokens,
                    attempt.maximum_output_tokens,
                    Jsonb(attempt.model_dump(mode="json")),
                ),
            )

    def append_validated_sec_links(self, receipt: ValidatedSecFilingLinks) -> None:
        """Append one source-bound link receipt or accept an exact replay."""

        with self._connection() as connection:
            self._insert_validated_sec_links(connection, receipt)

    def finish_analyst_attempt(self, receipt: AnalystAttemptReceipt) -> None:
        """Complete a started receipt exactly once without storing generated text."""

        with self._connection() as connection:
            self._finish_analyst_attempt(connection, receipt)

    @staticmethod
    def _finish_analyst_attempt(connection: object, receipt: AnalystAttemptReceipt) -> None:
        result = connection.execute(  # type: ignore[attr-defined]
            """
                UPDATE research_analyst_attempts
                SET state = 'completed', completed_at = %s, latency_ms = %s,
                    response_sha256 = %s, response_characters = %s, response_bytes = %s,
                    prompt_tokens = %s, generated_tokens = %s, parse_status = %s,
                    schema_status = %s, evidence_status = %s, failure_layer = %s,
                    failure_category = %s, failure_path = %s, retry_eligible = %s,
                    retry_scope = %s, outcome = %s, terminal_disposition = %s,
                    record = %s
                WHERE attempt_id = %s AND state = 'started'
                """,
            (
                receipt.completed_at,
                receipt.latency_ms,
                receipt.response_sha256,
                receipt.response_characters,
                receipt.response_bytes,
                receipt.prompt_tokens,
                receipt.generated_tokens,
                receipt.parse_status.value,
                receipt.schema_status.value,
                receipt.evidence_status.value,
                receipt.failure_layer.value,
                (receipt.failure_category.value if receipt.failure_category is not None else None),
                receipt.failure_path,
                receipt.retry_eligible,
                receipt.retry_scope.value,
                receipt.outcome.value,
                receipt.terminal_disposition.value,
                Jsonb(receipt.model_dump(mode="json")),
                receipt.start.attempt_id,
            ),
        )
        if result.rowcount != 1:
            raise RuntimeError("analyst attempt is absent or already completed")

    def candidate_analyst_attempt_ids(self, accession_number: str) -> tuple[UUID, ...]:
        """Return completed content-free attempt lineage available at decision time."""

        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT attempt_id FROM research_analyst_attempts
                WHERE origin = 'candidate'
                  AND candidate_accession_number = %s
                  AND state = 'completed'
                ORDER BY started_at, attempt_id
                LIMIT 24
                """,
                (accession_number,),
            ).fetchall()
        return tuple(row["attempt_id"] for row in rows)

    def human_analyst_attempt_receipts(self, lead_id: UUID) -> tuple[AnalystAttemptReceipt, ...]:
        """Return completed content-free receipts for one private human lead."""

        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT record
                FROM research_analyst_attempts
                WHERE lead_id = %s AND origin = 'human' AND state = 'completed'
                ORDER BY started_at, role, attempt_number, attempt_id
                """,
                (lead_id,),
            ).fetchall()
        return tuple(AnalystAttemptReceipt.model_validate(row["record"]) for row in rows)

    def append_pipeline_event(self, event: PipelineEvent) -> None:
        """Append content-free lifecycle telemetry for private aggregation."""

        with self._connection() as connection:
            self._insert_pipeline_event(connection, event)

    def generate_engineering_measurements(self, *, now: datetime) -> int:
        """Append at most one complete prospective measurement set per hour."""

        with self._connection() as connection:
            state = connection.execute(
                """
                SELECT started_at FROM research_engineering_measurement_state
                WHERE singleton
                """
            ).fetchone()
            if state is None:
                raise RuntimeError("engineering measurement state is absent")
            telemetry_started_at = state["started_at"]
            latest = connection.execute(
                "SELECT max(measured_at) AS measured_at FROM research_engineering_measurements"
            ).fetchone()
            if (
                latest is not None
                and latest["measured_at"] is not None
                and latest["measured_at"] < now
                and now < latest["measured_at"] + timedelta(seconds=MEASUREMENT_CADENCE_SECONDS)
            ):
                return 0
            resources = collect_resources()
            logical_cpu_count = min(max(os.cpu_count() or 1, 1), 256)
            analyst_rows = connection.execute(
                """
                SELECT completed_at, accession_number, input_evidence_characters,
                       prompt_tokens, latency_ms, failure_category, failure_path
                FROM research_analyst_attempts
                WHERE origin = 'candidate' AND state = 'completed'
                  AND completed_at >= %s AND completed_at <= %s
                ORDER BY completed_at, attempt_id
                """,
                (telemetry_started_at, now),
            ).fetchall()
            decision_rows = connection.execute(
                """
                SELECT decided_at, accession_number, disposition,
                       cardinality(analyst_attempt_ids) AS analyst_attempt_count
                FROM research_autonomous_screening_decisions
                WHERE decided_at >= %s AND decided_at <= %s
                ORDER BY decided_at, decision_id
                """,
                (telemetry_started_at, now),
            ).fetchall()
            publication_rows = connection.execute(
                """
                SELECT brief_id, accession_number, published_at
                FROM research_briefs ORDER BY published_at, brief_id
                """
            ).fetchall()
            delivery_rows = connection.execute(
                """
                SELECT brief_id, completed_at, status
                FROM research_notification_deliveries
                ORDER BY completed_at, delivery_id
                """
            ).fetchall()
            queue_row = connection.execute(
                """
                SELECT count(*) AS depth,
                       extract(epoch FROM %s - min(discovered_at))::bigint
                           AS oldest_age_seconds
                FROM research_candidates
                WHERE status = 'pending'
                   OR (status = 'retry_wait' AND next_attempt_at <= %s)
                """,
                (now, now),
            ).fetchone()
            if queue_row is None:
                raise RuntimeError("engineering queue observation is absent")
            lifecycle_rows = connection.execute(
                """
                SELECT c.accession_number, c.discovered_at, d.decided_at,
                       l.lineage_id AS event_lineage_id,
                       l.authoritative_first_known_at,
                       b.published_at, sent.completed_at AS alerted_at
                FROM research_autonomous_screening_decisions d
                JOIN research_candidates c USING (accession_number)
                LEFT JOIN research_briefs b USING (accession_number)
                LEFT JOIN LATERAL (
                    SELECT el.lineage_id, el.authoritative_first_known_at
                    FROM research_event_lineage el
                    JOIN research_event_disclosures ed
                      ON ed.disclosure_id = el.current_disclosure_id
                    WHERE ed.accession_number = c.accession_number
                    ORDER BY el.evaluated_at DESC, el.lineage_id DESC
                    LIMIT 1
                ) l ON true
                LEFT JOIN LATERAL (
                    SELECT n.completed_at
                    FROM research_notification_deliveries n
                    WHERE n.brief_id = b.brief_id AND n.status = 'sent'
                    ORDER BY n.completed_at, n.delivery_id LIMIT 1
                ) sent ON true
                WHERE d.decided_at >= %s AND d.decided_at <= %s
                ORDER BY d.decided_at, d.decision_id
                """,
                (telemetry_started_at, now),
            ).fetchall()

            latency_receipts = tuple(
                build_filing_latency_receipt(
                    accession_number=row["accession_number"],
                    event_lineage_id=row["event_lineage_id"],
                    authoritative_first_known_at=row["authoritative_first_known_at"],
                    discovered_at=row["discovered_at"],
                    published_at=row["published_at"],
                    alerted_at=row["alerted_at"],
                    measured_at=max(
                        item
                        for item in (
                            row["decided_at"],
                            row["published_at"],
                            row["alerted_at"],
                        )
                        if item is not None
                    ),
                )
                for row in lifecycle_rows
            )
            for receipt in latency_receipts:
                self._insert_filing_latency_receipt(connection, receipt)

            source = EngineeringMeasurementInput(
                telemetry_started_at=telemetry_started_at,
                observed_at=now,
                analyst_calls=tuple(
                    AnalystCallObservation(
                        completed_at=row["completed_at"],
                        accession_number=row["accession_number"],
                        evidence_characters=row["input_evidence_characters"],
                        prompt_tokens=row["prompt_tokens"],
                        latency_ms=row["latency_ms"],
                        timed_out=row["failure_category"] == "timeout",
                        latency_observed=(row["failure_path"] != "worker.processing_lease_expired"),
                    )
                    for row in analyst_rows
                ),
                terminal_decisions=tuple(
                    TerminalDecisionObservation(
                        decided_at=row["decided_at"],
                        accession_number=row["accession_number"],
                        disposition=row["disposition"],
                        analyst_attempt_count=row["analyst_attempt_count"],
                    )
                    for row in decision_rows
                ),
                publications=tuple(
                    PublicationObservation(
                        brief_id=str(row["brief_id"]),
                        accession_number=row["accession_number"],
                        published_at=row["published_at"],
                    )
                    for row in publication_rows
                ),
                deliveries=tuple(
                    DeliveryObservation(
                        brief_id=str(row["brief_id"]),
                        completed_at=row["completed_at"],
                        status=row["status"],
                    )
                    for row in delivery_rows
                ),
                filing_latencies=latency_receipts,
                queue=QueueObservation(
                    depth=queue_row["depth"],
                    oldest_age_seconds=queue_row["oldest_age_seconds"],
                ),
                resources=HostResourceObservation(
                    logical_cpu_count=logical_cpu_count,
                    load_1m=resources.load_1m,
                    cpu_temperature_celsius=resources.temperature_celsius,
                    memory_available_bytes=resources.memory_available_bytes,
                    swap_used_bytes=resources.swap_used_bytes,
                ),
            )
            measurements = build_runtime_engineering_measurements(source)
            for measurement in measurements:
                self._insert_engineering_measurement(connection, measurement)
        return len(measurements) + len(latency_receipts)

    def event_disclosures(
        self,
        *,
        issuer_cik: str,
        category: EventCategory,
        exclude_source_content_sha256: str | None = None,
    ) -> tuple[EventDisclosure, ...]:
        """Return bounded prior primary-source events for deterministic comparison."""

        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT record FROM research_event_disclosures
                WHERE issuer_cik = %s AND category = %s
                  AND (%s::text IS NULL OR source_content_sha256 <> %s::text)
                ORDER BY COALESCE(published_at, retrieved_at), disclosure_id
                LIMIT 64
                """,
                (
                    issuer_cik.zfill(10),
                    category.value,
                    exclude_source_content_sha256,
                    exclude_source_content_sha256,
                ),
            ).fetchall()
        return tuple(EventDisclosure.model_validate(row["record"]) for row in rows)

    def append_event_lineage(self, receipt: EventLineageReceipt) -> EventLineageReceipt:
        """Persist once, returning the first immutable decision on a stable retry."""

        disclosure = receipt.current_disclosure
        prior_id = (
            receipt.prior_related_disclosure.disclosure_id
            if receipt.prior_related_disclosure is not None
            else None
        )
        with self._connection() as connection:
            existing = connection.execute(
                "SELECT record FROM research_event_lineage WHERE lineage_id = %s",
                (receipt.lineage_id,),
            ).fetchone()
            if existing is not None:
                return EventLineageReceipt.model_validate(existing["record"])
            first_id = None
            if receipt.authoritative_first_known_disclosure is not None:
                row = connection.execute(
                    """
                    SELECT disclosure_id FROM research_event_disclosures
                    WHERE source_content_sha256 = %s
                      AND issuer_cik = %s AND category = %s
                    ORDER BY disclosure_id LIMIT 1
                    """,
                    (
                        receipt.authoritative_first_known_disclosure.source_content_sha256,
                        disclosure.issuer_cik,
                        disclosure.category.value,
                    ),
                ).fetchone()
                first_id = row["disclosure_id"] if row is not None else None
            self._insert_event_disclosure(connection, disclosure)
            inserted = connection.execute(
                """
                INSERT INTO research_event_lineage (
                    lineage_id, current_disclosure_id, prior_related_disclosure_id,
                    authoritative_first_known_disclosure_id,
                    authoritative_first_known_at, evaluated_at, disposition, reason,
                    prior_search_complete, rule_version, schema_version, record
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                ) ON CONFLICT (lineage_id) DO NOTHING
                RETURNING record
                """,
                (
                    receipt.lineage_id,
                    disclosure.disclosure_id,
                    prior_id,
                    first_id,
                    receipt.authoritative_first_known_at,
                    receipt.evaluated_at,
                    receipt.disposition.value,
                    receipt.reason.value,
                    receipt.prior_search_complete,
                    receipt.rule_version,
                    receipt.schema_version,
                    Jsonb(receipt.model_dump(mode="json")),
                ),
            ).fetchone()
            if inserted is None:
                existing = connection.execute(
                    "SELECT record FROM research_event_lineage WHERE lineage_id = %s",
                    (receipt.lineage_id,),
                ).fetchone()
                if (
                    existing is None
                    or EventLineageReceipt.model_validate(
                        existing["record"]
                    ).current_disclosure.disclosure_id
                    != receipt.current_disclosure.disclosure_id
                ):
                    raise EventNoveltyReplayConflict(
                        "event lineage identity already has different immutable content"
                    )
                return EventLineageReceipt.model_validate(existing["record"])
            return receipt

    def append_event_disclosure(self, disclosure: EventDisclosure) -> None:
        """Append one source-bound disclosure for later novelty comparisons."""

        with self._connection() as connection:
            self._insert_event_disclosure(connection, disclosure)

    def append_filing_change_snapshot(self, snapshot: FilingChangeSnapshot) -> None:
        """Append one exact private snapshot or accept its identical replay."""

        snapshot = FilingChangeSnapshot.model_validate(snapshot.model_dump(mode="json"))
        with self._connection() as connection:
            self._insert_filing_change_snapshot(connection, snapshot)

    def filing_change_snapshot_for_accession(
        self,
        *,
        cik: str,
        accession_number: str,
        knowledge_cutoff_at: datetime,
    ) -> FilingChangeSnapshot | None:
        """Return the first immutable same-accession source available by the cutoff."""

        if not cik.isascii() or not cik.isdigit() or not 1 <= len(cik) <= 10:
            raise ValueError("filing-change lookup requires a canonical numeric CIK")
        if knowledge_cutoff_at.tzinfo is None or knowledge_cutoff_at.utcoffset() is None:
            raise ValueError("filing-change knowledge cutoff must be timezone-aware")
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT record FROM research_filing_change_snapshots
                WHERE canonical_cik = %s AND accession_number = %s
                  AND available_at <= %s AND retrieved_at <= %s
                ORDER BY available_at, retrieved_at, manifest_sha256 LIMIT 2
                """,
                (
                    cik.zfill(10),
                    accession_number,
                    knowledge_cutoff_at.astimezone(UTC),
                    knowledge_cutoff_at.astimezone(UTC),
                ),
            ).fetchall()
        if len(rows) > 1:
            raise FilingChangeReplayConflict(
                "filing-change accession has multiple immutable source snapshots"
            )
        if not rows:
            return None
        return FilingChangeSnapshot.model_validate(rows[0]["record"])

    def filing_change_snapshots(
        self,
        *,
        cik: str,
        knowledge_cutoff_at: datetime,
        exclude_accession_number: str | None = None,
        limit: int = 16,
    ) -> tuple[FilingChangeSnapshot, ...]:
        """Return only issuer snapshots available and retrieved by the cutoff."""

        if not cik.isascii() or not cik.isdigit() or not 1 <= len(cik) <= 10:
            raise ValueError("filing-change lookup requires a canonical numeric CIK")
        if not 1 <= limit <= 64:
            raise ValueError("filing-change snapshot limit must be between one and 64")
        if knowledge_cutoff_at.tzinfo is None or knowledge_cutoff_at.utcoffset() is None:
            raise ValueError("filing-change knowledge cutoff must be timezone-aware")
        knowledge_cutoff_at = knowledge_cutoff_at.astimezone(UTC)
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT record FROM research_filing_change_snapshots
                WHERE canonical_cik = %s
                  AND available_at <= %s AND retrieved_at <= %s
                  AND (%s::text IS NULL OR accession_number <> %s::text)
                ORDER BY available_at DESC, retrieved_at DESC, manifest_sha256
                LIMIT %s
                """,
                (
                    cik.zfill(10),
                    knowledge_cutoff_at,
                    knowledge_cutoff_at,
                    exclude_accession_number,
                    exclude_accession_number,
                    limit,
                ),
            ).fetchall()
        return tuple(FilingChangeSnapshot.model_validate(row["record"]) for row in rows)

    def append_filing_change_selection(
        self,
        previous: FilingChangeSnapshot,
        current: FilingChangeSnapshot,
        receipt: FilingChangeSelectionReceipt,
    ) -> None:
        """Atomically persist both sources and their deterministic selection."""

        previous = FilingChangeSnapshot.model_validate(previous.model_dump(mode="json"))
        current = FilingChangeSnapshot.model_validate(current.model_dump(mode="json"))
        receipt = FilingChangeSelectionReceipt.model_validate(receipt.model_dump(mode="json"))
        expected = compare_and_select_filing_changes(
            previous,
            current,
            relationship=receipt.relationship,
        )
        if expected != receipt:
            raise ValueError("filing-change selection does not reconcile to its snapshots")
        with self._connection() as connection:
            self._insert_filing_change_snapshot(connection, previous)
            self._insert_filing_change_snapshot(connection, current)
            inserted = connection.execute(
                """
                INSERT INTO research_filing_change_selections (
                    receipt_id, relationship, previous_accession_number,
                    current_accession_number, previous_manifest_sha256,
                    current_manifest_sha256, selected_characters,
                    selection_sha256, recorded_at, extraction_version,
                    selection_version, schema_version, record
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                ) ON CONFLICT (receipt_id) DO NOTHING
                RETURNING record
                """,
                (
                    receipt.receipt_id,
                    receipt.relationship.value,
                    receipt.previous_accession_number,
                    receipt.current_accession_number,
                    receipt.previous_manifest_sha256,
                    receipt.current_manifest_sha256,
                    receipt.selected_characters,
                    receipt.selection_sha256,
                    max(previous.retrieved_at, current.retrieved_at),
                    receipt.extraction_version,
                    receipt.selection_version,
                    receipt.schema_version,
                    Jsonb(receipt.model_dump(mode="json")),
                ),
            ).fetchone()
            if inserted is None:
                existing = connection.execute(
                    "SELECT record FROM research_filing_change_selections WHERE receipt_id = %s",
                    (receipt.receipt_id,),
                ).fetchone()
                if (
                    existing is None
                    or FilingChangeSelectionReceipt.model_validate(existing["record"]) != receipt
                ):
                    raise FilingChangeReplayConflict(
                        "filing-change selection identity has different immutable content"
                    )

    def append_focus_membership_event(self, event: FocusMembershipEvent) -> None:
        """Append one serialized membership transition or accept an exact replay."""

        with self._connection() as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (event.canonical_cik,),
            )
            existing = connection.execute(
                "SELECT record FROM research_focus_membership_events WHERE event_id = %s",
                (event.event_id,),
            ).fetchone()
            if existing is not None:
                if FocusMembershipEvent.model_validate(existing["record"]) != event:
                    raise FocusMembershipReplayConflict(
                        "focus membership identity already has different immutable content"
                    )
                return
            connection.execute(
                """
                INSERT INTO research_focus_membership_events (
                    event_id, canonical_cik, ticker, company_name, action, reason,
                    effective_at, recorded_at, universe_version, supersedes_event_id,
                    schema_version, record
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    event.event_id,
                    event.canonical_cik,
                    event.ticker,
                    event.company_name,
                    event.action.value,
                    event.reason.value,
                    event.effective_at,
                    event.recorded_at,
                    event.universe_version,
                    event.supersedes_event_id,
                    event.schema_version,
                    Jsonb(event.model_dump(mode="json")),
                ),
            )

    def focus_universe(self, *, as_of: datetime) -> FocusUniverseSnapshot:
        """Replay only membership transitions available by the requested cutoff."""

        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT record FROM research_focus_membership_events
                WHERE effective_at <= %s AND recorded_at <= %s
                ORDER BY canonical_cik, recorded_at, event_id
                """,
                (as_of, as_of),
            ).fetchall()
        return project_focus_universe(
            tuple(FocusMembershipEvent.model_validate(row["record"]) for row in rows),
            as_of=as_of,
        )

    @staticmethod
    def _insert_event_disclosure(connection: object, disclosure: EventDisclosure) -> None:
        inserted = connection.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO research_event_disclosures (
                disclosure_id, issuer_cik, issuer_name, category, context,
                event_fingerprint, fact_fingerprint, source_class,
                accession_number, source_url, source_content_sha256,
                published_at, available_at, retrieved_at, extractor_version,
                schema_version, record
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s
            ) ON CONFLICT (disclosure_id) DO NOTHING
            RETURNING record
            """,
            (
                disclosure.disclosure_id,
                disclosure.issuer_cik,
                disclosure.issuer_name,
                disclosure.category.value,
                disclosure.context.value,
                disclosure.event_fingerprint,
                disclosure.fact_fingerprint,
                disclosure.source.source_class.value,
                disclosure.source.accession_number,
                str(disclosure.source.canonical_url),
                disclosure.source.source_content_sha256,
                disclosure.source.published_at,
                disclosure.source.available_at,
                disclosure.source.retrieved_at,
                disclosure.extractor_version,
                disclosure.schema_version,
                Jsonb(disclosure.model_dump(mode="json")),
            ),
        ).fetchone()
        if inserted is None:
            existing = connection.execute(  # type: ignore[attr-defined]
                "SELECT record FROM research_event_disclosures WHERE disclosure_id = %s",
                (disclosure.disclosure_id,),
            ).fetchone()
            if existing is None or EventDisclosure.model_validate(existing["record"]) != disclosure:
                raise EventNoveltyReplayConflict(
                    "event disclosure identity already has different immutable content"
                )

    @staticmethod
    def _insert_filing_change_snapshot(connection: object, snapshot: FilingChangeSnapshot) -> None:
        inserted = connection.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO research_filing_change_snapshots (
                manifest_sha256, accession_number, canonical_cik, filing_form,
                filed_at, available_at, retrieved_at, source_url,
                source_content_sha256, normalized_visible_sha256,
                section_count, extraction_version, schema_version, record
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            ) ON CONFLICT (manifest_sha256) DO NOTHING
            RETURNING record
            """,
            (
                snapshot.manifest_sha256,
                snapshot.accession_number,
                snapshot.cik.zfill(10),
                snapshot.filing_form.value,
                snapshot.filed_at,
                snapshot.available_at,
                snapshot.retrieved_at,
                snapshot.source_url,
                snapshot.source_content_sha256,
                snapshot.normalized_visible_sha256,
                len(snapshot.sections),
                snapshot.extraction_version,
                snapshot.schema_version,
                Jsonb(snapshot.model_dump(mode="json")),
            ),
        ).fetchone()
        if inserted is None:
            existing = connection.execute(  # type: ignore[attr-defined]
                "SELECT record FROM research_filing_change_snapshots WHERE manifest_sha256 = %s",
                (snapshot.manifest_sha256,),
            ).fetchone()
            if (
                existing is None
                or FilingChangeSnapshot.model_validate(existing["record"]) != snapshot
            ):
                raise FilingChangeReplayConflict(
                    "filing-change snapshot identity has different immutable content"
                )

    @staticmethod
    def _insert_validated_sec_links(connection: object, receipt: ValidatedSecFilingLinks) -> None:
        inserted = connection.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO research_sec_link_receipts (
                receipt_id, canonical_cik, accession_number, complete_submission_url,
                archive_index_url, primary_document_url, inline_xbrl_url,
                complete_submission_sha256, archive_index_sha256,
                primary_document_sha256, inline_xbrl_validated, validated_at,
                validation_version, record
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            ) ON CONFLICT (receipt_id) DO NOTHING
            RETURNING record
            """,
            (
                receipt.receipt_id,
                receipt.canonical_cik,
                receipt.accession_number,
                receipt.complete_submission_url,
                receipt.archive_index_url,
                receipt.primary_document_url,
                receipt.inline_xbrl_url,
                receipt.complete_submission_sha256,
                receipt.archive_index_sha256,
                receipt.primary_document_sha256,
                receipt.inline_xbrl_validated,
                receipt.validated_at,
                receipt.validation_version,
                Jsonb(receipt.model_dump(mode="json")),
            ),
        ).fetchone()
        if inserted is None:
            existing = connection.execute(  # type: ignore[attr-defined]
                "SELECT record FROM research_sec_link_receipts WHERE receipt_id = %s",
                (receipt.receipt_id,),
            ).fetchone()
            if (
                existing is None
                or ValidatedSecFilingLinks.model_validate(existing["record"]) != receipt
            ):
                raise SecLinkReceiptReplayConflict(
                    "SEC link receipt identity already has different immutable content"
                )

    @staticmethod
    def _validate_brief_sec_links(
        brief: ResearchBrief | None, receipt: ValidatedSecFilingLinks
    ) -> None:
        if brief is None:
            raise ValueError("validated SEC links require a published brief")
        if (
            receipt.accession_number != brief.accession_number
            or receipt.complete_submission_url != brief.source_url
            or receipt.complete_submission_sha256 != brief.source_document_sha256
            or receipt.canonical_cik != brief.cik.zfill(10)
            or receipt.validated_at > brief.published_at
        ):
            raise ValueError("validated SEC links do not match the published brief")

    @staticmethod
    def _insert_pipeline_event(connection: object, event: PipelineEvent) -> None:
        connection.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO research_pipeline_events (
                event_id, occurred_at, stage, run_id, accession_number, count,
                failure_category, schema_version
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                event.event_id,
                event.occurred_at,
                event.stage.value,
                event.run_id,
                event.accession_number,
                event.count,
                event.failure_category,
                event.schema_version,
            ),
        )

    def discover(self, candidates: tuple[FilingCandidate, ...]) -> int:
        inserted = 0
        with self._connection() as connection:
            for candidate in candidates:
                result = connection.execute(
                    """
                    INSERT INTO research_candidates (
                        accession_number, cik, company_name, ticker, exchange, filing_form,
                        filed_at, source_url, discovered_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (accession_number) DO NOTHING
                    """,
                    (
                        candidate.accession_number,
                        candidate.cik,
                        candidate.company_name,
                        candidate.ticker,
                        candidate.exchange,
                        candidate.filing_form,
                        candidate.filed_at,
                        candidate.source_url,
                        candidate.discovered_at,
                        candidate.discovered_at,
                    ),
                )
                inserted += result.rowcount
        return inserted

    def requeue_stale_processing(
        self, *, now: datetime, lease_seconds: int = 1_800, run_id: UUID | None = None
    ) -> int:
        """Recover candidates left processing by a dead worker without touching terminals."""

        if lease_seconds < 60:
            raise ValueError("processing lease must be at least one minute")
        with self._connection() as connection:
            self._recover_stale_analyst_attempts(connection, now=now, lease_seconds=lease_seconds)
            result = connection.execute(
                """
                UPDATE research_candidates
                SET status = 'retry_wait', next_attempt_at = %s, updated_at = %s,
                    last_error_code = 'processing_lease_expired'
                WHERE status = 'processing'
                  AND updated_at < %s - (%s * interval '1 second')
                """,
                (now, now, now, lease_seconds),
            )
            if result.rowcount:
                self._insert_pipeline_event(
                    connection,
                    PipelineEvent(
                        event_id=uuid4(),
                        occurred_at=now,
                        stage=PipelineStage.STALE_RECOVERED,
                        run_id=run_id,
                        count=result.rowcount,
                    ),
                )
            return result.rowcount

    @classmethod
    def _recover_stale_analyst_attempts(
        cls,
        connection: object,
        *,
        now: datetime,
        lease_seconds: int,
    ) -> int:
        """Close interrupted calls after the same lease used for parent recovery."""

        rows = connection.execute(  # type: ignore[attr-defined]
            """
            SELECT a.record,
                   c.status AS candidate_status,
                   h.status AS human_status
            FROM research_analyst_attempts a
            LEFT JOIN research_candidates c
              ON a.origin = 'candidate'
             AND c.accession_number = a.candidate_accession_number
            LEFT JOIN research_human_leads h
              ON a.origin = 'human' AND h.lead_id = a.lead_id
            WHERE a.state = 'started'
              AND a.started_at < %s - (%s * interval '1 second')
            ORDER BY a.started_at, a.attempt_id
            FOR UPDATE OF a
            """,
            (now, lease_seconds),
        ).fetchall()
        for row in rows:
            start = AnalystAttemptStart.model_validate(row["record"])
            active_parent = (
                start.context.origin is AnalystAttemptOrigin.CANDIDATE
                and row["candidate_status"] == "processing"
            ) or (
                start.context.origin is AnalystAttemptOrigin.HUMAN
                and row["human_status"] == HumanLeadStatus.ANALYZING.value
            )
            retry_eligible = active_parent and start.context.runtime_retry_eligible
            cls._finish_analyst_attempt(
                connection,
                interrupted_analyst_attempt_receipt(
                    start,
                    recovered_at=now,
                    retry_eligible=retry_eligible,
                ),
            )
            if (
                start.context.origin is AnalystAttemptOrigin.HUMAN
                and row["human_status"] == HumanLeadStatus.ANALYZING.value
            ):
                status = HumanLeadStatus.QUEUED if retry_eligible else HumanLeadStatus.FAILED
                connection.execute(  # type: ignore[attr-defined]
                    """
                    UPDATE research_human_leads
                    SET status = %s, updated_at = %s
                    WHERE lead_id = %s AND status = 'analyzing'
                    """,
                    (status.value, now, start.context.lead_id),
                )
                lead_row = connection.execute(  # type: ignore[attr-defined]
                    "SELECT * FROM research_human_leads WHERE lead_id = %s",
                    (start.context.lead_id,),
                ).fetchone()
                if lead_row is None:
                    raise RuntimeError("stale analyst attempt has no human parent")
                lead = HumanResearchLead.model_validate(
                    {
                        key: value
                        for key, value in lead_row.items()
                        if key not in {"result", "created_at", "updated_at", "next_attempt_at"}
                    }
                )
                cls._append_human_lead_event(
                    connection,
                    lead,
                    now=now,
                    detail="interrupted analyst invocation lease expired",
                )
        return len(rows)

    def requeue_processing_on_startup(self, *, now: datetime) -> int:
        """Recover claims old enough to belong to a prior worker lifecycle.

        The same lease bound used during normal polling is retained here so a
        concurrently starting process cannot steal genuinely active work.
        """

        return self.requeue_stale_processing(now=now, lease_seconds=1_800)

    def enqueue_human_lead(self, lead: HumanResearchLead, *, now: datetime) -> HumanResearchLead:
        """Persist one bounded lead, suppressing equivalent active work."""

        with self._connection() as connection:
            duplicate = connection.execute(
                """
                SELECT lead_id FROM research_human_leads
                WHERE dedupe_key = %s
                  AND status NOT IN ('duplicate', 'rejected', 'cancelled')
                LIMIT 1
                """,
                (lead.dedupe_key,),
            ).fetchone()
            if duplicate is None:
                duplicate = connection.execute(
                    """
                    SELECT lead_id FROM research_human_leads
                    WHERE discord_message_id = %s
                    LIMIT 1
                    """,
                    (lead.discord_message_id,),
                ).fetchone()
            if duplicate is not None:
                self._insert_pipeline_event(
                    connection,
                    PipelineEvent(
                        event_id=uuid4(),
                        occurred_at=now,
                        stage=PipelineStage.HUMAN_DUPLICATE,
                    ),
                )
                duplicate_lead = lead.model_copy(update={"status": HumanLeadStatus.DUPLICATE})
                return duplicate_lead
            queued = lead.model_copy(update={"status": HumanLeadStatus.QUEUED})
            connection.execute(
                """
                INSERT INTO research_human_leads (
                    lead_id, discord_message_id, submitter_user_id, channel_id,
                    submitted_at, ticker, cik, hypothesis, urls, notes,
                    original_submission_sha256, dedupe_key, origin, status, priority,
                    attempts, result, created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    queued.lead_id,
                    queued.discord_message_id,
                    queued.submitter_user_id,
                    queued.channel_id,
                    queued.submitted_at,
                    queued.ticker,
                    queued.cik,
                    queued.hypothesis,
                    list(queued.urls),
                    queued.notes,
                    queued.original_submission_sha256,
                    queued.dedupe_key,
                    queued.origin,
                    queued.status.value,
                    queued.priority.value,
                    queued.attempts,
                    None,
                    now,
                    now,
                ),
            )
            self._append_human_lead_event(connection, queued, now=now, detail="lead queued")
            return queued

    def claim_human_lead(self, *, now: datetime) -> HumanResearchLead | None:
        """Claim the highest-priority queued lead exactly once."""

        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM research_human_leads
                WHERE status = 'queued'
                ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                         submitted_at, lead_id
                FOR UPDATE SKIP LOCKED LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            updated = dict(row)
            updated["status"] = HumanLeadStatus.ANALYZING.value
            updated["attempts"] = row["attempts"] + 1
            updated["updated_at"] = now
            connection.execute(
                """
                UPDATE research_human_leads
                SET status = 'analyzing', attempts = attempts + 1, updated_at = %s
                WHERE lead_id = %s
                """,
                (now, row["lead_id"]),
            )
            claimed = HumanResearchLead.model_validate(
                {
                    key: value
                    for key, value in updated.items()
                    if key not in {"result", "created_at", "updated_at", "next_attempt_at"}
                }
            )
            self._append_human_lead_event(
                connection,
                claimed,
                now=now,
                detail="lead claimed for bounded analysis",
            )
            return claimed

    def transition_human_lead(
        self,
        lead_id: UUID,
        status: HumanLeadStatus,
        *,
        now: datetime,
        detail: str,
    ) -> None:
        """Append a status event and update only the mutable queue head."""

        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM research_human_leads WHERE lead_id = %s FOR UPDATE",
                (lead_id,),
            ).fetchone()
            if row is None:
                raise KeyError("unknown human lead")
            updated = HumanResearchLead.model_validate(
                {
                    key: value
                    for key, value in row.items()
                    if key not in {"result", "created_at", "updated_at", "next_attempt_at"}
                }
                | {"status": status.value}
            )
            connection.execute(
                "UPDATE research_human_leads SET status = %s, updated_at = %s WHERE lead_id = %s",
                (status.value, now, lead_id),
            )
            self._append_human_lead_event(connection, updated, now=now, detail=detail)

    @staticmethod
    def _append_human_lead_event(
        connection: object,
        lead: HumanResearchLead,
        *,
        now: datetime,
        detail: str,
    ) -> None:
        connection.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO research_human_lead_events
                (event_id, lead_id, occurred_at, status, detail, record)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                uuid4(),
                lead.lead_id,
                now,
                lead.status.value,
                detail,
                Jsonb(lead.model_dump(mode="json")),
            ),
        )

    def record_human_feedback(self, feedback: HumanResearchFeedback) -> bool:
        """Append feedback once; duplicate observations are harmless no-ops."""
        with self._connection() as connection:
            row = connection.execute(
                """
                INSERT INTO research_human_feedback
                    (feedback_id, research_reference, submitter_user_id, submitted_at,
                     feedback_type, note, version)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (research_reference, submitter_user_id, feedback_type)
                DO NOTHING RETURNING feedback_id
                """,
                (
                    feedback.feedback_id,
                    feedback.research_reference,
                    feedback.submitter_user_id,
                    feedback.submitted_at,
                    feedback.feedback_type.value,
                    feedback.note,
                    feedback.version,
                ),
            ).fetchone()
            return row is not None

    def record_human_result(self, result: HumanResearchResult, *, channel_id: str) -> bool:
        """Persist one immutable private result and create one delivery head."""
        if channel_id != result.delivery_channel_id:
            raise ValueError("human result delivery channel does not match its provenance")
        with self._connection() as connection:
            row = connection.execute(
                """INSERT INTO research_human_results
                (result_id, lead_id, record, created_at, schema_version, source_status,
                 accession_number, analyst_attempt_ids, delivery_channel_id)
                VALUES (%s, %s, %s, %s, '2.0.0', %s, %s, %s, %s)
                ON CONFLICT (lead_id) DO NOTHING RETURNING result_id""",
                (
                    result.result_id,
                    result.lead_id,
                    Jsonb(result.model_dump(mode="json")),
                    result.created_at,
                    result.source.status.value,
                    result.source.accession_number,
                    [receipt.start.attempt_id for receipt in result.analyst_attempt_receipts],
                    result.delivery_channel_id,
                ),
            ).fetchone()
            if row is None:
                return False
            connection.execute(
                """INSERT INTO research_human_result_deliveries
                (result_id, channel_id, status, updated_at)
                VALUES (%s, %s, 'pending', %s)""",
                (result.result_id, channel_id, result.created_at),
            )
            return True

    def claim_human_result_delivery(
        self, *, now: datetime
    ) -> tuple[UUID, dict[str, object]] | None:
        with self._connection() as connection:
            row = connection.execute(
                """SELECT d.result_id, r.record FROM research_human_result_deliveries d
                JOIN research_human_results r ON r.result_id = d.result_id
                WHERE d.status = 'pending'
                  AND (d.next_attempt_at IS NULL OR d.next_attempt_at <= %s)
                ORDER BY d.updated_at, d.result_id FOR UPDATE OF d SKIP LOCKED LIMIT 1""",
                (now,),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """UPDATE research_human_result_deliveries
                SET attempts = attempts + 1, updated_at = %s WHERE result_id = %s""",
                (now, row["result_id"]),
            )
            return row["result_id"], row["record"]

    def complete_human_result_delivery(
        self, result_id: UUID, *, now: datetime, message_id: str
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """UPDATE research_human_result_deliveries
                SET status = 'delivered', discord_message_id = %s, updated_at = %s
                WHERE result_id = %s AND status = 'pending'""",
                (message_id, now, result_id),
            )

    def claim(self, *, now: datetime, run_id: UUID | None = None) -> ClaimedCandidate | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT c.accession_number, c.cik, c.company_name, c.ticker, c.exchange,
                       c.filing_form, c.filed_at, c.source_url, c.discovered_at, c.attempts,
                       w.reconsideration, r.record AS first_audit
                FROM research_candidates c
                LEFT JOIN research_verification_retries w
                    ON w.accession_number = c.accession_number
                LEFT JOIN research_verifier_reviews r ON r.review_id = w.review_id
                LEFT JOIN LATERAL (
                    SELECT e.action
                    FROM research_focus_membership_events e
                    WHERE e.canonical_cik = lpad(c.cik, 10, '0')
                      AND e.effective_at <= %s AND e.recorded_at <= %s
                    ORDER BY e.recorded_at DESC, e.event_id DESC
                    LIMIT 1
                ) f ON true
                WHERE (
                    c.status IN ('pending', 'retry_wait')
                    AND (c.next_attempt_at IS NULL OR c.next_attempt_at <= %s)
                ) OR (
                    c.status = 'processing'
                    AND c.updated_at <= %s - interval '30 minutes'
                )
                ORDER BY
                    CASE
                        WHEN c.discovered_at <= %s - interval '24 hours' THEN 0
                        WHEN f.action = 'added' AND c.tier_outcome = 'escalate' THEN 1
                        WHEN c.tier_outcome = 'escalate' THEN 2
                        WHEN f.action = 'added' THEN 3
                        ELSE 4
                    END,
                    c.discovered_at,
                    c.accession_number
                FOR UPDATE OF c SKIP LOCKED
                LIMIT 1
                """,
                (now, now, now, now, now),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """
                UPDATE research_candidates
                SET status = 'processing', attempts = attempts + 1,
                    next_attempt_at = NULL, last_error_code = NULL, updated_at = %s
                WHERE accession_number = %s
                """,
                (now, row["accession_number"]),
            )
            self._insert_pipeline_event(
                connection,
                PipelineEvent(
                    event_id=uuid4(),
                    occurred_at=now,
                    stage=PipelineStage.CANDIDATE_PROCESSING,
                    run_id=run_id,
                    accession_number=row["accession_number"],
                ),
            )
        reconsideration_record = row["reconsideration"]
        first_audit_record = row["first_audit"]
        if (reconsideration_record is None) != (first_audit_record is None):
            raise RuntimeError("persisted verifier retry state is incomplete")
        candidate_record = {
            key: value
            for key, value in row.items()
            if key not in {"attempts", "reconsideration", "first_audit"}
        }
        return ClaimedCandidate(
            candidate=FilingCandidate.model_validate(candidate_record),
            attempts=row["attempts"] + 1,
            reconsideration=(
                AnalystReconsideration.model_validate(reconsideration_record)
                if reconsideration_record is not None
                else None
            ),
            first_audit=(
                VerifierAudit.model_validate(first_audit_record)
                if first_audit_record is not None
                else None
            ),
        )

    def reserve_analyst_retry(
        self,
        accession_number: str,
        *,
        audit: VerifierAudit,
        reconsideration: AnalystReconsideration,
        now: datetime,
    ) -> None:
        """Persist the one semantic retry before asking Qwen to reconsider."""

        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO research_verifier_reviews (
                    review_id, candidate_id, accession_number, review_number,
                    completed_at, verdict, model_name, model_digest, prompt_version,
                    schema_version, challenge_categories, evidence_ids, record
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    audit.review_id,
                    audit.candidate_id,
                    accession_number,
                    audit.review_number,
                    audit.completed_at,
                    audit.report.verdict.value,
                    audit.model_name,
                    audit.model_digest,
                    audit.prompt_version,
                    audit.schema_version,
                    [item.value for item in audit.report.challenge_categories],
                    list(audit.evidence_ids),
                    Jsonb(audit.model_dump(mode="json")),
                ),
            )
            connection.execute(
                """
                INSERT INTO research_verification_retries (
                    retry_id, candidate_id, accession_number, reserved_at,
                    review_id, reconsideration
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    uuid4(),
                    audit.candidate_id,
                    accession_number,
                    now,
                    audit.review_id,
                    Jsonb(reconsideration.model_dump(mode="json")),
                ),
            )
            connection.execute(
                """
                UPDATE research_operation_counters
                SET analyst_retries = analyst_retries + 1, updated_at = %s
                WHERE worker_name = 'filing-radar'
                """,
                (now,),
            )

    def record_verification_outcome(
        self,
        outcome: VerificationOutcome,
        *,
        brief: ResearchBrief | None,
        decision: AutonomousScreeningDecision,
        sec_links: ValidatedSecFilingLinks | None = None,
    ) -> None:
        """Atomically append review lineage and either publish or quarantine."""

        approved = outcome.disposition is VerificationDisposition.APPROVED
        if approved != (brief is not None):
            raise ValueError("only an approved verification outcome may carry a brief")
        if brief is not None and (brief.schema_version != "2.0.0" or brief.verification is None):
            raise ValueError("new publications require a version 2 verification receipt")
        if (brief is None) != (sec_links is None):
            raise ValueError("only a published brief may carry validated SEC links")
        if (
            decision.accession_number != outcome.accession_number
            or decision.decided_at != outcome.decided_at
        ):
            raise ValueError("verification outcome and screening decision identity must match")
        if approved != (decision.disposition is ScreeningDisposition.QUALIFIED):
            raise ValueError("verification approval must match the terminal screening disposition")
        with self._connection() as connection:
            if sec_links is not None:
                self._validate_brief_sec_links(brief, sec_links)
                self._insert_validated_sec_links(connection, sec_links)
            self._insert_screening_decision(connection, decision)
            for audit in outcome.audits:
                connection.execute(
                    """
                    INSERT INTO research_verifier_reviews (
                        review_id, candidate_id, accession_number, review_number,
                        completed_at, verdict, model_name, model_digest, prompt_version,
                        schema_version, challenge_categories, evidence_ids, record
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (review_id) DO NOTHING
                    """,
                    (
                        audit.review_id,
                        audit.candidate_id,
                        outcome.accession_number,
                        audit.review_number,
                        audit.completed_at,
                        audit.report.verdict.value,
                        audit.model_name,
                        audit.model_digest,
                        audit.prompt_version,
                        audit.schema_version,
                        [item.value for item in audit.report.challenge_categories],
                        list(audit.evidence_ids),
                        Jsonb(audit.model_dump(mode="json")),
                    ),
                )
            connection.execute(
                """
                INSERT INTO research_verification_dispositions (
                    disposition_id, candidate_id, accession_number, decided_at,
                    disposition, retry_count, analyst_model_name, analyst_model_digest,
                    verifier_model_name, verifier_model_digest, review_ids,
                    challenge_categories, evidence_ids, record
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    outcome.disposition_id,
                    outcome.candidate_id,
                    outcome.accession_number,
                    outcome.decided_at,
                    outcome.disposition.value,
                    outcome.retry_count,
                    outcome.analyst_model_name,
                    outcome.analyst_model_digest,
                    outcome.verifier_model_name,
                    outcome.verifier_model_digest,
                    [item.review_id for item in outcome.audits],
                    [item.value for item in outcome.final_challenge_categories],
                    list(outcome.final_evidence_ids),
                    Jsonb(outcome.model_dump(mode="json")),
                ),
            )
            if brief is not None:
                assert sec_links is not None
                connection.execute(
                    """
                    INSERT INTO research_briefs (
                        brief_id, schema_version, accession_number, ticker, company_name,
                        classification, attention_points, risk_points,
                        evidence_strength_points, filed_at, retrieved_at, published_at,
                        source_document_sha256, verification_disposition_id,
                        autonomous_decision_id, sec_link_receipt_id, record
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        brief.brief_id,
                        brief.schema_version,
                        brief.accession_number,
                        brief.ticker,
                        brief.company_name,
                        brief.classification.value,
                        brief.attention_points,
                        brief.risk_points,
                        brief.evidence_strength_points,
                        brief.filed_at,
                        brief.retrieved_at,
                        brief.published_at,
                        brief.source_document_sha256,
                        outcome.disposition_id,
                        decision.decision_id,
                        sec_links.receipt_id,
                        Jsonb(brief.model_dump(mode="json")),
                    ),
                )
                status = "published"
                error_code = None
                connection.execute(
                    """
                    UPDATE research_operation_counters
                    SET final_publications = final_publications + 1, updated_at = %s
                    WHERE worker_name = 'filing-radar'
                    """,
                    (outcome.decided_at,),
                )
            else:
                status = (
                    "quarantined"
                    if decision.disposition is ScreeningDisposition.SCREENED_OUT
                    else "failed"
                )
                error_code = outcome.disposition.value
            connection.execute(
                """
                UPDATE research_candidates
                SET status = %s, updated_at = %s, last_error_code = %s,
                    next_attempt_at = NULL
                WHERE accession_number = %s
                """,
                (status, outcome.decided_at, error_code, outcome.accession_number),
            )

    def record_deterministic_publication(
        self,
        brief: ResearchBrief,
        decision: AutonomousScreeningDecision,
        sec_links: ValidatedSecFilingLinks,
    ) -> None:
        """Atomically publish after the accepted Qwen-plus-deterministic gate."""

        if decision.disposition is not ScreeningDisposition.QUALIFIED:
            raise ValueError("a deterministic publication requires a qualified decision")
        if decision.accession_number != brief.accession_number:
            raise ValueError("publication and screening decision accession must match")
        if (
            brief.schema_version != "3.0.0"
            or brief.publication_gate is None
            or brief.publication_gate.mode is not PublicationGateMode.DETERMINISTIC_ONLY
            or brief.verification is not None
        ):
            raise ValueError("deterministic publication requires version 3 closed lineage")
        self._validate_brief_sec_links(brief, sec_links)
        with self._connection() as connection:
            self._insert_validated_sec_links(connection, sec_links)
            self._insert_screening_decision(connection, decision)
            connection.execute(
                """
                INSERT INTO research_briefs (
                    brief_id, schema_version, accession_number, ticker, company_name,
                    classification, attention_points, risk_points,
                    evidence_strength_points, filed_at, retrieved_at, published_at,
                    source_document_sha256, verification_disposition_id,
                    autonomous_decision_id, sec_link_receipt_id, record
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, %s, %s, %s
                )
                """,
                (
                    brief.brief_id,
                    brief.schema_version,
                    brief.accession_number,
                    brief.ticker,
                    brief.company_name,
                    brief.classification.value,
                    brief.attention_points,
                    brief.risk_points,
                    brief.evidence_strength_points,
                    brief.filed_at,
                    brief.retrieved_at,
                    brief.published_at,
                    brief.source_document_sha256,
                    decision.decision_id,
                    sec_links.receipt_id,
                    Jsonb(brief.model_dump(mode="json")),
                ),
            )
            connection.execute(
                """
                UPDATE research_candidates
                SET status = 'published', updated_at = %s, last_error_code = NULL,
                    next_attempt_at = NULL
                WHERE accession_number = %s
                """,
                (decision.decided_at, decision.accession_number),
            )
            connection.execute(
                """
                UPDATE research_operation_counters
                SET final_publications = final_publications + 1, updated_at = %s
                WHERE worker_name = 'filing-radar'
                """,
                (decision.decided_at,),
            )

    def increment_counter(self, name: str, *, now: datetime) -> None:
        if name not in OPERATION_COUNTERS:
            raise ValueError("unknown research operation counter")
        with self._connection() as connection:
            connection.execute(
                f"""
                UPDATE research_operation_counters
                SET {name} = {name} + 1, updated_at = %s
                WHERE worker_name = 'filing-radar'
                """,
                (now,),
            )

    def verifier_counts(self) -> tuple[int, int, int]:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT verifier_reviews, verifier_approvals, verifier_challenges
                FROM research_operation_counters
                WHERE worker_name = 'filing-radar'
                """
            ).fetchone()
        if row is None:
            raise RuntimeError("research operation counter row is absent")
        return row["verifier_reviews"], row["verifier_approvals"], row["verifier_challenges"]

    def complete_candidate(
        self,
        accession_number: str,
        *,
        status: str,
        now: datetime,
        error_code: str | None = None,
        next_attempt_at: datetime | None = None,
        failure_category: PipelineFailureCategory | None = None,
        run_id: UUID | None = None,
        decision: AutonomousScreeningDecision | None = None,
    ) -> None:
        if status not in {"skipped", "retry_wait", "failed"}:
            raise ValueError("unsupported candidate completion status")
        if (status in {"retry_wait", "failed"}) != (failure_category is not None):
            raise ValueError("retry and failure completion require a bounded failure category")
        if (status == "retry_wait") != (decision is None):
            raise ValueError("only terminal candidate completion requires a screening decision")
        if decision is not None:
            if decision.accession_number != accession_number or decision.decided_at != now:
                raise ValueError("candidate completion and screening decision identity must match")
            expected = (
                ScreeningDisposition.SCREENED_OUT
                if status == "skipped"
                else ScreeningDisposition.ANALYSIS_INCOMPLETE
            )
            if decision.disposition is not expected:
                raise ValueError("candidate status does not match screening disposition")
        with self._connection() as connection:
            if decision is not None:
                self._insert_screening_decision(connection, decision)
            connection.execute(
                """
                UPDATE research_candidates
                SET status = %s, updated_at = %s, last_error_code = %s, next_attempt_at = %s
                WHERE accession_number = %s
                """,
                (status, now, error_code, next_attempt_at, accession_number),
            )
            stage = {
                "skipped": PipelineStage.CANDIDATE_SKIPPED,
                "retry_wait": PipelineStage.CANDIDATE_RETRY_WAIT,
                "failed": PipelineStage.CANDIDATE_FAILED,
            }[status]
            self._insert_pipeline_event(
                connection,
                PipelineEvent(
                    event_id=uuid4(),
                    occurred_at=now,
                    stage=stage,
                    run_id=run_id,
                    accession_number=accession_number,
                    failure_category=failure_category,
                ),
            )

    @staticmethod
    def _insert_screening_decision(
        connection: object,
        decision: AutonomousScreeningDecision,
    ) -> None:
        connection.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO research_autonomous_screening_decisions (
                decision_id, accession_number, decided_at, disposition, reason,
                work_attempt, run_id, analyst_attempt_ids, source_document_sha256,
                schema_version, record
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                decision.decision_id,
                decision.accession_number,
                decision.decided_at,
                decision.disposition.value,
                decision.reason.value,
                decision.work_attempt,
                decision.run_id,
                list(decision.analyst_attempt_ids),
                decision.source_document_sha256,
                decision.schema_version,
                Jsonb(decision.model_dump(mode="json")),
            ),
        )

    def record_tier_decision(
        self,
        accession_number: str,
        decision: TierDecision,
        *,
        now: datetime,
        run_id: UUID | None = None,
    ) -> None:
        """Persist the deterministic Tier-0 decision before any model work."""

        record = decision.model_dump(mode="json")
        signal_by_name = {
            {
                "share_count_growth": "share_growth",
                "liquidity_pressure": "liquidity",
            }.get(signal.signal_id, signal.signal_id): signal
            for signal in decision.forensic_signals
        }
        detector_names: tuple[DetectorName, ...] = (
            "share_growth",
            "liquidity",
            "going_concern",
            "reverse_split",
            "filing_diff",
            "xbrl_numeric",
            "source_authority",
            "convergence",
        )
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE research_candidates
                SET tier_outcome = %s, tier_reason = %s, tier_evidence_ids = %s,
                    tier_decision_record = %s, updated_at = %s
                WHERE accession_number = %s
                """,
                (
                    decision.outcome.value,
                    decision.reason.value,
                    list(decision.evidence_ids),
                    Jsonb(record),
                    now,
                    accession_number,
                ),
            )
            if decision.outcome in {TierOutcome.RETAIN, TierOutcome.ESCALATE}:
                self._insert_pipeline_event(
                    connection,
                    PipelineEvent(
                        event_id=uuid4(),
                        occurred_at=now,
                        stage=(
                            PipelineStage.TIER_RETAINED
                            if decision.outcome is TierOutcome.RETAIN
                            else PipelineStage.TIER_ESCALATED
                        ),
                        run_id=run_id,
                        accession_number=accession_number,
                    ),
                )
            for detector_name in detector_names:
                signal = signal_by_name.get(detector_name)
                receipt = DetectorReceipt(
                    receipt_id=uuid4(),
                    accession_number=accession_number,
                    observed_at=now,
                    detector_name=detector_name,
                    invoked=signal is not None,
                    status=(signal.status if signal is not None else ForensicStatus.NOT_ASSESSED),
                    # Existing forensic observations are preserved in the decision,
                    # but choose_tier does not currently use them as an escalation input.
                    contributed_to_escalation=False,
                )
                connection.execute(
                    """
                    INSERT INTO research_detector_receipts (
                        receipt_id, accession_number, observed_at, detector_name,
                        invoked, status, contributed_to_escalation, schema_version
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (accession_number, detector_name) DO NOTHING
                    """,
                    (
                        receipt.receipt_id,
                        receipt.accession_number,
                        receipt.observed_at,
                        receipt.detector_name,
                        receipt.invoked,
                        receipt.status.value,
                        receipt.contributed_to_escalation,
                        receipt.schema_version,
                    ),
                )

    def counts(self) -> tuple[int, int, int]:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT count(*) AS discovered_count,
                       count(*) FILTER (
                           WHERE status IN ('pending', 'retry_wait', 'processing')
                       ) AS pending_count,
                       count(*) FILTER (WHERE status = 'published') AS published_count
                FROM research_candidates
                """
            ).fetchone()
        if row is None:
            raise RuntimeError("radar count query returned no row")
        return row["discovered_count"], row["pending_count"], row["published_count"]

    def save_snapshot(self, snapshot: WorkerSnapshot) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO research_worker_status (
                    worker_name, state, heartbeat_at, last_success_at, next_run_at,
                    last_error_code, discovered_count, pending_count, published_count,
                    discord_enabled, model_name, source_name,
                    verifier_enabled, verifier_model_name
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (worker_name) DO UPDATE SET
                    state = EXCLUDED.state,
                    heartbeat_at = EXCLUDED.heartbeat_at,
                    last_success_at = COALESCE(
                        EXCLUDED.last_success_at,
                        research_worker_status.last_success_at
                    ),
                    next_run_at = EXCLUDED.next_run_at,
                    last_error_code = EXCLUDED.last_error_code,
                    discovered_count = EXCLUDED.discovered_count,
                    pending_count = EXCLUDED.pending_count,
                    published_count = EXCLUDED.published_count,
                    discord_enabled = EXCLUDED.discord_enabled,
                    model_name = EXCLUDED.model_name,
                    source_name = EXCLUDED.source_name,
                    verifier_enabled = EXCLUDED.verifier_enabled,
                    verifier_model_name = EXCLUDED.verifier_model_name
                """,
                (
                    snapshot.worker_name,
                    snapshot.state.value,
                    snapshot.heartbeat_at,
                    snapshot.last_success_at,
                    snapshot.next_run_at,
                    snapshot.last_error_code,
                    snapshot.discovered_count,
                    snapshot.pending_count,
                    snapshot.published_count,
                    snapshot.discord_enabled,
                    snapshot.model_name,
                    snapshot.source_name,
                    snapshot.verifier_enabled,
                    snapshot.verifier_model_name,
                ),
            )

    def append_run(self, run: RadarRun) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO research_runs (run_id, started_at, completed_at, state, record)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    run.run_id,
                    run.started_at,
                    run.completed_at,
                    run.state.value,
                    Jsonb(run.model_dump(mode="json")),
                ),
            )

    def notification_is_terminal(self, notification_key: str) -> bool:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM research_notification_deliveries
                    WHERE notification_key = %s AND status IN ('sent', 'delivery_uncertain')
                ) AS present
                """,
                (notification_key,),
            ).fetchone()
        return bool(row and row["present"])

    def briefs_pending_notification(
        self, *, limit: int = 20
    ) -> tuple[tuple[ResearchBrief, ValidatedSecFilingLinks | None], ...]:
        if not 1 <= limit <= 100:
            raise ValueError("notification batch limit must be between one and 100")
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT b.record, l.record AS sec_link_record
                FROM research_briefs b
                LEFT JOIN research_sec_link_receipts l
                    ON l.receipt_id = b.sec_link_receipt_id
                WHERE NOT EXISTS (
                    SELECT 1 FROM research_notification_deliveries d
                    WHERE d.brief_id = b.brief_id
                      AND d.status IN ('sent', 'delivery_uncertain')
                )
                ORDER BY b.published_at, b.brief_id
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
        return tuple(
            (
                ResearchBrief.model_validate(row["record"]),
                (
                    ValidatedSecFilingLinks.model_validate(row["sec_link_record"])
                    if row["sec_link_record"] is not None
                    else None
                ),
            )
            for row in rows
        )

    def append_delivery(self, brief_id: UUID, delivery: NotificationDelivery) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO research_notification_deliveries (
                    delivery_id, notification_key, brief_id, completed_at, status, record
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    uuid4(),
                    delivery.notification_key,
                    brief_id,
                    delivery.completed_at,
                    delivery.status.value,
                    Jsonb(delivery.model_dump(mode="json")),
                ),
            )

    @staticmethod
    def _insert_engineering_measurement(
        connection: object,
        receipt: EngineeringMeasurementReceipt,
    ) -> None:
        inserted = connection.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO research_engineering_measurements (
                receipt_id, metric_name, metric_version, definition_sha256,
                window_started_at, window_ended_at, measured_at, availability,
                unavailable_reason, coverage_started_at, sample_count, numerator,
                denominator, scaled_value_millionths, minimum_value, p50_value,
                p90_value, p95_value, maximum_value, gauge_value, record
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            ) ON CONFLICT (receipt_id) DO NOTHING
            RETURNING record
            """,
            (
                receipt.receipt_id,
                receipt.metric_name.value,
                receipt.measurement_version,
                receipt.definition_sha256,
                receipt.window_started_at,
                receipt.window_ended_at,
                receipt.measured_at,
                receipt.availability.value,
                (
                    receipt.unavailable_reason.value
                    if receipt.unavailable_reason is not None
                    else None
                ),
                receipt.coverage_started_at,
                receipt.sample_count,
                receipt.numerator,
                receipt.denominator,
                receipt.scaled_value_millionths,
                receipt.minimum_value,
                receipt.p50_value,
                receipt.p90_value,
                receipt.p95_value,
                receipt.maximum_value,
                receipt.gauge_value,
                Jsonb(receipt.model_dump(mode="json")),
            ),
        ).fetchone()
        if inserted is not None:
            return
        existing = connection.execute(  # type: ignore[attr-defined]
            "SELECT record FROM research_engineering_measurements WHERE receipt_id = %s",
            (receipt.receipt_id,),
        ).fetchone()
        if (
            existing is None
            or EngineeringMeasurementReceipt.model_validate(existing["record"]) != receipt
        ):
            raise EngineeringMeasurementReplayConflict(
                "engineering measurement identity already has different immutable content"
            )

    @staticmethod
    def _insert_filing_latency_receipt(
        connection: object,
        receipt: FilingLatencyReceipt,
    ) -> None:
        inserted = connection.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO research_filing_latency_receipts (
                receipt_id, accession_number, event_lineage_id,
                authoritative_first_known_at, discovered_at, published_at, alerted_at,
                first_known_to_discovery_ms, first_known_to_discovery_reason,
                discovery_to_publication_ms, discovery_to_publication_reason,
                first_known_to_alert_ms, first_known_to_alert_reason, measured_at,
                measurement_version, record
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s
            ) ON CONFLICT (
                accession_number, event_lineage_id, published_at, alerted_at,
                measurement_version
            ) DO NOTHING
            RETURNING record
            """,
            (
                receipt.receipt_id,
                receipt.accession_number,
                receipt.event_lineage_id,
                receipt.authoritative_first_known_at,
                receipt.discovered_at,
                receipt.published_at,
                receipt.alerted_at,
                receipt.first_known_to_discovery.value_ms,
                (
                    receipt.first_known_to_discovery.unavailable_reason.value
                    if receipt.first_known_to_discovery.unavailable_reason is not None
                    else None
                ),
                receipt.discovery_to_publication.value_ms,
                (
                    receipt.discovery_to_publication.unavailable_reason.value
                    if receipt.discovery_to_publication.unavailable_reason is not None
                    else None
                ),
                receipt.first_known_to_alert.value_ms,
                (
                    receipt.first_known_to_alert.unavailable_reason.value
                    if receipt.first_known_to_alert.unavailable_reason is not None
                    else None
                ),
                receipt.measured_at,
                receipt.measurement_version,
                Jsonb(receipt.model_dump(mode="json")),
            ),
        ).fetchone()
        if inserted is not None:
            return
        existing = connection.execute(  # type: ignore[attr-defined]
            """
            SELECT record FROM research_filing_latency_receipts
            WHERE accession_number = %s
              AND event_lineage_id IS NOT DISTINCT FROM %s
              AND published_at IS NOT DISTINCT FROM %s
              AND alerted_at IS NOT DISTINCT FROM %s
              AND measurement_version = %s
            """,
            (
                receipt.accession_number,
                receipt.event_lineage_id,
                receipt.published_at,
                receipt.alerted_at,
                receipt.measurement_version,
            ),
        ).fetchone()
        if existing is None or FilingLatencyReceipt.model_validate(existing["record"]) != receipt:
            raise EngineeringMeasurementReplayConflict(
                "filing latency identity already has different immutable content"
            )
