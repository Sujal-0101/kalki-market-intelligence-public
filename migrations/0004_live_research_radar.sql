BEGIN;

CREATE TABLE research_candidates (
    accession_number text PRIMARY KEY CHECK (accession_number ~ '^\d{10}-\d{2}-\d{6}$'),
    cik text NOT NULL CHECK (cik ~ '^\d{1,10}$'),
    company_name text NOT NULL CHECK (length(company_name) BETWEEN 1 AND 255),
    ticker text CHECK (ticker IS NULL OR ticker ~ '^[A-Z0-9][A-Z0-9.\-]{0,14}$'),
    exchange text CHECK (exchange IS NULL OR length(exchange) BETWEEN 1 AND 255),
    filing_form text NOT NULL CHECK (length(filing_form) BETWEEN 1 AND 32),
    filed_at timestamptz NOT NULL,
    source_url text NOT NULL CHECK (source_url LIKE 'https://www.sec.gov/Archives/edgar/data/%'),
    discovered_at timestamptz NOT NULL,
    status text NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'processing', 'published', 'skipped', 'retry_wait', 'failed')
    ),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 6),
    next_attempt_at timestamptz,
    last_error_code text CHECK (last_error_code IS NULL OR length(last_error_code) BETWEEN 1 AND 255),
    updated_at timestamptz NOT NULL,
    CHECK (discovered_at >= filed_at)
);

CREATE INDEX research_candidates_work_idx
    ON research_candidates (status, next_attempt_at, filed_at, accession_number);

CREATE TABLE research_briefs (
    brief_id uuid PRIMARY KEY,
    schema_version text NOT NULL CHECK (schema_version = '1.0.0'),
    accession_number text NOT NULL UNIQUE REFERENCES research_candidates(accession_number),
    ticker text CHECK (ticker IS NULL OR ticker ~ '^[A-Z0-9][A-Z0-9.\-]{0,14}$'),
    company_name text NOT NULL CHECK (length(company_name) BETWEEN 1 AND 255),
    classification text NOT NULL CHECK (classification IN ('opportunity', 'mixed', 'risk', 'watch')),
    attention_points integer NOT NULL CHECK (attention_points BETWEEN 0 AND 100),
    risk_points integer NOT NULL CHECK (risk_points BETWEEN 0 AND 100),
    evidence_strength_points integer NOT NULL CHECK (evidence_strength_points BETWEEN 0 AND 100),
    filed_at timestamptz NOT NULL,
    retrieved_at timestamptz NOT NULL,
    published_at timestamptz NOT NULL,
    source_document_sha256 text NOT NULL CHECK (source_document_sha256 ~ '^[0-9a-f]{64}$'),
    record jsonb NOT NULL,
    CHECK (retrieved_at >= filed_at),
    CHECK (published_at >= retrieved_at)
);

CREATE INDEX research_briefs_publication_order_idx
    ON research_briefs (published_at DESC, brief_id DESC);
CREATE INDEX research_briefs_classification_order_idx
    ON research_briefs (classification, published_at DESC, brief_id DESC);

CREATE TABLE research_worker_status (
    worker_name text PRIMARY KEY CHECK (worker_name = 'filing-radar'),
    state text NOT NULL CHECK (
        state IN ('starting', 'running', 'idle', 'degraded', 'waiting_for_configuration')
    ),
    heartbeat_at timestamptz NOT NULL,
    last_success_at timestamptz,
    next_run_at timestamptz,
    last_error_code text CHECK (last_error_code IS NULL OR length(last_error_code) BETWEEN 1 AND 255),
    discovered_count integer NOT NULL CHECK (discovered_count >= 0),
    pending_count integer NOT NULL CHECK (pending_count >= 0),
    published_count integer NOT NULL CHECK (published_count >= 0),
    discord_enabled boolean NOT NULL,
    model_name text NOT NULL CHECK (length(model_name) BETWEEN 1 AND 255),
    source_name text NOT NULL CHECK (source_name = 'SEC EDGAR daily master index')
);

CREATE TABLE research_runs (
    run_id uuid PRIMARY KEY,
    started_at timestamptz NOT NULL,
    completed_at timestamptz NOT NULL,
    state text NOT NULL CHECK (state IN ('completed', 'degraded', 'failed')),
    record jsonb NOT NULL,
    CHECK (completed_at >= started_at)
);

CREATE INDEX research_runs_completed_idx ON research_runs (completed_at DESC, run_id DESC);

CREATE TABLE research_notification_deliveries (
    delivery_id uuid PRIMARY KEY,
    notification_key text NOT NULL CHECK (notification_key ~ '^[0-9a-f]{64}$'),
    brief_id uuid NOT NULL REFERENCES research_briefs(brief_id),
    completed_at timestamptz NOT NULL,
    status text NOT NULL CHECK (
        status IN ('sent', 'duplicate', 'disabled', 'rejected', 'rate_limited', 'delivery_uncertain')
    ),
    record jsonb NOT NULL
);

CREATE UNIQUE INDEX research_notification_terminal_key_idx
    ON research_notification_deliveries (notification_key)
    WHERE status IN ('sent', 'delivery_uncertain');

CREATE TRIGGER research_briefs_no_update_delete
    BEFORE UPDATE OR DELETE ON research_briefs
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_briefs_no_truncate
    BEFORE TRUNCATE ON research_briefs
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();

CREATE TRIGGER research_runs_no_update_delete
    BEFORE UPDATE OR DELETE ON research_runs
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_runs_no_truncate
    BEFORE TRUNCATE ON research_runs
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();

CREATE TRIGGER research_notification_deliveries_no_update_delete
    BEFORE UPDATE OR DELETE ON research_notification_deliveries
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_notification_deliveries_no_truncate
    BEFORE TRUNCATE ON research_notification_deliveries
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();

INSERT INTO schema_migrations (version) VALUES ('0004_live_research_radar');

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kalki_app') THEN
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON research_candidates TO kalki_app';
        EXECUTE 'GRANT SELECT, INSERT ON research_briefs, research_runs, research_notification_deliveries TO kalki_app';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON research_worker_status TO kalki_app';
    END IF;
END
$$;

COMMIT;
