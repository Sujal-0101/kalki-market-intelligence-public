"""Opt-in PostgreSQL gate for durable web state and publication reads."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from psycopg.errors import InsufficientPrivilege
from psycopg.types.json import Jsonb
from test_live_radar import verified_brief
from test_prediction_outcomes import prediction

from kalki_market_intelligence.database import DatabaseOptions, DatabaseRuntime
from kalki_market_intelligence.web.contracts import AuditEventType
from kalki_market_intelligence.web.repository import PostgresResearchRepository
from kalki_market_intelligence.web.security import (
    PostgresLoginRateLimiter,
    PostgresSecurityAuditLog,
    PostgresSessionStore,
)

OWNER_PASSWORD_FILE = os.environ.get("KALKI_POSTGRES_OWNER_GATE_PASSWORD_FILE")
APP_PASSWORD_FILE = os.environ.get("KALKI_POSTGRES_APP_GATE_PASSWORD_FILE")

pytestmark = pytest.mark.skipif(
    OWNER_PASSWORD_FILE is None or APP_PASSWORD_FILE is None,
    reason="Phase 12 PostgreSQL gate is not running",
)


def test_postgres_publication_sessions_audit_and_limits_are_durable() -> None:
    assert OWNER_PASSWORD_FILE is not None
    assert APP_PASSWORD_FILE is not None
    record = prediction()
    owner_password = Path(OWNER_PASSWORD_FILE).read_text(encoding="utf-8").strip()
    with psycopg.connect(
        host="127.0.0.1",
        port=55_439,
        dbname="kalki",
        user="kalki_owner",
        password=owner_password,
    ) as owner:
        owner.execute(
            """
            INSERT INTO predictions (
                prediction_id, schema_version, research_subject_id, instrument_id,
                benchmark_instrument_id, as_of_date, knowledge_cutoff_at, published_at,
                horizon_days, evaluation_due_on, signal_fingerprint, record
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (prediction_id) DO NOTHING
            """,
            (
                record.prediction_id,
                record.schema_version,
                record.research_subject_id,
                record.instrument_id,
                record.benchmark_instrument_id,
                record.as_of_date,
                record.knowledge_cutoff_at,
                record.published_at,
                record.horizon_days,
                record.evaluation_due_on,
                record.versions.signal_fingerprint,
                record.model_dump_json(),
            ),
        )

    runtime = DatabaseRuntime(
        DatabaseOptions(
            host="127.0.0.1",
            port=55_439,
            name="kalki",
            user="kalki_app",
            password_file=Path(APP_PASSWORD_FILE),
            minimum_pool_size=1,
            maximum_pool_size=2,
        )
    )
    runtime.open()
    try:
        repository = PostgresResearchRepository(runtime.connection)
        assert repository.list_predictions() == (record,)
        assert repository.get_prediction(record.prediction_id) == record

        with pytest.raises(InsufficientPrivilege):
            with runtime.connection() as connection:
                connection.execute(
                    "UPDATE predictions SET published_at = now() WHERE prediction_id = %s",
                    (record.prediction_id,),
                )

        tokens = iter(("s" * 43, "c" * 43))
        sessions_a = PostgresSessionStore(
            runtime.connection,
            token_factory=lambda: next(tokens),
        )
        token, issued = sessions_a.issue("admin", "a" * 64)
        sessions_b = PostgresSessionStore(runtime.connection)
        authenticated = sessions_b.authenticate(token, "a" * 64)
        assert authenticated is not None
        assert authenticated.csrf_token == issued.csrf_token
        sessions_b.revoke(token)
        assert sessions_a.authenticate(token, "a" * 64) is None

        audit_a = PostgresSecurityAuditLog(runtime.connection)
        event = audit_a.append(
            AuditEventType.LOGIN_SUCCEEDED,
            actor="admin",
            client_sha256="a" * 64,
            detail="admin session issued",
        )
        assert event in PostgresSecurityAuditLog(runtime.connection).events
        with pytest.raises(InsufficientPrivilege):
            with runtime.connection() as connection:
                connection.execute(
                    "DELETE FROM web_security_audit_events WHERE event_id = %s",
                    (event.event_id,),
                )

        def now() -> datetime:
            return datetime(2026, 8, 24, 12, tzinfo=UTC)

        rate_fingerprint = "b" * 64
        with runtime.connection() as connection:
            connection.execute(
                "DELETE FROM web_login_attempts WHERE client_sha256 = %s",
                (rate_fingerprint,),
            )
        limiter_a = PostgresLoginRateLimiter(
            runtime.connection,
            maximum_attempts=3,
            window_seconds=60,
            now=now,
        )
        assert limiter_a.allow_attempt(rate_fingerprint) == (True, 0)
        assert PostgresLoginRateLimiter(
            runtime.connection,
            maximum_attempts=3,
            window_seconds=60,
            now=now,
        ).allow_attempt(rate_fingerprint) == (True, 0)
    finally:
        runtime.close()


def test_publication_index_combines_public_tables_and_excludes_private_human_results() -> None:
    assert OWNER_PASSWORD_FILE is not None
    assert APP_PASSWORD_FILE is not None
    forecast = prediction()
    dossier = verified_brief()
    verification = dossier.verification
    assert verification is not None
    candidate_id = "41000000-0000-4000-8000-000000000001"
    analyst_attempt_id = "40500000-0000-4000-8000-000000000001"
    analyst_invocation_id = "40600000-0000-4000-8000-000000000001"
    review_id = "42000000-0000-4000-8000-000000000001"
    disposition_id = "43000000-0000-4000-8000-000000000001"
    decision_id = "43500000-0000-4000-8000-000000000001"
    run_id = "43600000-0000-4000-8000-000000000001"
    lead_id = "44000000-0000-4000-8000-000000000001"
    result_id = "45000000-0000-4000-8000-000000000001"
    owner_password = Path(OWNER_PASSWORD_FILE).read_text(encoding="utf-8").strip()
    with psycopg.connect(
        host="127.0.0.1",
        port=55_439,
        dbname="kalki",
        user="kalki_owner",
        password=owner_password,
    ) as owner:
        owner.execute(
            """
            INSERT INTO predictions (
                prediction_id, schema_version, research_subject_id, instrument_id,
                benchmark_instrument_id, as_of_date, knowledge_cutoff_at, published_at,
                horizon_days, evaluation_due_on, signal_fingerprint, record
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (prediction_id) DO NOTHING
            """,
            (
                forecast.prediction_id,
                forecast.schema_version,
                forecast.research_subject_id,
                forecast.instrument_id,
                forecast.benchmark_instrument_id,
                forecast.as_of_date,
                forecast.knowledge_cutoff_at,
                forecast.published_at,
                forecast.horizon_days,
                forecast.evaluation_due_on,
                forecast.versions.signal_fingerprint,
                forecast.model_dump_json(),
            ),
        )
        owner.execute(
            """
            INSERT INTO research_candidates (
                accession_number, cik, company_name, ticker, exchange, filing_form,
                filed_at, source_url, discovered_at, status, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'published', %s)
            ON CONFLICT (accession_number) DO NOTHING
            """,
            (
                dossier.accession_number,
                dossier.cik,
                dossier.company_name,
                dossier.ticker,
                dossier.exchange,
                dossier.filing_form,
                dossier.filed_at,
                dossier.source_url,
                dossier.retrieved_at,
                dossier.published_at,
            ),
        )
        owner.execute(
            """
            INSERT INTO research_analyst_attempts (
                attempt_id, invocation_id, origin, candidate_accession_number,
                ticker, cik, accession_number, filing_form, work_attempt,
                semantic_retry, provider_name, model_name, model_digest,
                prompt_version, output_schema_version, validation_version, role,
                attempt_number, started_at, input_evidence_count,
                input_evidence_characters, system_prompt_characters,
                user_prompt_characters, context_tokens, maximum_output_tokens,
                state, record
            ) VALUES (
                %s, %s, 'candidate', %s, %s, %s, %s, %s, 1, false,
                'ollama-loopback', %s, %s, 'analyst-v2', '1.0.0', '1.0.0',
                'catalyst_analyst', 1, %s, 1, 500, 1000, 2000, 4096, 768,
                'started', '{}'
            ) ON CONFLICT (attempt_id) DO NOTHING
            """,
            (
                analyst_attempt_id,
                analyst_invocation_id,
                dossier.accession_number,
                dossier.ticker,
                dossier.cik,
                dossier.accession_number,
                dossier.filing_form,
                dossier.model_name,
                dossier.model_digest,
                dossier.retrieved_at,
            ),
        )
        owner.execute(
            """
            UPDATE research_analyst_attempts
            SET state = 'completed', completed_at = started_at + interval '1 second',
                latency_ms = 1000, response_sha256 = repeat('f', 64),
                response_characters = 80, response_bytes = 80,
                parse_status = 'passed', schema_status = 'passed',
                evidence_status = 'passed', failure_layer = 'none',
                retry_eligible = false, retry_scope = 'none', outcome = 'accepted',
                terminal_disposition = 'accepted', record = '{}'
            WHERE attempt_id = %s AND state = 'started'
            """,
            (analyst_attempt_id,),
        )
        owner.execute(
            """
            INSERT INTO research_verifier_reviews (
                review_id, candidate_id, accession_number, review_number, completed_at,
                verdict, model_name, model_digest, prompt_version, schema_version,
                challenge_categories, evidence_ids, record
            ) VALUES (%s, %s, %s, 1, %s, 'approve', %s, %s, 'verifier-v1', '1.0.0',
                      '{}', %s, %s)
            ON CONFLICT (review_id) DO NOTHING
            """,
            (
                review_id,
                candidate_id,
                dossier.accession_number,
                dossier.published_at,
                verification.verifier_model_name,
                verification.verifier_model_digest,
                [dossier.evidence[0].evidence_id],
                Jsonb({"fixture": "approved"}),
            ),
        )
        owner.execute(
            """
            INSERT INTO research_verification_dispositions (
                disposition_id, candidate_id, accession_number, decided_at, disposition,
                retry_count, analyst_model_name, analyst_model_digest, verifier_model_name,
                verifier_model_digest, review_ids, challenge_categories, evidence_ids, record
            ) VALUES (%s, %s, %s, %s, 'approved', 0, %s, %s, %s, %s, %s, '{}', '{}', %s)
            ON CONFLICT (disposition_id) DO NOTHING
            """,
            (
                disposition_id,
                candidate_id,
                dossier.accession_number,
                dossier.published_at,
                dossier.model_name,
                dossier.model_digest,
                verification.verifier_model_name,
                verification.verifier_model_digest,
                [review_id],
                Jsonb({"fixture": "approved"}),
            ),
        )
        owner.execute(
            """
            INSERT INTO research_autonomous_screening_decisions (
                decision_id, accession_number, decided_at, disposition, reason,
                work_attempt, run_id, analyst_attempt_ids,
                source_document_sha256, schema_version, record
            ) VALUES (%s, %s, %s, 'QUALIFIED', 'VALIDATED_PUBLICATION', 1,
                      %s, %s, %s, '1.0.0', %s)
            ON CONFLICT (decision_id) DO NOTHING
            """,
            (
                decision_id,
                dossier.accession_number,
                dossier.published_at,
                run_id,
                [analyst_attempt_id],
                dossier.source_document_sha256,
                Jsonb(
                    {
                        "decision_id": decision_id,
                        "accession_number": dossier.accession_number,
                        "decided_at": dossier.published_at.isoformat(),
                        "disposition": "QUALIFIED",
                        "reason": "VALIDATED_PUBLICATION",
                        "work_attempt": 1,
                        "run_id": run_id,
                        "analyst_attempt_ids": [analyst_attempt_id],
                        "source_document_sha256": dossier.source_document_sha256,
                        "schema_version": "1.0.0",
                    }
                ),
            ),
        )
        owner.execute(
            """
            INSERT INTO research_briefs (
                brief_id, schema_version, accession_number, ticker, company_name,
                classification, attention_points, risk_points, evidence_strength_points,
                filed_at, retrieved_at, published_at, source_document_sha256,
                verification_disposition_id, autonomous_decision_id, record
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (brief_id) DO NOTHING
            """,
            (
                dossier.brief_id,
                dossier.schema_version,
                dossier.accession_number,
                dossier.ticker,
                dossier.company_name,
                dossier.classification.value,
                dossier.attention_points,
                dossier.risk_points,
                dossier.evidence_strength_points,
                dossier.filed_at,
                dossier.retrieved_at,
                dossier.published_at,
                dossier.source_document_sha256,
                disposition_id,
                decision_id,
                Jsonb(dossier.model_dump(mode="json")),
            ),
        )
        owner.execute(
            """
            INSERT INTO research_human_leads (
                lead_id, discord_message_id, submitter_user_id, channel_id, submitted_at,
                ticker, hypothesis, original_submission_sha256, dedupe_key, status,
                created_at, updated_at
            ) VALUES (%s, '123456789012345678', '223456789012345678',
                      '323456789012345678', %s, 'TEST', 'Private fixture', %s, %s,
                      'completed', %s, %s)
            ON CONFLICT (lead_id) DO NOTHING
            """,
            (
                lead_id,
                dossier.published_at,
                "d" * 64,
                "e" * 64,
                dossier.published_at,
                dossier.published_at,
            ),
        )
        owner.execute(
            """
            INSERT INTO research_human_results (
                result_id, lead_id, record, created_at, schema_version,
                source_status, accession_number, analyst_attempt_ids,
                delivery_channel_id
            ) VALUES (%s, %s, %s, %s, '2.0.0', 'unresolved', NULL, '{}',
                      '323456789012345678')
            ON CONFLICT (result_id) DO NOTHING
            """,
            (
                result_id,
                lead_id,
                Jsonb(
                    {
                        "version": "human-research-v2",
                        "result_id": result_id,
                        "lead_id": lead_id,
                        "source": {"status": "unresolved"},
                        "analyst_attempt_receipts": [],
                        "delivery_channel_id": "323456789012345678",
                        "private_marker": "must-never-reach-public-library",
                    }
                ),
                dossier.published_at,
            ),
        )

    runtime = DatabaseRuntime(
        DatabaseOptions(
            host="127.0.0.1",
            port=55_439,
            name="kalki",
            user="kalki_app",
            password_file=Path(APP_PASSWORD_FILE),
            minimum_pool_size=1,
            maximum_pool_size=2,
        )
    )
    runtime.open()
    try:
        publications = PostgresResearchRepository(runtime.connection).list_publications()
        assert publications == (dossier, forecast)
        assert len(publications) == 2
    finally:
        runtime.close()


def test_application_role_has_only_declared_table_privileges() -> None:
    assert OWNER_PASSWORD_FILE is not None
    assert APP_PASSWORD_FILE is not None
    password = Path(APP_PASSWORD_FILE).read_text(encoding="utf-8").strip()
    with psycopg.connect(
        host="127.0.0.1",
        port=55_439,
        dbname="kalki",
        user="kalki_app",
        password=password,
    ) as connection:
        rows = connection.execute(
            """
            SELECT table_name, privilege_type
            FROM information_schema.role_table_grants
            WHERE grantee = 'kalki_app' AND table_schema = 'public'
            ORDER BY table_name, privilege_type
            """
        ).fetchall()

    privileges: dict[str, set[str]] = {}
    for table_name, privilege in rows:
        privileges.setdefault(table_name, set()).add(privilege)
    assert privileges["predictions"] == {"SELECT"}
    assert privileges["prediction_corrections"] == {"SELECT"}
    assert privileges["prediction_outcomes"] == {"SELECT"}
    assert privileges["web_security_audit_events"] == {"INSERT", "SELECT"}
    assert privileges["web_admin_sessions"] == {"DELETE", "INSERT", "SELECT", "UPDATE"}
    assert "TRUNCATE" not in {item for values in privileges.values() for item in values}
