#!/bin/sh
set -eu

repository_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
image=postgres:18.0-alpine3.22@sha256:48c8ad3a7284b82be4482a52076d47d879fd6fb084a1cbfccbd551f9331b0e40
container=kalki-phase33-postgres-gate-$$
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
        echo "Disposable analyst-attempt database did not become ready." >&2
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
    filed_at, source_url, discovered_at, updated_at
) VALUES (
    '0000320193-26-000001', '320193', 'Synthetic issuer', 'TEST', 'Test', '8-K',
    '2026-08-27 10:00:00+00',
    'https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/test.txt',
    '2026-08-27 10:01:00+00', '2026-08-27 10:01:00+00'
);
INSERT INTO research_human_leads (
    lead_id, discord_message_id, submitter_user_id, channel_id, submitted_at,
    ticker, cik, hypothesis, original_submission_sha256, dedupe_key,
    status, attempts, created_at, updated_at
) VALUES (
    '10000000-0000-4000-8000-000000000001', '123456789012345678',
    '223456789012345678', '323456789012345678', '2026-08-27 10:00:00+00',
    'TEST', '320193', 'Synthetic private hypothesis', repeat('a', 64), repeat('b', 64),
    'analyzing', 1, '2026-08-27 10:00:00+00', '2026-08-27 10:01:00+00'
);
SET ROLE kalki_app;
INSERT INTO research_analyst_attempts (
    attempt_id, invocation_id, origin, candidate_accession_number, lead_id, ticker, cik,
    accession_number, filing_form, work_attempt, semantic_retry, provider_name,
    model_name, model_digest, prompt_version, output_schema_version,
    validation_version, role, attempt_number, started_at, input_evidence_count,
    input_evidence_characters, system_prompt_characters, user_prompt_characters,
    context_tokens, maximum_output_tokens, state, record
) VALUES (
    '20000000-0000-4000-8000-000000000001',
    '21000000-0000-4000-8000-000000000001', 'candidate',
    '0000320193-26-000001', NULL, 'TEST', '320193', '0000320193-26-000001', '8-K',
    1, false, 'ollama-loopback', 'qwen3:4b', repeat('c', 64), 'analyst-v2',
    '1.0.0', '1.0.0', 'catalyst_analyst', 1, '2026-08-27 10:02:00+00',
    1, 500, 1000, 2000, 4096, 768, 'started', '{}'
), (
    '20000000-0000-4000-8000-000000000002',
    '21000000-0000-4000-8000-000000000002', 'human', NULL,
    '10000000-0000-4000-8000-000000000001', 'TEST', '320193',
    '0000320193-26-000001', '8-K', 1, false,
    'ollama-loopback', 'qwen3:4b', repeat('c', 64), 'analyst-v2', '1.0.0',
    '1.0.0', 'bull_bear_risk_analyst', 1, '2026-08-27 10:02:00+00',
    1, 500, 1000, 2000, 4096, 768, 'started', '{}'
);
UPDATE research_analyst_attempts
SET state = 'completed', completed_at = '2026-08-27 10:03:00+00', latency_ms = 60000,
    response_sha256 = repeat('d', 64), response_characters = 800, response_bytes = 800,
    prompt_tokens = 500, generated_tokens = 200, parse_status = 'passed',
    schema_status = 'passed', evidence_status = 'passed', failure_layer = 'none',
    retry_eligible = false, retry_scope = 'none', outcome = 'accepted',
    terminal_disposition = 'accepted', record = '{}'
WHERE attempt_id = '20000000-0000-4000-8000-000000000001';
UPDATE research_analyst_attempts
SET state = 'completed', completed_at = '2026-08-27 10:07:00+00', latency_ms = 300000,
    parse_status = 'not_checked', schema_status = 'not_checked',
    evidence_status = 'not_checked', failure_layer = 'runtime',
    failure_category = 'timeout', failure_path = 'provider.generate',
    retry_eligible = false, retry_scope = 'none', outcome = 'runtime_error',
    terminal_disposition = 'provider_error', record = '{}'
WHERE attempt_id = '20000000-0000-4000-8000-000000000002';
RESET ROLE;
SQL

if docker exec "$container" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
    --username kalki_owner --dbname kalki --command \
    "UPDATE research_analyst_attempts SET latency_ms = 1 WHERE attempt_id = '20000000-0000-4000-8000-000000000001'" \
    >/dev/null 2>&1; then
    echo "A completed analyst receipt was unexpectedly mutable." >&2
    exit 1
fi
if docker exec "$container" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
    --username kalki_owner --dbname kalki --command \
    "DELETE FROM research_analyst_attempts WHERE attempt_id = '20000000-0000-4000-8000-000000000001'" \
    >/dev/null 2>&1; then
    echo "An analyst receipt was unexpectedly deletable." >&2
    exit 1
fi

result=$(docker exec "$container" psql --no-psqlrc --tuples-only --no-align \
    --username kalki_owner --dbname kalki --command "
        SELECT count(*),
            count(*) FILTER (WHERE outcome = 'accepted'),
            count(*) FILTER (WHERE failure_category = 'timeout'),
            has_table_privilege('kalki_app', 'research_analyst_attempts', 'INSERT'),
            has_table_privilege('kalki_app', 'research_analyst_attempts', 'UPDATE'),
            has_table_privilege('kalki_app', 'research_analyst_attempts', 'DELETE')
        FROM research_analyst_attempts;")
if [ "$result" != "2|1|1|t|t|f" ]; then
    echo "Unexpected analyst-attempt lifecycle or privilege result: $result" >&2
    exit 1
fi

echo "Disposable PostgreSQL analyst-attempt lifecycle gate passed."
