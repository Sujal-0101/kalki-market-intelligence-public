#!/bin/sh
set -eu

repository_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
hours=${1:-168}
case "$hours" in
    ''|*[!0-9]*)
        echo "Usage: scripts/report-analyst-attempts.sh [WINDOW_HOURS]" >&2
        exit 2
        ;;
esac
if [ "$hours" -lt 1 ] || [ "$hours" -gt 8760 ]; then
    echo "Window hours must be between 1 and 8760." >&2
    exit 2
fi

cd "$repository_dir"
docker compose -f compose.production.yaml exec -T postgres \
    psql --no-psqlrc --set=ON_ERROR_STOP=1 --set=window_hours="$hours" \
    --username kalki_owner --dbname kalki --tuples-only --no-align <<'SQL'
WITH bounds AS (
    SELECT clock_timestamp() AS observed_at,
           clock_timestamp() - (:'window_hours'::integer * interval '1 hour') AS since
),
windowed AS (
    SELECT a.* FROM research_analyst_attempts a, bounds b
    WHERE a.started_at >= b.since
),
completed AS (
    SELECT * FROM windowed WHERE state = 'completed'
),
category_counts AS (
    SELECT COALESCE(jsonb_object_agg(failure_category, category_count), '{}'::jsonb) AS value
    FROM (
        SELECT failure_category, count(*) AS category_count
        FROM completed WHERE failure_category IS NOT NULL
        GROUP BY failure_category ORDER BY failure_category
    ) categories
),
origin_counts AS (
    SELECT COALESCE(jsonb_object_agg(origin, origin_count), '{}'::jsonb) AS value
    FROM (
        SELECT origin, count(*) AS origin_count
        FROM completed GROUP BY origin ORDER BY origin
    ) origins
),
latency AS (
    SELECT count(*) AS sample_size,
           min(latency_ms) AS minimum_ms,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) AS p50_ms,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_ms,
           max(latency_ms) AS maximum_ms
    FROM completed
    WHERE failure_path IS DISTINCT FROM 'worker.processing_lease_expired'
),
summary AS (
    SELECT jsonb_build_object(
        'observed_at_utc', b.observed_at,
        'window_start_utc', b.since,
        'window_hours', :'window_hours'::integer,
        'attempts_started', count(w.attempt_id),
        'attempts_incomplete', count(*) FILTER (WHERE w.state = 'started'),
        'attempts_completed', count(*) FILTER (WHERE w.state = 'completed'),
        'valid_contracts', count(*) FILTER (WHERE w.outcome = 'accepted'),
        'format_failures', count(*) FILTER (WHERE w.failure_layer = 'format'),
        'content_evidence_failures', count(*) FILTER (
            WHERE w.failure_layer = 'content_evidence'
        ),
        'runtime_failures', count(*) FILTER (WHERE w.failure_layer = 'runtime'),
        'timeouts', count(*) FILTER (WHERE w.failure_category = 'timeout'),
        'provider_errors', count(*) FILTER (WHERE w.failure_category = 'provider_error'),
        'interrupted_recoveries', count(*) FILTER (
            WHERE w.failure_path = 'worker.processing_lease_expired'
        ),
        'pipeline_retry_attempts', count(*) FILTER (WHERE w.attempt_number > 1),
        'pipeline_retry_successes', count(*) FILTER (
            WHERE w.attempt_number > 1 AND w.outcome = 'accepted'
        ),
        'work_item_retry_attempts', count(*) FILTER (
            WHERE w.work_attempt > 1 AND w.attempt_number = 1
        ),
        'work_item_retry_successes', count(*) FILTER (
            WHERE w.work_attempt > 1 AND w.attempt_number = 1 AND w.outcome = 'accepted'
        ),
        'latency_sample_size', l.sample_size,
        'latency_sample_label', CASE WHEN l.sample_size < 30 THEN 'small_n' ELSE 'descriptive' END,
        'latency_minimum_ms', l.minimum_ms,
        'latency_p50_ms', l.p50_ms,
        'latency_p95_ms', l.p95_ms,
        'latency_maximum_ms', l.maximum_ms,
        'failure_categories', c.value,
        'origins', o.value
    ) AS report
    FROM bounds b CROSS JOIN latency l CROSS JOIN category_counts c CROSS JOIN origin_counts o
    LEFT JOIN windowed w ON true
    GROUP BY b.observed_at, b.since, l.sample_size, l.minimum_ms, l.p50_ms, l.p95_ms,
             l.maximum_ms, c.value, o.value
)
SELECT jsonb_pretty(report) FROM summary;
SQL
