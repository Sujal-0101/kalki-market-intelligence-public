#!/bin/sh
set -eu

repository_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
image=postgres:18.0-alpine3.22@sha256:48c8ad3a7284b82be4482a52076d47d879fd6fb084a1cbfccbd551f9331b0e40
container=kalki-phase17-postgres-gate-$$
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
        echo "Disposable verifier database did not become ready." >&2
        exit 1
    fi
    sleep 1
done

docker exec "$container" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
    --username kalki_owner --dbname kalki \
    --command "CREATE ROLE kalki_app NOLOGIN;" >/dev/null
for migration in "$repository_dir"/migrations/000[1-5]_*.sql
do
    docker exec --interactive "$container" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
        --username kalki_owner --dbname kalki <"$migration" >/dev/null
done

docker exec --interactive "$container" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
    --username kalki_owner --dbname kalki >/dev/null <<'SQL'
INSERT INTO research_candidates (
    accession_number, cik, company_name, ticker, exchange, filing_form,
    filed_at, source_url, discovered_at, updated_at
) VALUES
    ('0000000001-26-000001', '1', 'Synthetic issuer one', 'ONE', 'Test', '8-K',
     '2026-08-25 10:00:00+00',
     'https://www.sec.gov/Archives/edgar/data/1/000000000126000001/test.txt',
     '2026-08-25 10:01:00+00', '2026-08-25 10:01:00+00'),
    ('0000000002-26-000002', '2', 'Synthetic issuer two', 'TWO', 'Test', '8-K',
     '2026-08-25 10:00:00+00',
     'https://www.sec.gov/Archives/edgar/data/2/000000000226000002/test.txt',
     '2026-08-25 10:01:00+00', '2026-08-25 10:01:00+00');
SQL

if docker exec --interactive "$container" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
    --username kalki_owner --dbname kalki >/dev/null 2>&1 <<'SQL'
INSERT INTO research_briefs (
    brief_id, schema_version, accession_number, company_name, classification,
    attention_points, risk_points, evidence_strength_points, filed_at,
    retrieved_at, published_at, source_document_sha256, record
) VALUES (
    '10000000-0000-4000-8000-000000000001', '1.0.0',
    '0000000001-26-000001', 'Synthetic issuer one', 'watch', 20, 10, 70,
    '2026-08-25 10:00:00+00', '2026-08-25 10:02:00+00',
    '2026-08-25 10:03:00+00', repeat('a', 64), '{}'
);
SQL
then
    echo "Unverified publication unexpectedly passed the database trigger." >&2
    exit 1
fi

docker exec --interactive "$container" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
    --username kalki_owner --dbname kalki >/dev/null <<'SQL'
INSERT INTO research_verifier_reviews (
    review_id, candidate_id, accession_number, review_number, completed_at,
    verdict, model_name, model_digest, prompt_version, schema_version,
    challenge_categories, evidence_ids, record
) VALUES (
    '20000000-0000-4000-8000-000000000001',
    '21000000-0000-4000-8000-000000000001', '0000000001-26-000001', 1,
    '2026-08-25 10:03:00+00', 'approve', 'gemma4:12b-it-q4_K_M', repeat('b', 64),
    'verifier-v1', '1.0.0', '{}',
    ARRAY['22000000-0000-4000-8000-000000000001'::uuid], '{}'
);
INSERT INTO research_verification_dispositions (
    disposition_id, candidate_id, accession_number, decided_at, disposition,
    retry_count, analyst_model_name, analyst_model_digest, verifier_model_name,
    verifier_model_digest, review_ids, challenge_categories, evidence_ids, record
) VALUES (
    '23000000-0000-4000-8000-000000000001',
    '21000000-0000-4000-8000-000000000001', '0000000001-26-000001',
    '2026-08-25 10:04:00+00', 'approved', 0, 'qwen3:4b', repeat('c', 64),
    'gemma4:12b-it-q4_K_M', repeat('b', 64),
    ARRAY['20000000-0000-4000-8000-000000000001'::uuid], '{}', '{}', '{}'
);
INSERT INTO research_briefs (
    brief_id, schema_version, accession_number, company_name, classification,
    attention_points, risk_points, evidence_strength_points, filed_at,
    retrieved_at, published_at, source_document_sha256,
    verification_disposition_id, record
) VALUES (
    '10000000-0000-4000-8000-000000000001', '2.0.0',
    '0000000001-26-000001', 'Synthetic issuer one', 'watch', 20, 10, 70,
    '2026-08-25 10:00:00+00', '2026-08-25 10:02:00+00',
    '2026-08-25 10:04:00+00', repeat('a', 64),
    '23000000-0000-4000-8000-000000000001', '{}'
);
INSERT INTO research_verifier_reviews (
    review_id, candidate_id, accession_number, review_number, completed_at,
    verdict, model_name, model_digest, prompt_version, schema_version,
    challenge_categories, evidence_ids, record
) VALUES (
    '30000000-0000-4000-8000-000000000001',
    '31000000-0000-4000-8000-000000000001', '0000000002-26-000002', 1,
    '2026-08-25 10:03:00+00', 'challenge', 'gemma4:12b-it-q4_K_M', repeat('b', 64),
    'verifier-v1', '1.0.0', ARRAY['missing_material_risk'],
    ARRAY['32000000-0000-4000-8000-000000000001'::uuid], '{}'
);
INSERT INTO research_verification_retries (
    retry_id, candidate_id, accession_number, reserved_at, review_id, reconsideration
) VALUES (
    '33000000-0000-4000-8000-000000000001',
    '31000000-0000-4000-8000-000000000001', '0000000002-26-000002',
    '2026-08-25 10:04:00+00', '30000000-0000-4000-8000-000000000001', '{}'
);
INSERT INTO research_verifier_reviews (
    review_id, candidate_id, accession_number, review_number, completed_at,
    verdict, model_name, model_digest, prompt_version, schema_version,
    challenge_categories, evidence_ids, record
) VALUES (
    '30000000-0000-4000-8000-000000000002',
    '31000000-0000-4000-8000-000000000001', '0000000002-26-000002', 2,
    '2026-08-25 10:05:00+00', 'challenge', 'gemma4:12b-it-q4_K_M', repeat('b', 64),
    'verifier-v1', '1.0.0', ARRAY['missing_material_risk'],
    ARRAY['32000000-0000-4000-8000-000000000001'::uuid], '{}'
);
INSERT INTO research_verification_dispositions (
    disposition_id, candidate_id, accession_number, decided_at, disposition,
    retry_count, analyst_model_name, analyst_model_digest, verifier_model_name,
    verifier_model_digest, review_ids, challenge_categories, evidence_ids, record
) VALUES (
    '34000000-0000-4000-8000-000000000001',
    '31000000-0000-4000-8000-000000000001', '0000000002-26-000002',
    '2026-08-25 10:06:00+00', 'verification_disagreement', 1,
    'qwen3:4b', repeat('c', 64), 'gemma4:12b-it-q4_K_M', repeat('b', 64),
    ARRAY[
        '30000000-0000-4000-8000-000000000001'::uuid,
        '30000000-0000-4000-8000-000000000002'::uuid
    ], ARRAY['missing_material_risk'],
    ARRAY['32000000-0000-4000-8000-000000000001'::uuid], '{}'
);
SQL

if docker exec --interactive "$container" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
    --username kalki_owner --dbname kalki >/dev/null 2>&1 <<'SQL'
UPDATE research_verifier_reviews SET verdict = 'approve'
WHERE review_id = '30000000-0000-4000-8000-000000000002';
SQL
then
    echo "Append-only verifier review unexpectedly allowed an update." >&2
    exit 1
fi

result=$(docker exec "$container" psql --no-psqlrc --tuples-only --no-align \
    --username kalki_owner --dbname kalki --command "
        SELECT
            (SELECT count(*) FROM research_briefs),
            (SELECT count(*) FROM research_verifier_reviews),
            (SELECT count(*) FROM research_verification_retries),
            (SELECT count(*) FROM research_verification_dispositions),
            has_table_privilege('kalki_app', 'research_verifier_reviews', 'INSERT'),
            has_table_privilege('kalki_app', 'research_verifier_reviews', 'UPDATE');")
if [ "$result" != "1|3|1|2|t|f" ]; then
    echo "Unexpected verifier lifecycle or privilege result: $result" >&2
    exit 1
fi

echo "Disposable PostgreSQL hierarchical-verifier lifecycle gate passed."
