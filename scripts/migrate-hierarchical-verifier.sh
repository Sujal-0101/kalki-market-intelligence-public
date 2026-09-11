#!/bin/sh
set -eu

repository_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
migration=$repository_dir/migrations/0005_hierarchical_verifier.sql

cd "$repository_dir"

if ! docker compose -f compose.production.yaml exec -T postgres \
    pg_isready --username kalki_owner --dbname kalki >/dev/null; then
    echo "Production PostgreSQL is not healthy; migration refused." >&2
    exit 1
fi

applied=$(docker compose -f compose.production.yaml exec -T postgres \
    psql --no-psqlrc --tuples-only --no-align --username kalki_owner --dbname kalki \
    --command "SELECT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '0005_hierarchical_verifier')")
if [ "$applied" = "t" ]; then
    echo "Migration 0005 is already applied."
    exit 0
fi

docker compose -f compose.production.yaml exec -T postgres \
    psql --no-psqlrc --set=ON_ERROR_STOP=1 --username kalki_owner --dbname kalki < "$migration"

echo "Migration 0005 applied. It has no destructive automatic rollback."
