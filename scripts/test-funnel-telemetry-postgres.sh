#!/bin/sh
set -eu

repository_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
image=postgres:18.0-alpine3.22@sha256:48c8ad3a7284b82be4482a52076d47d879fd6fb084a1cbfccbd551f9331b0e40
container=kalki-phase34-postgres-gate-$$
password_file=$(mktemp)
cleanup() {
    docker container rm --force "$container" >/dev/null 2>&1 || true
    rm -f -- "$password_file"
}
trap cleanup EXIT HUP INT TERM
printf '%s\n' 'unused-trust-auth-value' >"$password_file"

docker run --detach --name "$container" \
    --publish 127.0.0.1:55440:5432 \
    --tmpfs /var/lib/postgresql/data:rw,noexec,nosuid,size=768m \
    --env POSTGRES_HOST_AUTH_METHOD=trust --env POSTGRES_DB=kalki \
    --env POSTGRES_USER=kalki_owner "$image" >/dev/null

attempt=0
until docker exec "$container" psql --no-psqlrc --username kalki_owner --dbname kalki \
    --command "SELECT 1" >/dev/null 2>&1
do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 45 ]; then
        echo "Disposable funnel database did not become ready." >&2
        exit 1
    fi
    sleep 1
done

docker exec "$container" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
    --username kalki_owner --dbname kalki \
    --command "CREATE ROLE kalki_app LOGIN;" >/dev/null
for migration in "$repository_dir"/migrations/000[1-9]_*.sql
do
    docker exec --interactive "$container" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
        --username kalki_owner --dbname kalki <"$migration" >/dev/null
done

docker exec --interactive "$container" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
    --username kalki_owner --dbname kalki >/dev/null <<'SQL'
INSERT INTO research_human_leads (
    lead_id, discord_message_id, submitter_user_id, channel_id, submitted_at,
    hypothesis, original_submission_sha256, dedupe_key, status, attempts,
    created_at, updated_at
) VALUES (
    '16000000-0000-4000-8000-000000000001', '123456789012345678',
    '223456789012345678', '323456789012345678', clock_timestamp() - interval '19 minutes',
    'Synthetic private hypothesis', repeat('1', 64), repeat('2', 64), 'completed', 1,
    clock_timestamp() - interval '19 minutes', clock_timestamp() - interval '18 minutes'
);
INSERT INTO research_human_results (result_id, lead_id, record, created_at)
VALUES (
    '17000000-0000-4000-8000-000000000001',
    '16000000-0000-4000-8000-000000000001', '{}',
    clock_timestamp() - interval '18 minutes'
);
INSERT INTO research_human_result_deliveries (
    result_id, channel_id, discord_message_id, status, attempts, updated_at
) VALUES (
    '17000000-0000-4000-8000-000000000001', '323456789012345678',
    '423456789012345678', 'delivered', 1, clock_timestamp() - interval '17 minutes'
);
SQL

for migration in "$repository_dir"/migrations/001[0-9]_*.sql
do
    docker exec --interactive "$container" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
        --username kalki_owner --dbname kalki <"$migration" >/dev/null
done

docker exec --interactive "$container" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
    --username kalki_owner --dbname kalki >/dev/null <<'SQL'
INSERT INTO research_candidates (
    accession_number, cik, company_name, ticker, exchange, filing_form,
    filed_at, source_url, discovered_at, status, updated_at,
    tier_outcome, tier_reason, tier_evidence_ids, tier_decision_record
) VALUES (
    '0000320193-26-000001', '320193', 'Synthetic issuer', 'TEST', 'Test', '8-K',
    clock_timestamp() - interval '2 hours',
    'https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/test.txt',
    clock_timestamp() - interval '90 minutes', 'skipped', clock_timestamp(),
    'retain', 'ambiguous_evidence', '{}', '{}'
);
INSERT INTO research_runs (run_id, started_at, completed_at, state, record)
VALUES (
    '10000000-0000-4000-8000-000000000001',
    clock_timestamp() - interval '30 minutes', clock_timestamp() - interval '20 minutes',
    'completed', '{"discovered_count":1}'
);
INSERT INTO research_pipeline_events (
    event_id, occurred_at, stage, run_id, accession_number, count,
    failure_category, schema_version
) VALUES
    ('11000000-0000-4000-8000-000000000001', clock_timestamp() - interval '30 minutes',
     'sec_poll_attempted', '10000000-0000-4000-8000-000000000001', NULL, 1, NULL, '1.0.0'),
    ('11000000-0000-4000-8000-000000000002', clock_timestamp() - interval '29 minutes',
     'candidate_processing', '10000000-0000-4000-8000-000000000001',
     '0000320193-26-000001', 1, NULL, '1.0.0'),
    ('11000000-0000-4000-8000-000000000003', clock_timestamp() - interval '28 minutes',
     'candidate_retrieved', '10000000-0000-4000-8000-000000000001',
     '0000320193-26-000001', 1, NULL, '1.0.0'),
    ('11000000-0000-4000-8000-000000000004', clock_timestamp() - interval '27 minutes',
     'candidate_parsed', '10000000-0000-4000-8000-000000000001',
     '0000320193-26-000001', 1, NULL, '1.0.0'),
    ('11000000-0000-4000-8000-000000000005', clock_timestamp() - interval '26 minutes',
     'companyfacts_normalized', '10000000-0000-4000-8000-000000000001',
     '0000320193-26-000001', 1, NULL, '1.0.0'),
    ('11000000-0000-4000-8000-000000000006', clock_timestamp() - interval '25 minutes',
     'tier_retained', '10000000-0000-4000-8000-000000000001',
     '0000320193-26-000001', 1, NULL, '1.0.0'),
    ('11000000-0000-4000-8000-000000000007', clock_timestamp() - interval '24 minutes',
     'candidate_skipped', '10000000-0000-4000-8000-000000000001',
     '0000320193-26-000001', 1, NULL, '1.0.0');
INSERT INTO research_detector_receipts (
    receipt_id, accession_number, observed_at, detector_name, invoked, status,
    contributed_to_escalation, schema_version
) VALUES (
    '12000000-0000-4000-8000-000000000001', '0000320193-26-000001',
    clock_timestamp() - interval '25 minutes', 'going_concern', true, 'positive',
    false, '1.0.0'
);
INSERT INTO research_analyst_attempts (
    attempt_id, invocation_id, origin, candidate_accession_number, ticker, cik,
    accession_number, filing_form, work_attempt, semantic_retry, provider_name,
    model_name, model_digest, prompt_version, output_schema_version,
    validation_version, role, attempt_number, started_at,
    input_evidence_count, input_evidence_characters, system_prompt_characters,
    user_prompt_characters, context_tokens, maximum_output_tokens,
    state, record
) VALUES (
    '13000000-0000-4000-8000-000000000001',
    '13100000-0000-4000-8000-000000000001', 'candidate',
    '0000320193-26-000001', 'TEST', '320193', '0000320193-26-000001', '8-K',
    1, false, 'ollama-loopback', 'qwen3:4b', repeat('c', 64), 'analyst-v2',
    '1.0.0', '1.0.0', 'catalyst_analyst', 1,
    clock_timestamp() - interval '23 minutes', 1, 500, 1000, 2000, 4096, 768,
    'started', '{}'
);
UPDATE research_analyst_attempts
SET state = 'completed', completed_at = started_at + interval '1 second', latency_ms = 1000,
    response_sha256 = repeat('d', 64), response_characters = 80, response_bytes = 80,
    parse_status = 'passed', schema_status = 'passed', evidence_status = 'passed',
    failure_layer = 'none', retry_eligible = false, retry_scope = 'none',
    outcome = 'accepted', terminal_disposition = 'accepted', record = '{}'
WHERE attempt_id = '13000000-0000-4000-8000-000000000001';
INSERT INTO research_verifier_reviews (
    review_id, candidate_id, accession_number, review_number, completed_at,
    verdict, model_name, model_digest, prompt_version, schema_version,
    challenge_categories, evidence_ids, record
) VALUES (
    '13500000-0000-4000-8000-000000000001',
    '13600000-0000-4000-8000-000000000001', '0000320193-26-000001', 1,
    clock_timestamp() - interval '22 minutes', 'approve', 'fixture-verifier',
    repeat('b', 64), 'verifier-v1', '1.0.0', '{}',
    ARRAY['13700000-0000-4000-8000-000000000001'::uuid], '{}'
);
INSERT INTO research_verification_dispositions (
    disposition_id, candidate_id, accession_number, decided_at, disposition,
    retry_count, analyst_model_name, analyst_model_digest, verifier_model_name,
    verifier_model_digest, review_ids, challenge_categories, evidence_ids, record
) VALUES (
    '13800000-0000-4000-8000-000000000001',
    '13600000-0000-4000-8000-000000000001', '0000320193-26-000001',
    clock_timestamp() - interval '21 minutes', 'approved', 0, 'qwen3:4b',
    repeat('c', 64), 'fixture-verifier', repeat('b', 64),
    ARRAY['13500000-0000-4000-8000-000000000001'::uuid], '{}', '{}', '{}'
);
WITH decision AS (
    SELECT
        '13900000-0000-4000-8000-000000000001'::uuid AS decision_id,
        clock_timestamp() - interval '21 minutes' AS decided_at,
        ARRAY['13000000-0000-4000-8000-000000000001'::uuid] AS analyst_attempt_ids
)
INSERT INTO research_autonomous_screening_decisions (
    decision_id, accession_number, decided_at, disposition, reason, work_attempt,
    run_id, analyst_attempt_ids, source_document_sha256, schema_version, record
)
SELECT
    decision_id, '0000320193-26-000001', decided_at, 'QUALIFIED',
    'VALIDATED_PUBLICATION', 1, '10000000-0000-4000-8000-000000000001',
    analyst_attempt_ids, repeat('e', 64), '1.0.0',
    jsonb_build_object(
        'decision_id', decision_id,
        'accession_number', '0000320193-26-000001',
        'decided_at', decided_at,
        'disposition', 'QUALIFIED',
        'reason', 'VALIDATED_PUBLICATION',
        'work_attempt', 1,
        'run_id', '10000000-0000-4000-8000-000000000001',
        'analyst_attempt_ids', analyst_attempt_ids,
        'source_document_sha256', repeat('e', 64),
        'schema_version', '1.0.0'
    )
FROM decision;
INSERT INTO research_briefs (
    brief_id, schema_version, accession_number, ticker, company_name, classification,
    attention_points, risk_points, evidence_strength_points, filed_at, retrieved_at,
    published_at, source_document_sha256, verification_disposition_id,
    autonomous_decision_id, record
)
SELECT
    '14000000-0000-4000-8000-000000000001', '2.0.0', '0000320193-26-000001',
    'TEST', 'Synthetic issuer', 'watch', 10, 10, 10,
    clock_timestamp() - interval '2 hours', clock_timestamp() - interval '22 minutes',
    decided_at, repeat('e', 64), '13800000-0000-4000-8000-000000000001',
    decision_id, '{}'
FROM research_autonomous_screening_decisions
WHERE decision_id = '13900000-0000-4000-8000-000000000001';
INSERT INTO research_notification_deliveries (
    delivery_id, notification_key, brief_id, completed_at, status, record
) VALUES (
    '15000000-0000-4000-8000-000000000001', repeat('f', 64),
    '14000000-0000-4000-8000-000000000001', clock_timestamp() - interval '20 minutes',
    'sent', '{}'
);
SQL

if docker exec "$container" psql --username kalki_owner --dbname kalki \
    --command "DELETE FROM research_pipeline_events" >/dev/null 2>&1; then
    echo "Pipeline telemetry was unexpectedly deletable." >&2
    exit 1
fi

KALKI_FUNNEL_GATE_PASSWORD_FILE="$password_file" KALKI_FUNNEL_GATE_PORT=55440 \
    "$repository_dir/.venv/bin/pytest" -q \
    "$repository_dir/tests/test_funnel_postgres_integration.py"

echo "Disposable PostgreSQL funnel reconciliation gate passed."
