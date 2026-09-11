BEGIN;

-- A worker can be unavailable longer than the original two-hour runtime bound.
-- Interrupted attempts are completed only after lease expiry, so their latency is
-- the truthful durable-record lifetime through recovery. PostgreSQL bigint remains
-- the explicit storage bound.
ALTER TABLE research_analyst_attempts
    DROP CONSTRAINT research_analyst_attempts_latency_ms_check;
ALTER TABLE research_analyst_attempts
    ADD CONSTRAINT research_analyst_attempts_latency_ms_check
    CHECK (latency_ms IS NULL OR latency_ms >= 0);

INSERT INTO schema_migrations (version) VALUES ('0024_stale_analyst_attempt_recovery');

COMMIT;
