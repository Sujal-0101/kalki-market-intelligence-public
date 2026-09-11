#!/usr/bin/env bash
set -euo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
container=kalki-production-postgres-1
if docker exec "$container" psql -U kalki_owner -d kalki -Atqc "SELECT EXISTS (SELECT 1 FROM schema_migrations WHERE version='0009_human_research_results')" | grep -qx t; then exit 0; fi
docker cp "$repo/migrations/0009_human_research_results.sql" "$container:/tmp/0009.sql"
docker exec "$container" psql -v ON_ERROR_STOP=1 -U kalki_owner -d kalki -f /tmp/0009.sql
