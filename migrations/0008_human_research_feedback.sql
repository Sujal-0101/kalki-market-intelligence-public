BEGIN;

CREATE TABLE research_human_feedback (
    feedback_id uuid PRIMARY KEY,
    research_reference text NOT NULL CHECK (length(research_reference) BETWEEN 1 AND 120),
    submitter_user_id text NOT NULL CHECK (submitter_user_id ~ '^[0-9]{17,20}$'),
    submitted_at timestamptz NOT NULL,
    feedback_type text NOT NULL CHECK (feedback_type IN ('useful','not_useful','false_positive','missed_evidence','incorrect_fact','too_late','other')),
    note text CHECK (note IS NULL OR length(note) BETWEEN 1 AND 1000),
    version text NOT NULL CHECK (length(version) BETWEEN 1 AND 40),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (research_reference, submitter_user_id, feedback_type)
);
CREATE INDEX research_human_feedback_reference_idx ON research_human_feedback (research_reference, submitted_at);
CREATE TRIGGER research_human_feedback_no_update_delete BEFORE UPDATE OR DELETE ON research_human_feedback FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_human_feedback_no_truncate BEFORE TRUNCATE ON research_human_feedback FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();
INSERT INTO schema_migrations (version) VALUES ('0008_human_research_feedback');
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kalki_app') THEN
  EXECUTE 'GRANT SELECT, INSERT ON research_human_feedback TO kalki_app';
 END IF;
END $$;
COMMIT;
