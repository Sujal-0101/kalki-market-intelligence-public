#!/bin/sh
set -eu

repository_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
migration="$repository_dir/migrations/0011_funnel_telemetry.sql"
container=${KALKI_POSTGRES_CONTAINER:-kalki-production-postgres-1}

if ! docker inspect --format '{{.State.Health.Status}}' "$container" | grep -qx healthy; then
    echo "Production PostgreSQL is not healthy; refusing migration 0011." >&2
    exit 1
fi
if docker exec "$container" psql --username kalki_owner --dbname kalki \
    --no-align --tuples-only --command \
    "SELECT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '0011_funnel_telemetry')" \
    | grep -qx t; then
    echo "Migration 0011 is already applied."
    exit 0
fi

docker cp "$migration" "$container:/tmp/0011_funnel_telemetry.sql"
docker exec "$container" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
    --username kalki_owner --dbname kalki --file /tmp/0011_funnel_telemetry.sql
docker exec "$container" rm /tmp/0011_funnel_telemetry.sql

echo "Migration 0011 applied. It has no destructive automatic rollback."
