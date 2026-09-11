BEGIN;

CREATE TABLE research_funnel_telemetry_state (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    started_at timestamptz NOT NULL,
    schema_version text NOT NULL CHECK (schema_version = '1.0.0')
);

INSERT INTO research_funnel_telemetry_state (started_at, schema_version)
VALUES (clock_timestamp(), '1.0.0');

CREATE TABLE research_pipeline_events (
    event_id uuid PRIMARY KEY,
    occurred_at timestamptz NOT NULL,
    stage text NOT NULL CHECK (stage IN (
        'sec_poll_attempted', 'candidate_processing', 'candidate_retrieved',
        'candidate_parsed', 'companyfacts_normalized', 'candidate_retry_wait',
        'candidate_skipped', 'candidate_failed', 'tier_retained',
        'tier_escalated', 'stale_recovered', 'human_duplicate'
    )),
    run_id uuid,
    accession_number text REFERENCES research_candidates(accession_number),
    count integer NOT NULL DEFAULT 1 CHECK (count BETWEEN 1 AND 10000),
    failure_category text CHECK (
        failure_category IS NULL OR failure_category IN (
            'sec_retrieval', 'filing_parse', 'companyfacts_normalization',
            'deterministic_processing', 'analyst', 'verifier', 'persistence', 'other'
        )
    ),
    schema_version text NOT NULL CHECK (schema_version = '1.0.0'),
    CHECK (
        ((stage IN ('candidate_processing', 'candidate_retrieved', 'candidate_parsed',
                    'companyfacts_normalized', 'candidate_retry_wait',
                    'candidate_skipped', 'candidate_failed', 'tier_retained',
                    'tier_escalated'))
            = (accession_number IS NOT NULL))
    ),
    CHECK (
        ((stage IN ('candidate_retry_wait', 'candidate_failed'))
            = (failure_category IS NOT NULL))
    ),
    CHECK (stage <> 'sec_poll_attempted' OR run_id IS NOT NULL)
);

CREATE INDEX research_pipeline_events_window_idx
    ON research_pipeline_events (occurred_at DESC, stage);
CREATE INDEX research_pipeline_events_run_idx
    ON research_pipeline_events (run_id) WHERE run_id IS NOT NULL;

CREATE TABLE research_detector_receipts (
    receipt_id uuid PRIMARY KEY,
    accession_number text NOT NULL REFERENCES research_candidates(accession_number),
    observed_at timestamptz NOT NULL,
    detector_name text NOT NULL CHECK (detector_name IN (
        'share_growth', 'liquidity', 'going_concern', 'reverse_split',
        'filing_diff', 'xbrl_numeric', 'source_authority', 'convergence'
    )),
    invoked boolean NOT NULL,
    status text NOT NULL CHECK (status IN (
        'positive', 'negative', 'unknown', 'not_assessed', 'insufficient_evidence'
    )),
    contributed_to_escalation boolean NOT NULL,
    schema_version text NOT NULL CHECK (schema_version = '1.0.0'),
    UNIQUE (accession_number, detector_name),
    CHECK (invoked OR status = 'not_assessed'),
    CHECK (NOT contributed_to_escalation OR (invoked AND status = 'positive'))
);

CREATE INDEX research_detector_receipts_window_idx
    ON research_detector_receipts (observed_at DESC, detector_name, status);

CREATE INDEX research_runs_started_idx ON research_runs (started_at DESC, run_id);
CREATE INDEX research_candidates_discovered_idx
    ON research_candidates (discovered_at DESC, accession_number);
CREATE INDEX research_verification_dispositions_decided_idx
    ON research_verification_dispositions (decided_at DESC, disposition);
CREATE INDEX research_notification_deliveries_completed_idx
    ON research_notification_deliveries (completed_at DESC, status);
CREATE INDEX research_human_leads_submitted_idx
    ON research_human_leads (submitted_at DESC, lead_id);
CREATE INDEX research_human_results_created_idx
    ON research_human_results (created_at DESC, result_id);
CREATE INDEX research_human_result_deliveries_updated_idx
    ON research_human_result_deliveries (updated_at DESC, status);

CREATE TRIGGER research_funnel_telemetry_state_no_update_delete
    BEFORE UPDATE OR DELETE ON research_funnel_telemetry_state
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_funnel_telemetry_state_no_truncate
    BEFORE TRUNCATE ON research_funnel_telemetry_state
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();

CREATE TRIGGER research_pipeline_events_no_update_delete
    BEFORE UPDATE OR DELETE ON research_pipeline_events
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_pipeline_events_no_truncate
    BEFORE TRUNCATE ON research_pipeline_events
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_detector_receipts_no_update_delete
    BEFORE UPDATE OR DELETE ON research_detector_receipts
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_detector_receipts_no_truncate
    BEFORE TRUNCATE ON research_detector_receipts
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();

INSERT INTO schema_migrations (version) VALUES ('0011_funnel_telemetry');

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kalki_app') THEN
        EXECUTE 'GRANT SELECT ON research_funnel_telemetry_state TO kalki_app';
        EXECUTE 'GRANT SELECT, INSERT ON research_pipeline_events, research_detector_receipts TO kalki_app';
    END IF;
END
$$;

COMMIT;
