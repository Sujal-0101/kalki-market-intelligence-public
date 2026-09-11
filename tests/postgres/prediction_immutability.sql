\set ON_ERROR_STOP on

INSERT INTO predictions (
    prediction_id, schema_version, research_subject_id, instrument_id,
    benchmark_instrument_id, as_of_date, knowledge_cutoff_at, published_at,
    horizon_days, evaluation_due_on, signal_fingerprint, record
) VALUES (
    '10000000-0000-4000-8000-000000000001', '1.0.0',
    '20000000-0000-4000-8000-000000000001',
    '30000000-0000-4000-8000-000000000001',
    '40000000-0000-4000-8000-000000000001',
    DATE '2026-01-01', TIMESTAMPTZ '2026-01-01 21:00:00+00',
    TIMESTAMPTZ '2026-01-01 22:00:00+00', 90, DATE '2026-04-01',
    repeat('a', 64), '{"synthetic": true}'::jsonb
);

INSERT INTO prediction_outcomes (
    outcome_id, prediction_id, schema_version, appended_at, evaluated_at,
    knowledge_cutoff_at, security_status, record
) VALUES (
    '50000000-0000-4000-8000-000000000001',
    '10000000-0000-4000-8000-000000000001', '1.0.0',
    TIMESTAMPTZ '2026-04-02 21:00:00+00',
    TIMESTAMPTZ '2026-04-02 20:00:00+00',
    TIMESTAMPTZ '2026-04-02 21:00:00+00', 'delisted',
    '{"synthetic": true}'::jsonb
);

DO $$
BEGIN
    BEGIN
        UPDATE predictions SET record = '{}'::jsonb
        WHERE prediction_id = '10000000-0000-4000-8000-000000000001';
        RAISE EXCEPTION 'prediction update unexpectedly succeeded';
    EXCEPTION WHEN SQLSTATE '55000' THEN
        NULL;
    END;
    BEGIN
        DELETE FROM predictions
        WHERE prediction_id = '10000000-0000-4000-8000-000000000001';
        RAISE EXCEPTION 'prediction delete unexpectedly succeeded';
    EXCEPTION WHEN SQLSTATE '55000' THEN
        NULL;
    END;
END;
$$;

SELECT CASE WHEN count(*) = 1 THEN 'prediction append/immutability: passed'
    ELSE pg_catalog.set_config('invalid', 'count', false) END
FROM predictions;
SELECT CASE WHEN count(*) = 1 THEN 'delisted outcome append: passed'
    ELSE pg_catalog.set_config('invalid', 'count', false) END
FROM prediction_outcomes WHERE security_status = 'delisted';
