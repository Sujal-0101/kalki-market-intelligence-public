#!/bin/sh
set -eu

repository_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
migration="$repository_dir/migrations/0013_autonomous_screening_decisions.sql"
container=${KALKI_POSTGRES_CONTAINER:-kalki-production-postgres-1}

if ! docker inspect --format '{{.State.Health.Status}}' "$container" | grep -qx healthy; then
    echo "Production PostgreSQL is not healthy; refusing migration 0013." >&2
    exit 1
fi
if docker exec "$container" psql --username kalki_owner --dbname kalki \
    --no-align --tuples-only --command \
    "SELECT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '0013_autonomous_screening_decisions')" \
    | grep -qx t; then
    echo "Migration 0013 is already applied."
    exit 0
fi

docker cp "$migration" "$container:/tmp/0013_autonomous_screening_decisions.sql"
docker exec "$container" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
    --username kalki_owner --dbname kalki \
    --file /tmp/0013_autonomous_screening_decisions.sql
docker exec "$container" rm /tmp/0013_autonomous_screening_decisions.sql

echo "Migration 0013 applied without rewriting legacy candidate history."
