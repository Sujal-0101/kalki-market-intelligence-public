#!/bin/sh
set -eu

repository_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
migration="$repository_dir/migrations/0018_event_novelty_lineage.sql"
container=${KALKI_POSTGRES_CONTAINER:-kalki-production-postgres-1}
remote_migration=/tmp/0018_event_novelty_lineage.sql
cleanup() {
    docker exec "$container" rm -f "$remote_migration" >/dev/null 2>&1 || true
}
trap cleanup EXIT HUP INT TERM

if ! docker inspect --format '{{.State.Health.Status}}' "$container" | grep -qx healthy; then
    echo "Production PostgreSQL is not healthy; refusing migration 0018." >&2
    exit 1
fi
if docker exec "$container" psql --username kalki_owner --dbname kalki \
    --no-align --tuples-only --command \
    "SELECT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '0018_event_novelty_lineage')" \
    | grep -qx t; then
    echo "Migration 0018 is already applied."
    exit 0
fi
prior_versions=$(docker exec "$container" psql --username kalki_owner --dbname kalki \
    --no-align --tuples-only --command \
    "SELECT string_agg(version, ',' ORDER BY version) FROM schema_migrations")
expected_versions='0001_prediction_outcomes,0002_web_operations,0003_publication_list_index,0004_live_research_radar,0005_hierarchical_verifier,0006_tier0_decisions,0007_human_research_leads,0008_human_research_feedback,0009_human_research_results,0010_analyst_attempt_receipts,0011_funnel_telemetry,0012_human_result_provenance,0013_autonomous_screening_decisions,0014_prospective_outcomes,0015_ownership_intelligence,0016_ownership_index_identity,0017_financing_intelligence'
if [ "$prior_versions" != "$expected_versions" ]; then
    echo "Production migration history is not the exact supported pre-0018 history." >&2
    exit 1
fi

docker cp "$migration" "$container:$remote_migration"
docker exec "$container" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
    --username kalki_owner --dbname kalki --file "$remote_migration"

echo "Migration 0018 applied. Existing event and publication history was not rewritten."
