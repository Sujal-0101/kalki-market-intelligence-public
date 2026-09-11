BEGIN;

CREATE TABLE schema_migrations (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);

CREATE TABLE predictions (
    prediction_id uuid PRIMARY KEY,
    schema_version text NOT NULL CHECK (schema_version = '1.0.0'),
    research_subject_id uuid NOT NULL,
    instrument_id uuid NOT NULL,
    benchmark_instrument_id uuid NOT NULL,
    as_of_date date NOT NULL,
    knowledge_cutoff_at timestamptz NOT NULL,
    published_at timestamptz NOT NULL,
    horizon_days integer NOT NULL CHECK (horizon_days BETWEEN 30 AND 180),
    evaluation_due_on date NOT NULL,
    signal_fingerprint text NOT NULL CHECK (signal_fingerprint ~ '^[0-9a-f]{64}$'),
    record jsonb NOT NULL,
    CHECK (instrument_id <> benchmark_instrument_id),
    CHECK (as_of_date <= knowledge_cutoff_at::date),
    CHECK (published_at >= knowledge_cutoff_at),
    CHECK (evaluation_due_on = as_of_date + horizon_days)
);

CREATE TABLE prediction_corrections (
    correction_id uuid PRIMARY KEY,
    prediction_id uuid NOT NULL REFERENCES predictions(prediction_id),
    appended_at timestamptz NOT NULL,
    record jsonb NOT NULL
);

CREATE TABLE prediction_outcomes (
    outcome_id uuid PRIMARY KEY,
    prediction_id uuid NOT NULL REFERENCES predictions(prediction_id),
    schema_version text NOT NULL CHECK (schema_version = '1.0.0'),
    appended_at timestamptz NOT NULL,
    evaluated_at timestamptz NOT NULL,
    knowledge_cutoff_at timestamptz NOT NULL,
    security_status text NOT NULL CHECK (
        security_status IN ('active', 'delisted', 'acquired', 'bankrupt', 'renamed', 'data_unavailable')
    ),
    record jsonb NOT NULL,
    CHECK (knowledge_cutoff_at >= evaluated_at)
);

CREATE INDEX prediction_outcomes_prediction_appended_idx
    ON prediction_outcomes (prediction_id, appended_at);

CREATE FUNCTION reject_append_only_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION USING
        ERRCODE = '55000',
        MESSAGE = format('%s is append-only; %s is forbidden', TG_TABLE_NAME, TG_OP);
END;
$$;

CREATE TRIGGER predictions_no_update_delete
    BEFORE UPDATE OR DELETE ON predictions
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER predictions_no_truncate
    BEFORE TRUNCATE ON predictions
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();

CREATE TRIGGER corrections_no_update_delete
    BEFORE UPDATE OR DELETE ON prediction_corrections
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER corrections_no_truncate
    BEFORE TRUNCATE ON prediction_corrections
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();

CREATE TRIGGER outcomes_no_update_delete
    BEFORE UPDATE OR DELETE ON prediction_outcomes
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER outcomes_no_truncate
    BEFORE TRUNCATE ON prediction_outcomes
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();

INSERT INTO schema_migrations (version) VALUES ('0001_prediction_outcomes');

COMMIT;
