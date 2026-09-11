BEGIN;

CREATE TABLE research_human_leads (
    lead_id uuid PRIMARY KEY,
    discord_message_id text NOT NULL UNIQUE CHECK (discord_message_id ~ '^[0-9]{17,20}$'),
    submitter_user_id text NOT NULL CHECK (submitter_user_id ~ '^[0-9]{17,20}$'),
    channel_id text NOT NULL CHECK (channel_id ~ '^[0-9]{17,20}$'),
    submitted_at timestamptz NOT NULL,
    ticker text CHECK (ticker IS NULL OR ticker ~ '^[A-Z0-9][A-Z0-9.\-]{0,14}$'),
    cik text CHECK (cik IS NULL OR cik ~ '^[0-9]{1,10}$'),
    hypothesis text NOT NULL CHECK (length(hypothesis) BETWEEN 1 AND 2000),
    urls text[] NOT NULL DEFAULT '{}',
    notes text CHECK (notes IS NULL OR length(notes) BETWEEN 1 AND 2000),
    original_submission_sha256 text NOT NULL CHECK (original_submission_sha256 ~ '^[0-9a-f]{64}$'),
    dedupe_key text NOT NULL CHECK (dedupe_key ~ '^[0-9a-f]{64}$'),
    origin text NOT NULL DEFAULT 'human' CHECK (origin = 'human'),
    status text NOT NULL DEFAULT 'received' CHECK (status IN (
        'received', 'validating', 'duplicate', 'queued', 'retained', 'analyzing',
        'completed', 'inconclusive', 'rejected', 'failed', 'cancelled'
    )),
    priority text NOT NULL DEFAULT 'normal' CHECK (priority IN ('high', 'normal', 'low')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 3),
    next_attempt_at timestamptz,
    result jsonb,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    CHECK (cardinality(urls) <= 8),
    CHECK (updated_at >= created_at)
);

CREATE INDEX research_human_leads_queue_idx
    ON research_human_leads (status, priority, submitted_at, lead_id);
CREATE INDEX research_human_leads_dedupe_idx
    ON research_human_leads (dedupe_key, status);

CREATE TABLE research_human_lead_events (
    event_id uuid PRIMARY KEY,
    lead_id uuid NOT NULL REFERENCES research_human_leads(lead_id),
    occurred_at timestamptz NOT NULL,
    status text NOT NULL CHECK (status IN (
        'received', 'validating', 'duplicate', 'queued', 'retained', 'analyzing',
        'completed', 'inconclusive', 'rejected', 'failed', 'cancelled'
    )),
    detail text NOT NULL CHECK (length(detail) BETWEEN 1 AND 500),
    record jsonb NOT NULL
);

CREATE INDEX research_human_lead_events_lead_idx
    ON research_human_lead_events (lead_id, occurred_at, event_id);

CREATE TRIGGER research_human_lead_events_no_update_delete
    BEFORE UPDATE OR DELETE ON research_human_lead_events
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_human_lead_events_no_truncate
    BEFORE TRUNCATE ON research_human_lead_events
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();

INSERT INTO schema_migrations (version) VALUES ('0007_human_research_leads');

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kalki_app') THEN
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON research_human_leads TO kalki_app';
        EXECUTE 'GRANT SELECT, INSERT ON research_human_lead_events TO kalki_app';
    END IF;
END
$$;

COMMIT;
