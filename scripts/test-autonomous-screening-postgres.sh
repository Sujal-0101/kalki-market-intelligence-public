#!/bin/sh
set -eu

repository_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
image=postgres:18.0-alpine3.22@sha256:48c8ad3a7284b82be4482a52076d47d879fd6fb084a1cbfccbd551f9331b0e40
container=kalki-screening-postgres-gate-$$
cleanup() {
    docker container rm --force "$container" >/dev/null 2>&1 || true
}
trap cleanup EXIT HUP INT TERM

docker run --detach --name "$container" --network none \
    --tmpfs /var/lib/postgresql/data:rw,noexec,nosuid,size=768m \
    --env POSTGRES_HOST_AUTH_METHOD=trust --env POSTGRES_DB=kalki \
    --env POSTGRES_USER=kalki_owner "$image" >/dev/null

attempt=0
until docker exec "$container" psql --no-psqlrc --username kalki_owner --dbname kalki \
    --command "SELECT 1" >/dev/null 2>&1
do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 45 ]; then
        echo "Disposable screening database did not become ready." >&2
        exit 1
    fi
    sleep 1
done

docker exec "$container" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
    --username kalki_owner --dbname kalki \
    --command "CREATE ROLE kalki_app NOLOGIN;" >/dev/null
for migration in "$repository_dir"/migrations/00[01][0-9]_*.sql
do
    docker exec --interactive "$container" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
        --username kalki_owner --dbname kalki <"$migration" >/dev/null
done

docker exec --interactive "$container" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
    --username kalki_owner --dbname kalki >/dev/null <<'SQL'
INSERT INTO research_candidates (
    accession_number, cik, company_name, ticker, exchange, filing_form,
    filed_at, source_url, discovered_at, status, attempts, updated_at
) VALUES
    ('0000320193-26-000001', '320193', 'Qualified fixture', 'QUAL', 'Test', '8-K',
     '2026-08-28 09:00:00+00',
     'https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/test.txt',
     '2026-08-28 09:01:00+00', 'processing', 1, '2026-08-28 09:01:00+00'),
    ('0000320193-26-000002', '320193', 'Screened fixture', 'OUT', 'Test', '8-K',
     '2026-08-28 09:00:00+00',
     'https://www.sec.gov/Archives/edgar/data/320193/000032019326000002/test.txt',
     '2026-08-28 09:01:00+00', 'processing', 1, '2026-08-28 09:01:00+00'),
    ('0000320193-26-000003', '320193', 'Incomplete fixture', 'INC', 'Test', '8-K',
     '2026-08-28 09:00:00+00',
     'https://www.sec.gov/Archives/edgar/data/320193/000032019326000003/test.txt',
     '2026-08-28 09:01:00+00', 'processing', 1, '2026-08-28 09:01:00+00');

INSERT INTO research_analyst_attempts (
    attempt_id, invocation_id, origin, candidate_accession_number, ticker, cik,
    accession_number, filing_form, work_attempt, semantic_retry, provider_name,
    model_name, model_digest, prompt_version, output_schema_version,
    validation_version, role, attempt_number, started_at, input_evidence_count,
    input_evidence_characters, system_prompt_characters, user_prompt_characters,
    context_tokens, maximum_output_tokens, state, record
) VALUES (
    '71000000-0000-4000-8000-000000000001',
    '72000000-0000-4000-8000-000000000001', 'candidate',
    '0000320193-26-000001', 'QUAL', '320193', '0000320193-26-000001', '8-K',
    1, false, 'ollama-loopback', 'qwen3:4b', repeat('a', 64), 'analyst-v2',
    '1.0.0', '1.0.0', 'catalyst_analyst', 1, '2026-08-28 09:02:00+00',
    1, 500, 1000, 2000, 4096, 768, 'started', '{}'
);
UPDATE research_analyst_attempts
SET state = 'completed', completed_at = '2026-08-28 09:03:00+00', latency_ms = 60000,
    response_sha256 = repeat('b', 64), response_characters = 100, response_bytes = 100,
    prompt_tokens = 500, generated_tokens = 50, parse_status = 'passed',
    schema_status = 'passed', evidence_status = 'passed', failure_layer = 'none',
    retry_eligible = false, retry_scope = 'none', outcome = 'accepted',
    terminal_disposition = 'accepted', record = '{}'
WHERE attempt_id = '71000000-0000-4000-8000-000000000001';

SET ROLE kalki_app;
INSERT INTO research_autonomous_screening_decisions (
    decision_id, accession_number, decided_at, disposition, reason, work_attempt,
    run_id, analyst_attempt_ids, source_document_sha256, schema_version, record
) VALUES
    ('73000000-0000-4000-8000-000000000001', '0000320193-26-000001',
     '2026-08-28 09:04:00+00', 'QUALIFIED', 'VALIDATED_PUBLICATION', 1,
     '74000000-0000-4000-8000-000000000001',
     ARRAY['71000000-0000-4000-8000-000000000001'::uuid], repeat('c', 64), '1.0.0',
     '{"decision_id":"73000000-0000-4000-8000-000000000001","accession_number":"0000320193-26-000001","decided_at":"2026-08-28T09:04:00Z","disposition":"QUALIFIED","reason":"VALIDATED_PUBLICATION","work_attempt":1,"run_id":"74000000-0000-4000-8000-000000000001","analyst_attempt_ids":["71000000-0000-4000-8000-000000000001"],"source_document_sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","schema_version":"1.0.0"}'),
    ('73000000-0000-4000-8000-000000000002', '0000320193-26-000002',
     '2026-08-28 09:04:00+00', 'SCREENED_OUT', 'DETERMINISTIC_QUALIFICATION_NOT_MET', 1,
     '74000000-0000-4000-8000-000000000001', ARRAY[]::uuid[], repeat('d', 64), '1.0.0',
     '{"decision_id":"73000000-0000-4000-8000-000000000002","accession_number":"0000320193-26-000002","decided_at":"2026-08-28T09:04:00Z","disposition":"SCREENED_OUT","reason":"DETERMINISTIC_QUALIFICATION_NOT_MET","work_attempt":1,"run_id":"74000000-0000-4000-8000-000000000001","analyst_attempt_ids":[],"source_document_sha256":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd","schema_version":"1.0.0"}'),
    ('73000000-0000-4000-8000-000000000003', '0000320193-26-000003',
     '2026-08-28 09:04:00+00', 'ANALYSIS_INCOMPLETE', 'SOURCE_RETRIEVAL_FAILURE', 1,
     '74000000-0000-4000-8000-000000000001', ARRAY[]::uuid[], NULL, '1.0.0',
     '{"decision_id":"73000000-0000-4000-8000-000000000003","accession_number":"0000320193-26-000003","decided_at":"2026-08-28T09:04:00Z","disposition":"ANALYSIS_INCOMPLETE","reason":"SOURCE_RETRIEVAL_FAILURE","work_attempt":1,"run_id":"74000000-0000-4000-8000-000000000001","analyst_attempt_ids":[],"source_document_sha256":null,"schema_version":"1.0.0"}');

INSERT INTO research_briefs (
    brief_id, schema_version, accession_number, ticker, company_name, classification,
    attention_points, risk_points, evidence_strength_points, filed_at, retrieved_at,
    published_at, source_document_sha256, autonomous_decision_id, record
) VALUES (
    '75000000-0000-4000-8000-000000000001', '3.0.0',
    '0000320193-26-000001', 'QUAL', 'Qualified fixture', 'watch', 40, 20, 65,
    '2026-08-28 09:00:00+00', '2026-08-28 09:03:00+00',
    '2026-08-28 09:04:00+00', repeat('c', 64),
    '73000000-0000-4000-8000-000000000001',
    '{"schema_version":"3.0.0","verification":null,"publication_gate":{"status":"passed","mode":"deterministic_only","deterministic_validation_version":"1.0.0","validated_at":"2026-08-28T09:04:00Z","independent_verifier_status":"disabled"}}'
);
RESET ROLE;
SQL

if docker exec "$container" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
    --username kalki_owner --dbname kalki --command \
    "UPDATE research_autonomous_screening_decisions SET reason = 'UNKNOWN' WHERE decision_id = '73000000-0000-4000-8000-000000000003'" \
    >/dev/null 2>&1; then
    echo "A terminal screening decision was unexpectedly mutable." >&2
    exit 1
fi
if docker exec "$container" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
    --username kalki_owner --dbname kalki --command \
    "DELETE FROM research_autonomous_screening_decisions WHERE decision_id = '73000000-0000-4000-8000-000000000002'" \
    >/dev/null 2>&1; then
    echo "A terminal screening decision was unexpectedly deletable." >&2
    exit 1
fi

result=$(docker exec "$container" psql --no-psqlrc --tuples-only --no-align \
    --username kalki_owner --dbname kalki --command "
        SELECT count(*),
            count(*) FILTER (WHERE disposition = 'QUALIFIED'),
            count(*) FILTER (WHERE disposition = 'SCREENED_OUT'),
            count(*) FILTER (WHERE disposition = 'ANALYSIS_INCOMPLETE'),
            (SELECT count(*) FROM research_briefs WHERE schema_version = '3.0.0'),
            has_table_privilege('kalki_app', 'research_autonomous_screening_decisions', 'INSERT'),
            has_table_privilege('kalki_app', 'research_autonomous_screening_decisions', 'DELETE')
        FROM research_autonomous_screening_decisions;")
if [ "$result" != "3|1|1|1|1|t|f" ]; then
    echo "Unexpected screening decision lifecycle or privilege result: $result" >&2
    exit 1
fi

echo "Disposable PostgreSQL autonomous-screening gate passed."
