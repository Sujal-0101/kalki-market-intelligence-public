BEGIN;

CREATE TABLE research_prospective_outcome_plans (
    plan_id uuid PRIMARY KEY,
    publication_id uuid NOT NULL REFERENCES research_briefs(brief_id),
    horizon integer NOT NULL CHECK (horizon IN (1, 5, 20)),
    provider_name text NOT NULL CHECK (provider_name = 'twelve_data'),
    published_at timestamptz NOT NULL,
    asset_symbol text NOT NULL CHECK (asset_symbol ~ '^[A-Z0-9][A-Z0-9.-]{0,15}$'),
    asset_mic text NOT NULL CHECK (asset_mic ~ '^[A-Z0-9]{4}$'),
    benchmark_symbol text NOT NULL CHECK (benchmark_symbol ~ '^[A-Z0-9][A-Z0-9.-]{0,15}$'),
    benchmark_mic text NOT NULL CHECK (benchmark_mic ~ '^[A-Z0-9]{4}$'),
    calendar_name text NOT NULL CHECK (calendar_name IN ('XNYS', 'XTSE')),
    currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    publication_session_date date NOT NULL,
    reference_session_date date NOT NULL,
    reference_session_close_at timestamptz NOT NULL,
    target_session_date date NOT NULL,
    target_session_close_at timestamptz NOT NULL,
    origin text NOT NULL CHECK (origin IN ('GENUINE_FORWARD', 'RECONSTRUCTED')),
    enrolled_at timestamptz NOT NULL,
    methodology_version text NOT NULL CHECK (methodology_version = 'prospective-outcome-v1'),
    provider_terms_version text NOT NULL CHECK (provider_terms_version = '2026-01-01'),
    provider_use_mode text NOT NULL CHECK (provider_use_mode = 'internal_non_display'),
    record jsonb NOT NULL,
    UNIQUE (publication_id, horizon, provider_name),
    CHECK (asset_symbol <> benchmark_symbol OR asset_mic <> benchmark_mic),
    CHECK (reference_session_close_at >= published_at),
    CHECK (target_session_date > reference_session_date),
    CHECK (target_session_close_at > reference_session_close_at),
    CHECK (
        origin = CASE WHEN enrolled_at < target_session_close_at
            THEN 'GENUINE_FORWARD' ELSE 'RECONSTRUCTED' END
    )
);

CREATE TABLE research_prospective_outcome_jobs (
    plan_id uuid PRIMARY KEY REFERENCES research_prospective_outcome_plans(plan_id),
    status text NOT NULL CHECK (status IN (
        'pending', 'processing', 'retry_wait', 'completed', 'data_unavailable'
    )),
    attempts integer NOT NULL CHECK (attempts BETWEEN 0 AND 6),
    claimed_at timestamptz,
    next_attempt_at timestamptz,
    last_error_code text CHECK (
        last_error_code IS NULL OR length(last_error_code) BETWEEN 1 AND 255
    ),
    updated_at timestamptz NOT NULL,
    CHECK (
        (status = 'processing' AND claimed_at IS NOT NULL AND next_attempt_at IS NULL)
        OR (status IN ('pending', 'retry_wait') AND claimed_at IS NULL
            AND next_attempt_at IS NOT NULL)
        OR (status IN ('completed', 'data_unavailable') AND claimed_at IS NULL
            AND next_attempt_at IS NULL)
    )
);

CREATE INDEX research_prospective_outcome_jobs_due_idx
    ON research_prospective_outcome_jobs (status, next_attempt_at, plan_id);

CREATE TABLE research_prospective_outcome_attempts (
    attempt_id uuid PRIMARY KEY,
    plan_id uuid NOT NULL REFERENCES research_prospective_outcome_plans(plan_id),
    attempt_number integer NOT NULL CHECK (attempt_number BETWEEN 1 AND 6),
    started_at timestamptz NOT NULL,
    completed_at timestamptz NOT NULL,
    status text NOT NULL CHECK (status IN (
        'succeeded', 'retryable_failure', 'terminal_failure'
    )),
    error_code text CHECK (error_code IS NULL OR length(error_code) BETWEEN 1 AND 255),
    record jsonb NOT NULL,
    UNIQUE (plan_id, attempt_number),
    CHECK (completed_at >= started_at),
    CHECK ((status = 'succeeded') = (error_code IS NULL))
);

CREATE TABLE research_prospective_outcomes (
    outcome_id uuid PRIMARY KEY,
    plan_id uuid NOT NULL UNIQUE REFERENCES research_prospective_outcome_plans(plan_id),
    publication_id uuid NOT NULL REFERENCES research_briefs(brief_id),
    horizon integer NOT NULL CHECK (horizon IN (1, 5, 20)),
    provider_name text NOT NULL CHECK (provider_name = 'twelve_data'),
    status text NOT NULL CHECK (status IN ('completed', 'data_unavailable')),
    origin text NOT NULL CHECK (origin IN ('GENUINE_FORWARD', 'RECONSTRUCTED')),
    authority text NOT NULL CHECK (authority = 'SUPPORTING'),
    asset_reference_close numeric CHECK (asset_reference_close > 0),
    asset_target_close numeric CHECK (asset_target_close > 0),
    benchmark_reference_close numeric CHECK (benchmark_reference_close > 0),
    benchmark_target_close numeric CHECK (benchmark_target_close > 0),
    asset_return numeric,
    benchmark_return numeric,
    benchmark_relative_return numeric,
    calculation_version text NOT NULL CHECK (calculation_version = 'price-return-v1'),
    evaluated_at timestamptz NOT NULL,
    appended_at timestamptz NOT NULL,
    record jsonb NOT NULL,
    UNIQUE (publication_id, horizon, provider_name),
    CHECK (appended_at >= evaluated_at),
    CHECK (
        (status = 'completed'
            AND asset_reference_close IS NOT NULL AND asset_target_close IS NOT NULL
            AND benchmark_reference_close IS NOT NULL
            AND benchmark_target_close IS NOT NULL AND asset_return IS NOT NULL
            AND benchmark_return IS NOT NULL AND benchmark_relative_return IS NOT NULL)
        OR (status = 'data_unavailable' AND asset_return IS NULL
            AND benchmark_return IS NULL AND benchmark_relative_return IS NULL)
    )
);

CREATE FUNCTION validate_prospective_outcome_plan()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    immutable_publication_time timestamptz;
BEGIN
    SELECT published_at INTO immutable_publication_time
    FROM research_briefs WHERE brief_id = NEW.publication_id;
    IF NEW.record->>'publication_id' <> NEW.publication_id::text
        OR (NEW.record->>'horizon')::integer <> NEW.horizon
        OR NEW.record->>'provider_name' <> NEW.provider_name
        OR NEW.record->>'origin' <> NEW.origin
        OR NEW.record->>'asset_symbol' <> NEW.asset_symbol
        OR NEW.record->>'asset_mic' <> NEW.asset_mic
        OR NEW.record->>'benchmark_symbol' <> NEW.benchmark_symbol
        OR NEW.record->>'benchmark_mic' <> NEW.benchmark_mic
        OR NEW.record->>'calendar_name' <> NEW.calendar_name
        OR NEW.record->>'currency' <> NEW.currency
        OR NEW.record->>'methodology_version' <> NEW.methodology_version
        OR NEW.record->>'provider_terms_version' <> NEW.provider_terms_version
        OR NEW.record->>'provider_use_mode' <> NEW.provider_use_mode
        OR (NEW.record->>'published_at')::timestamptz <> NEW.published_at
        OR (NEW.record->>'enrolled_at')::timestamptz <> NEW.enrolled_at
        OR immutable_publication_time IS NULL
        OR immutable_publication_time <> NEW.published_at THEN
        RAISE EXCEPTION 'prospective outcome plan columns do not match record';
    END IF;
    RETURN NEW;
END
$$;

CREATE FUNCTION validate_prospective_outcome_attempt()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    plan_publication_id uuid;
    plan_horizon integer;
BEGIN
    SELECT publication_id, horizon INTO plan_publication_id, plan_horizon
    FROM research_prospective_outcome_plans WHERE plan_id = NEW.plan_id;
    IF NEW.record->>'attempt_id' <> NEW.attempt_id::text
        OR NEW.record->>'publication_id' <> plan_publication_id::text
        OR (NEW.record->>'horizon')::integer <> plan_horizon
        OR (NEW.record->>'attempt_number')::integer <> NEW.attempt_number
        OR NEW.record->>'status' <> NEW.status THEN
        RAISE EXCEPTION 'prospective outcome attempt columns do not match record';
    END IF;
    RETURN NEW;
END
$$;

CREATE FUNCTION validate_prospective_outcome_result()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    plan_origin text;
    attempt jsonb;
    retained_attempt_count integer;
BEGIN
    SELECT origin INTO plan_origin FROM research_prospective_outcome_plans
    WHERE plan_id = NEW.plan_id AND publication_id = NEW.publication_id
      AND horizon = NEW.horizon AND provider_name = NEW.provider_name;
    IF plan_origin IS NULL OR plan_origin <> NEW.origin
        OR NEW.record->>'outcome_id' <> NEW.outcome_id::text
        OR NEW.record->>'status' <> NEW.status
        OR NEW.record->>'authority' <> NEW.authority
        OR NEW.record->>'calculation_version' <> NEW.calculation_version
        OR (NEW.record->>'evaluated_at')::timestamptz <> NEW.evaluated_at
        OR (NEW.record->>'appended_at')::timestamptz <> NEW.appended_at
        OR (NEW.record#>>'{observations,asset_reference,close}')::numeric
            IS DISTINCT FROM NEW.asset_reference_close
        OR (NEW.record#>>'{observations,asset_target,close}')::numeric
            IS DISTINCT FROM NEW.asset_target_close
        OR (NEW.record#>>'{observations,benchmark_reference,close}')::numeric
            IS DISTINCT FROM NEW.benchmark_reference_close
        OR (NEW.record#>>'{observations,benchmark_target,close}')::numeric
            IS DISTINCT FROM NEW.benchmark_target_close
        OR (NEW.record->>'asset_return')::numeric IS DISTINCT FROM NEW.asset_return
        OR (NEW.record->>'benchmark_return')::numeric IS DISTINCT FROM NEW.benchmark_return
        OR (NEW.record->>'benchmark_relative_return')::numeric
            IS DISTINCT FROM NEW.benchmark_relative_return
        OR NEW.record->'plan'->>'publication_id' <> NEW.publication_id::text
        OR (NEW.record->'plan'->>'horizon')::integer <> NEW.horizon
        OR NEW.record->'plan'->>'provider_name' <> NEW.provider_name THEN
        RAISE EXCEPTION 'prospective outcome columns do not match record or plan';
    END IF;
    SELECT count(*) INTO retained_attempt_count
    FROM research_prospective_outcome_attempts WHERE plan_id = NEW.plan_id;
    IF jsonb_array_length(NEW.record->'attempts') <> retained_attempt_count THEN
        RAISE EXCEPTION 'prospective outcome omits retained attempts';
    END IF;
    FOR attempt IN SELECT value FROM jsonb_array_elements(NEW.record->'attempts') LOOP
        IF NOT EXISTS (
            SELECT 1 FROM research_prospective_outcome_attempts
            WHERE attempt_id = (attempt->>'attempt_id')::uuid
              AND plan_id = NEW.plan_id
              AND status = attempt->>'status'
        ) THEN
            RAISE EXCEPTION 'prospective outcome references an absent attempt';
        END IF;
    END LOOP;
    RETURN NEW;
END
$$;

CREATE TRIGGER research_prospective_outcome_plans_validate
    BEFORE INSERT ON research_prospective_outcome_plans
    FOR EACH ROW EXECUTE FUNCTION validate_prospective_outcome_plan();
CREATE TRIGGER research_prospective_outcome_attempts_validate
    BEFORE INSERT ON research_prospective_outcome_attempts
    FOR EACH ROW EXECUTE FUNCTION validate_prospective_outcome_attempt();
CREATE TRIGGER research_prospective_outcomes_validate
    BEFORE INSERT ON research_prospective_outcomes
    FOR EACH ROW EXECUTE FUNCTION validate_prospective_outcome_result();

CREATE TRIGGER research_prospective_outcome_plans_no_mutation
    BEFORE UPDATE OR DELETE ON research_prospective_outcome_plans
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_prospective_outcome_plans_no_truncate
    BEFORE TRUNCATE ON research_prospective_outcome_plans
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_prospective_outcome_attempts_no_mutation
    BEFORE UPDATE OR DELETE ON research_prospective_outcome_attempts
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_prospective_outcome_attempts_no_truncate
    BEFORE TRUNCATE ON research_prospective_outcome_attempts
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_prospective_outcomes_no_mutation
    BEFORE UPDATE OR DELETE ON research_prospective_outcomes
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_prospective_outcomes_no_truncate
    BEFORE TRUNCATE ON research_prospective_outcomes
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_prospective_outcome_jobs_no_delete
    BEFORE DELETE ON research_prospective_outcome_jobs
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_prospective_outcome_jobs_no_truncate
    BEFORE TRUNCATE ON research_prospective_outcome_jobs
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kalki_app') THEN
        EXECUTE 'GRANT SELECT, INSERT ON research_prospective_outcome_plans,
            research_prospective_outcome_attempts, research_prospective_outcomes TO kalki_app';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON research_prospective_outcome_jobs TO kalki_app';
    END IF;
END
$$;

INSERT INTO schema_migrations (version) VALUES ('0014_prospective_outcomes');

COMMIT;
