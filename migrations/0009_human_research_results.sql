BEGIN;
CREATE TABLE research_human_results (
    result_id uuid PRIMARY KEY,
    lead_id uuid NOT NULL UNIQUE REFERENCES research_human_leads(lead_id),
    record jsonb NOT NULL,
    created_at timestamptz NOT NULL
);
CREATE TABLE research_human_result_deliveries (
    result_id uuid PRIMARY KEY REFERENCES research_human_results(result_id),
    channel_id text NOT NULL CHECK (channel_id ~ '^[0-9]{17,20}$'),
    discord_message_id text CHECK (discord_message_id IS NULL OR discord_message_id ~ '^[0-9]{17,20}$'),
    status text NOT NULL CHECK (status IN ('pending','delivered','failed')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_attempt_at timestamptz,
    updated_at timestamptz NOT NULL
);
CREATE TRIGGER research_human_results_no_update_delete BEFORE UPDATE OR DELETE ON research_human_results FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_human_results_no_truncate BEFORE TRUNCATE ON research_human_results FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();
INSERT INTO schema_migrations (version) VALUES ('0009_human_research_results');
DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kalki_app') THEN EXECUTE 'GRANT SELECT, INSERT ON research_human_results TO kalki_app'; EXECUTE 'GRANT SELECT, INSERT, UPDATE ON research_human_result_deliveries TO kalki_app'; END IF; END $$;
COMMIT;
