#!/usr/bin/env bash
set -euo pipefail
repository_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
migration="$repository_dir/migrations/0008_human_research_feedback.sql"
container="kalki-production-postgres-1"
if docker exec "$container" psql -U kalki_owner -d kalki -Atqc "SELECT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '0008_human_research_feedback')" | grep -qx t; then
  echo "Migration 0008 is already applied."; exit 0
fi
docker cp "$migration" "$container:/tmp/0008_human_research_feedback.sql"
docker exec "$container" psql -v ON_ERROR_STOP=1 -U kalki_owner -d kalki -f /tmp/0008_human_research_feedback.sql
echo "Migration 0008 applied. It has no destructive automatic rollback."
