#!/bin/sh
set -eu

direction=${1:-}
case "$direction" in
    up)
        migration=migrations/0003_publication_list_index.sql
        expected_present=t
        ;;
    down)
        migration=migrations/rollback/0003_publication_list_index.sql
        expected_present=f
        ;;
    *)
        echo "Usage: scripts/migrate-postgres.sh up|down" >&2
        exit 2
        ;;
esac

if ! docker compose -f compose.production.yaml exec -T postgres \
    pg_isready --username kalki_owner --dbname kalki >/dev/null; then
    echo "Production PostgreSQL is not healthy; migration refused." >&2
    exit 1
fi

present=$(docker compose -f compose.production.yaml exec -T postgres \
    psql --no-psqlrc --tuples-only --no-align --username kalki_owner --dbname kalki \
    --command "SELECT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '0003_publication_list_index')")

if [ "$present" = "$expected_present" ]; then
    echo "Migration 0003 is already in the requested state."
    exit 0
fi

docker compose -f compose.production.yaml exec -T postgres \
    psql --no-psqlrc --set=ON_ERROR_STOP=1 --username kalki_owner --dbname kalki < "$migration"

echo "Migration 0003 changed successfully; verify the application and query plan."
