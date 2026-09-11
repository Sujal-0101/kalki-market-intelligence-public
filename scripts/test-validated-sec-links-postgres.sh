#!/bin/sh
set -eu

repository_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
image=postgres:18.0-alpine3.22@sha256:48c8ad3a7284b82be4482a52076d47d879fd6fb084a1cbfccbd551f9331b0e40
container=kalki-sec-links-postgres-gate-$$
temporary_dir=$(mktemp -d)
cleanup() {
    docker container rm --force "$container" >/dev/null 2>&1 || true
    rm -r -- "$temporary_dir"
}
trap cleanup EXIT HUP INT TERM

printf 'unused-trust-auth-password\n' >"$temporary_dir/password"
docker run --detach --name "$container" --publish 127.0.0.1::5432 \
    --tmpfs /var/lib/postgresql/data:rw,noexec,nosuid,size=768m \
    --env POSTGRES_HOST_AUTH_METHOD=trust --env POSTGRES_DB=kalki \
    --env POSTGRES_USER=kalki_owner "$image" >/dev/null

attempt=0
until docker exec "$container" psql --no-psqlrc --username kalki_owner --dbname kalki \
    --command "SELECT 1" >/dev/null 2>&1
do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 45 ]; then
        echo "Disposable validated-link database did not become ready." >&2
        exit 1
    fi
    sleep 1
done

docker exec "$container" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
    --username kalki_owner --dbname kalki \
    --command "CREATE ROLE kalki_app LOGIN;" >/dev/null
for migration in "$repository_dir"/migrations/00[0-2][0-9]_*.sql
do
    docker exec --interactive "$container" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
        --username kalki_owner --dbname kalki <"$migration" >/dev/null
done

docker exec --interactive "$container" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
    --username kalki_owner --dbname kalki >/dev/null <<'SQL'
INSERT INTO research_candidates (
    accession_number, cik, company_name, ticker, exchange, filing_form,
    filed_at, source_url, discovered_at, status, attempts, updated_at
) VALUES (
    '0000320193-26-000001', '320193', 'Synthetic link issuer', 'LINK', 'Test', '8-K',
    '2026-08-30 10:00:00+00',
    'https://www.sec.gov/Archives/edgar/data/320193/0000320193-26-000001.txt',
    '2026-08-30 10:01:00+00', 'processing', 1, '2026-08-30 10:01:00+00'
);
INSERT INTO research_analyst_attempts (
    attempt_id, invocation_id, origin, candidate_accession_number, ticker, cik,
    accession_number, filing_form, work_attempt, semantic_retry, provider_name,
    model_name, model_digest, prompt_version, output_schema_version,
    validation_version, role, attempt_number, started_at, input_evidence_count,
    input_evidence_characters, system_prompt_characters, user_prompt_characters,
    context_tokens, maximum_output_tokens, state, record
) VALUES (
    '81000000-0000-4000-8000-000000000001',
    '82000000-0000-4000-8000-000000000001', 'candidate',
    '0000320193-26-000001', 'LINK', '320193', '0000320193-26-000001', '8-K',
    1, false, 'ollama-loopback', 'qwen3:4b', repeat('a', 64), 'analyst-v2',
    '1.0.0', '1.0.0', 'catalyst_analyst', 1, '2026-08-30 10:02:00+00',
    1, 500, 1000, 2000, 4096, 768, 'started', '{}'
);
UPDATE research_analyst_attempts
SET state = 'completed', completed_at = '2026-08-30 10:03:00+00', latency_ms = 60000,
    response_sha256 = repeat('b', 64), response_characters = 100, response_bytes = 100,
    prompt_tokens = 500, generated_tokens = 50, parse_status = 'passed',
    schema_status = 'passed', evidence_status = 'passed', failure_layer = 'none',
    retry_eligible = false, retry_scope = 'none', outcome = 'accepted',
    terminal_disposition = 'accepted', record = '{}'
WHERE attempt_id = '81000000-0000-4000-8000-000000000001';

SET ROLE kalki_app;
INSERT INTO research_sec_link_receipts (
    receipt_id, canonical_cik, accession_number, complete_submission_url,
    archive_index_url, primary_document_url, inline_xbrl_url,
    complete_submission_sha256, archive_index_sha256, primary_document_sha256,
    inline_xbrl_validated, validated_at, validation_version, record
) VALUES (
    '3583000e-78b0-5afd-a154-5bfa7901c228', '0000320193',
    '0000320193-26-000001',
    'https://www.sec.gov/Archives/edgar/data/320193/0000320193-26-000001.txt',
    'https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/0000320193-26-000001-index.html',
    'https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/event.htm', NULL,
    repeat('c', 64), repeat('d', 64), repeat('e', 64), false,
    '2026-08-30 10:03:30+00', '1.0.0',
    '{"receipt_id":"3583000e-78b0-5afd-a154-5bfa7901c228","canonical_cik":"0000320193","accession_number":"0000320193-26-000001","complete_submission_url":"https://www.sec.gov/Archives/edgar/data/320193/0000320193-26-000001.txt","archive_index_url":"https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/0000320193-26-000001-index.html","primary_document_url":"https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/event.htm","inline_xbrl_url":null,"complete_submission_sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","archive_index_sha256":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd","primary_document_sha256":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee","inline_xbrl_validated":false,"validated_at":"2026-08-30T10:03:30Z","validation_version":"1.0.0"}'
);
INSERT INTO research_autonomous_screening_decisions (
    decision_id, accession_number, decided_at, disposition, reason, work_attempt,
    run_id, analyst_attempt_ids, source_document_sha256, schema_version, record
) VALUES (
    '84000000-0000-4000-8000-000000000001', '0000320193-26-000001',
    '2026-08-30 10:04:00+00', 'QUALIFIED', 'VALIDATED_PUBLICATION', 1,
    '85000000-0000-4000-8000-000000000001',
    ARRAY['81000000-0000-4000-8000-000000000001'::uuid], repeat('c', 64), '1.0.0',
    '{"decision_id":"84000000-0000-4000-8000-000000000001","accession_number":"0000320193-26-000001","decided_at":"2026-08-30T10:04:00Z","disposition":"QUALIFIED","reason":"VALIDATED_PUBLICATION","work_attempt":1,"run_id":"85000000-0000-4000-8000-000000000001","analyst_attempt_ids":["81000000-0000-4000-8000-000000000001"],"source_document_sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","schema_version":"1.0.0"}'
);
RESET ROLE;
SQL

if docker exec --interactive "$container" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
    --username kalki_owner --dbname kalki >/dev/null 2>&1 <<'SQL'
INSERT INTO research_briefs (
    brief_id, schema_version, accession_number, ticker, company_name, classification,
    attention_points, risk_points, evidence_strength_points, filed_at, retrieved_at,
    published_at, source_document_sha256, autonomous_decision_id, record
) VALUES (
    '86000000-0000-4000-8000-000000000001', '3.0.0',
    '0000320193-26-000001', 'LINK', 'Synthetic link issuer', 'watch', 40, 20, 65,
    '2026-08-30 10:00:00+00', '2026-08-30 10:03:00+00',
    '2026-08-30 10:04:00+00', repeat('c', 64),
    '84000000-0000-4000-8000-000000000001',
    '{"schema_version":"3.0.0","source_url":"https://www.sec.gov/Archives/edgar/data/320193/0000320193-26-000001.txt","verification":null,"publication_gate":{"status":"passed","mode":"deterministic_only","deterministic_validation_version":"1.0.0","validated_at":"2026-08-30T10:04:00Z","independent_verifier_status":"disabled"}}'
);
SQL
then
    echo "A future brief without validated link lineage unexpectedly passed." >&2
    exit 1
fi

docker exec --interactive "$container" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
    --username kalki_owner --dbname kalki >/dev/null <<'SQL'
SET ROLE kalki_app;
INSERT INTO research_briefs (
    brief_id, schema_version, accession_number, ticker, company_name, classification,
    attention_points, risk_points, evidence_strength_points, filed_at, retrieved_at,
    published_at, source_document_sha256, autonomous_decision_id, sec_link_receipt_id, record
) VALUES (
    '86000000-0000-4000-8000-000000000001', '3.0.0',
    '0000320193-26-000001', 'LINK', 'Synthetic link issuer', 'watch', 40, 20, 65,
    '2026-08-30 10:00:00+00', '2026-08-30 10:03:00+00',
    '2026-08-30 10:04:00+00', repeat('c', 64),
    '84000000-0000-4000-8000-000000000001',
    '3583000e-78b0-5afd-a154-5bfa7901c228',
    '{"schema_version":"3.0.0","source_url":"https://www.sec.gov/Archives/edgar/data/320193/0000320193-26-000001.txt","verification":null,"publication_gate":{"status":"passed","mode":"deterministic_only","deterministic_validation_version":"1.0.0","validated_at":"2026-08-30T10:04:00Z","independent_verifier_status":"disabled"}}'
);
RESET ROLE;
SQL

if docker exec "$container" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
    --username kalki_owner --dbname kalki --command \
    "UPDATE research_sec_link_receipts SET validation_version = validation_version" \
    >/dev/null 2>&1; then
    echo "A validated SEC-link receipt was unexpectedly mutable." >&2
    exit 1
fi

result=$(docker exec "$container" psql --no-psqlrc --tuples-only --no-align \
    --username kalki_owner --dbname kalki --command "
        SELECT (SELECT count(*) FROM research_sec_link_receipts),
               (SELECT count(*) FROM research_briefs WHERE sec_link_receipt_id IS NOT NULL),
               has_table_privilege('kalki_app', 'research_sec_link_receipts', 'INSERT'),
               has_table_privilege('kalki_app', 'research_sec_link_receipts', 'DELETE'),
               (SELECT count(*) FROM schema_migrations
                WHERE version = '0020_validated_sec_links');")
if [ "$result" != "1|1|t|f|1" ]; then
    echo "Unexpected validated SEC-link lifecycle or privilege result: $result" >&2
    exit 1
fi

published_port=$(docker port "$container" 5432/tcp | sed 's/^.*://')
KALKI_SEC_LINK_GATE_PASSWORD_FILE="$temporary_dir/password" \
KALKI_SEC_LINK_GATE_PORT="$published_port" \
    "$repository_dir/.venv/bin/pytest" -q \
    "$repository_dir/tests/test_sec_links_postgres_integration.py"

echo "Disposable PostgreSQL validated SEC-link gate passed."
