BEGIN;

-- Phase 44 hardens the original Phase 37 ledger in place.  Production has no
-- outcome rows, and this migration performs no backfill or history mutation.
ALTER TABLE research_prospective_outcome_plans
    ADD CONSTRAINT research_prospective_outcome_plans_enrollment_after_publication
    CHECK (enrolled_at >= published_at) NOT VALID;
ALTER TABLE research_prospective_outcome_plans
    VALIDATE CONSTRAINT research_prospective_outcome_plans_enrollment_after_publication;

CREATE FUNCTION outcome_decimal34(value numeric)
RETURNS numeric
LANGUAGE plpgsql
IMMUTABLE
STRICT
AS $$
DECLARE
    magnitude integer;
    places integer;
    scaled numeric;
    integral numeric;
    fraction numeric;
BEGIN
    IF value = 0 THEN
        RETURN 0;
    END IF;
    magnitude := floor(log(10::numeric, abs(value)))::integer;
    places := 33 - magnitude;
    scaled := abs(value) * (('1e' || places::text)::numeric);
    integral := trunc(scaled);
    fraction := scaled - integral;
    IF fraction > 0.5 OR (fraction = 0.5 AND mod(integral, 2) = 1) THEN
        integral := integral + 1;
    END IF;
    RETURN sign(value) * integral * (('1e' || (-places)::text)::numeric);
END
$$;

CREATE FUNCTION outcome_price_return_decimal34(reference_close numeric, target_close numeric)
RETURNS numeric
LANGUAGE sql
IMMUTABLE
STRICT
AS $$
    SELECT outcome_decimal34(
        (
            outcome_decimal34(target_close - reference_close) * 1e100::numeric
            / reference_close
        ) * 1e-100::numeric
    )
$$;

CREATE FUNCTION validate_prospective_outcome_bar(
    bar jsonb,
    expected_symbol text,
    expected_mic text,
    expected_session date,
    expected_currency text,
    expected_provider text,
    evaluation_time timestamptz
)
RETURNS void
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
    bar_keys text[];
BEGIN
    IF bar IS NULL OR bar = 'null'::jsonb THEN
        RETURN;
    END IF;
    SELECT array_agg(key ORDER BY key) INTO bar_keys
    FROM jsonb_object_keys(bar) AS key;
    IF bar_keys IS DISTINCT FROM ARRAY[
            'adjustment', 'authority', 'available_at', 'close', 'currency',
            'high', 'low', 'mic', 'open', 'provider_mic', 'provider_name',
            'retrieved_at', 'session_date', 'source_content_sha256',
            'source_record_id', 'symbol', 'volume'
        ]::text[]
        OR bar->>'symbol' IS DISTINCT FROM expected_symbol
        OR bar->>'mic' IS DISTINCT FROM expected_mic
        OR (bar->>'session_date')::date IS DISTINCT FROM expected_session
        OR bar->>'currency' IS DISTINCT FROM expected_currency
        OR bar->>'provider_name' IS DISTINCT FROM expected_provider
        OR bar->>'authority' IS DISTINCT FROM 'SUPPORTING'
        OR bar->>'adjustment' IS DISTINCT FROM 'splits'
        OR bar->>'provider_mic' !~ '^[A-Z0-9]{4}$'
        OR bar->>'source_content_sha256' !~ '^[0-9a-f]{64}$'
        OR length(btrim(bar->>'source_record_id')) NOT BETWEEN 1 AND 255
        OR (bar->>'open')::numeric <= 0
        OR (bar->>'high')::numeric <= 0
        OR (bar->>'low')::numeric <= 0
        OR (bar->>'close')::numeric <= 0
        OR (bar->>'high')::numeric < greatest(
            (bar->>'open')::numeric, (bar->>'low')::numeric, (bar->>'close')::numeric
        )
        OR (bar->>'low')::numeric > least(
            (bar->>'open')::numeric, (bar->>'high')::numeric, (bar->>'close')::numeric
        )
        OR (bar->>'volume')::numeric < 0
        OR (bar->>'volume')::numeric <> trunc((bar->>'volume')::numeric)
        OR (bar->>'available_at')::timestamptz > (bar->>'retrieved_at')::timestamptz
        OR (bar->>'retrieved_at')::timestamptz > evaluation_time THEN
        RAISE EXCEPTION 'prospective outcome bar violates closed identity or knowledge time';
    END IF;
END
$$;

CREATE OR REPLACE FUNCTION validate_prospective_outcome_plan()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    immutable_publication_time timestamptz;
    plan_keys text[];
BEGIN
    SELECT published_at INTO immutable_publication_time
    FROM research_briefs WHERE brief_id = NEW.publication_id;
    SELECT array_agg(key ORDER BY key) INTO plan_keys
    FROM jsonb_object_keys(NEW.record) AS key;
    IF plan_keys IS DISTINCT FROM ARRAY[
            'asset_mic', 'asset_symbol', 'benchmark_mic', 'benchmark_symbol',
            'calendar_name', 'currency', 'enrolled_at', 'horizon',
            'methodology_version', 'origin', 'provider_name', 'provider_terms_version',
            'provider_use_mode', 'publication_id', 'publication_session_date',
            'published_at', 'reference_session_close_at', 'reference_session_date',
            'target_session_close_at', 'target_session_date'
        ]::text[]
        OR NEW.record->>'publication_id' IS DISTINCT FROM NEW.publication_id::text
        OR (NEW.record->>'horizon')::integer IS DISTINCT FROM NEW.horizon
        OR NEW.record->>'provider_name' IS DISTINCT FROM NEW.provider_name
        OR NEW.record->>'origin' IS DISTINCT FROM NEW.origin
        OR NEW.record->>'asset_symbol' IS DISTINCT FROM NEW.asset_symbol
        OR NEW.record->>'asset_mic' IS DISTINCT FROM NEW.asset_mic
        OR NEW.record->>'benchmark_symbol' IS DISTINCT FROM NEW.benchmark_symbol
        OR NEW.record->>'benchmark_mic' IS DISTINCT FROM NEW.benchmark_mic
        OR NEW.record->>'calendar_name' IS DISTINCT FROM NEW.calendar_name
        OR NEW.record->>'currency' IS DISTINCT FROM NEW.currency
        OR NEW.record->>'methodology_version' IS DISTINCT FROM NEW.methodology_version
        OR NEW.record->>'provider_terms_version' IS DISTINCT FROM NEW.provider_terms_version
        OR NEW.record->>'provider_use_mode' IS DISTINCT FROM NEW.provider_use_mode
        OR (NEW.record->>'published_at')::timestamptz IS DISTINCT FROM NEW.published_at
        OR (NEW.record->>'enrolled_at')::timestamptz IS DISTINCT FROM NEW.enrolled_at
        OR (NEW.record->>'publication_session_date')::date
            IS DISTINCT FROM NEW.publication_session_date
        OR (NEW.record->>'reference_session_date')::date
            IS DISTINCT FROM NEW.reference_session_date
        OR (NEW.record->>'reference_session_close_at')::timestamptz
            IS DISTINCT FROM NEW.reference_session_close_at
        OR (NEW.record->>'target_session_date')::date
            IS DISTINCT FROM NEW.target_session_date
        OR (NEW.record->>'target_session_close_at')::timestamptz
            IS DISTINCT FROM NEW.target_session_close_at
        OR NEW.enrolled_at < NEW.published_at
        OR immutable_publication_time IS NULL
        OR immutable_publication_time IS DISTINCT FROM NEW.published_at THEN
        RAISE EXCEPTION 'prospective outcome plan violates closed publication enrollment';
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION validate_prospective_outcome_attempt()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    plan_publication_id uuid;
    plan_horizon integer;
    plan_provider text;
    terminal_evaluated_at timestamptz;
    attempt_keys text[];
BEGIN
    SELECT publication_id, horizon, provider_name
      INTO plan_publication_id, plan_horizon, plan_provider
    FROM research_prospective_outcome_plans WHERE plan_id = NEW.plan_id;
    SELECT evaluated_at INTO terminal_evaluated_at
    FROM research_prospective_outcomes WHERE plan_id = NEW.plan_id;
    SELECT array_agg(key ORDER BY key) INTO attempt_keys
    FROM jsonb_object_keys(NEW.record) AS key;
    IF attempt_keys IS DISTINCT FROM ARRAY[
            'attempt_id', 'attempt_number', 'completed_at', 'error_code', 'horizon',
            'provider_name', 'publication_id', 'response_row_count', 'response_sha256',
            'started_at', 'status'
        ]::text[]
        OR plan_publication_id IS NULL
        OR NEW.record->>'attempt_id' IS DISTINCT FROM NEW.attempt_id::text
        OR NEW.record->>'publication_id' IS DISTINCT FROM plan_publication_id::text
        OR (NEW.record->>'horizon')::integer IS DISTINCT FROM plan_horizon
        OR NEW.record->>'provider_name' IS DISTINCT FROM plan_provider
        OR (NEW.record->>'attempt_number')::integer IS DISTINCT FROM NEW.attempt_number
        OR (NEW.record->>'started_at')::timestamptz IS DISTINCT FROM NEW.started_at
        OR (NEW.record->>'completed_at')::timestamptz IS DISTINCT FROM NEW.completed_at
        OR NEW.record->>'status' IS DISTINCT FROM NEW.status
        OR NEW.record->>'error_code' IS DISTINCT FROM NEW.error_code
        OR jsonb_array_length(NEW.record->'response_sha256') > 2
        OR (NEW.record->>'response_row_count')::integer NOT BETWEEN 0 AND 10000
        OR terminal_evaluated_at IS NOT NULL
        OR NEW.completed_at > coalesce(terminal_evaluated_at, 'infinity'::timestamptz) THEN
        RAISE EXCEPTION 'prospective outcome attempt violates closed scope or evaluation time';
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION validate_prospective_outcome_result()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    stored_plan jsonb;
    attempt jsonb;
    retained_attempt_count integer;
    expected_asset_return numeric;
    expected_benchmark_return numeric;
    expected_relative_return numeric;
    observed_hashes text[];
    retained_hashes text[];
    last_attempt_status text;
    top_keys text[];
    observation_keys text[];
BEGIN
    SELECT record INTO stored_plan FROM research_prospective_outcome_plans
    WHERE plan_id = NEW.plan_id AND publication_id = NEW.publication_id
      AND horizon = NEW.horizon AND provider_name = NEW.provider_name
      AND origin = NEW.origin;
    SELECT array_agg(key ORDER BY key) INTO top_keys
    FROM jsonb_object_keys(NEW.record) AS key;
    SELECT array_agg(key ORDER BY key) INTO observation_keys
    FROM jsonb_object_keys(NEW.record->'observations') AS key;
    IF stored_plan IS NULL
        OR top_keys IS DISTINCT FROM ARRAY[
            'appended_at', 'asset_return', 'attempts', 'authority', 'benchmark_relative_return',
            'benchmark_return', 'calculation_version', 'evaluated_at', 'limitations',
            'observation_hashes', 'observations', 'outcome_id', 'plan', 'schema_version',
            'status'
        ]::text[]
        OR observation_keys IS DISTINCT FROM ARRAY[
            'asset_reference', 'asset_target', 'benchmark_reference', 'benchmark_target'
        ]::text[]
        OR NEW.record->'plan' IS DISTINCT FROM stored_plan
        OR NEW.record->>'outcome_id' IS DISTINCT FROM NEW.outcome_id::text
        OR NEW.record->>'status' IS DISTINCT FROM NEW.status
        OR NEW.record->>'authority' IS DISTINCT FROM NEW.authority
        OR NEW.record->>'calculation_version' IS DISTINCT FROM NEW.calculation_version
        OR NEW.record->>'schema_version' IS DISTINCT FROM '1.0.0'
        OR (NEW.record->>'evaluated_at')::timestamptz IS DISTINCT FROM NEW.evaluated_at
        OR (NEW.record->>'appended_at')::timestamptz IS DISTINCT FROM NEW.appended_at
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
        OR NEW.evaluated_at < (stored_plan->>'target_session_close_at')::timestamptz THEN
        RAISE EXCEPTION 'prospective outcome columns do not match the closed plan and record';
    END IF;

    PERFORM validate_prospective_outcome_bar(
        NEW.record#>'{observations,asset_reference}', stored_plan->>'asset_symbol',
        stored_plan->>'asset_mic', (stored_plan->>'reference_session_date')::date,
        stored_plan->>'currency', stored_plan->>'provider_name', NEW.evaluated_at
    );
    PERFORM validate_prospective_outcome_bar(
        NEW.record#>'{observations,asset_target}', stored_plan->>'asset_symbol',
        stored_plan->>'asset_mic', (stored_plan->>'target_session_date')::date,
        stored_plan->>'currency', stored_plan->>'provider_name', NEW.evaluated_at
    );
    PERFORM validate_prospective_outcome_bar(
        NEW.record#>'{observations,benchmark_reference}', stored_plan->>'benchmark_symbol',
        stored_plan->>'benchmark_mic', (stored_plan->>'reference_session_date')::date,
        stored_plan->>'currency', stored_plan->>'provider_name', NEW.evaluated_at
    );
    PERFORM validate_prospective_outcome_bar(
        NEW.record#>'{observations,benchmark_target}', stored_plan->>'benchmark_symbol',
        stored_plan->>'benchmark_mic', (stored_plan->>'target_session_date')::date,
        stored_plan->>'currency', stored_plan->>'provider_name', NEW.evaluated_at
    );

    SELECT array_agg(value ORDER BY position) INTO observed_hashes
    FROM jsonb_array_elements_text(NEW.record->'observation_hashes')
        WITH ORDINALITY AS item(value, position);
    SELECT array_agg(hash ORDER BY hash) INTO retained_hashes
    FROM (
        SELECT value->>'source_content_sha256' AS hash
        FROM jsonb_each(NEW.record->'observations')
        WHERE value <> 'null'::jsonb
    ) AS hashes;
    IF coalesce(observed_hashes, ARRAY[]::text[])
            IS DISTINCT FROM coalesce(retained_hashes, ARRAY[]::text[])
        OR cardinality(coalesce(observed_hashes, ARRAY[]::text[]))
            <> cardinality(ARRAY(SELECT DISTINCT unnest(coalesce(observed_hashes, ARRAY[]::text[]))))
        OR cardinality(coalesce(observed_hashes, ARRAY[]::text[])) > 4 THEN
        RAISE EXCEPTION 'prospective outcome observation hashes do not reconcile';
    END IF;

    IF NEW.status = 'data_unavailable' THEN
        IF jsonb_array_length(NEW.record->'limitations') = 0
            OR NEW.asset_return IS NOT NULL
            OR NEW.benchmark_return IS NOT NULL
            OR NEW.benchmark_relative_return IS NOT NULL THEN
            RAISE EXCEPTION 'unavailable prospective outcome requires a limitation and no return';
        END IF;
    ELSE
        IF jsonb_array_length(NEW.record->'limitations') <> 0
            OR NEW.record#>'{observations,asset_reference}' = 'null'::jsonb
            OR NEW.record#>'{observations,asset_target}' = 'null'::jsonb
            OR NEW.record#>'{observations,benchmark_reference}' = 'null'::jsonb
            OR NEW.record#>'{observations,benchmark_target}' = 'null'::jsonb THEN
            RAISE EXCEPTION 'completed prospective outcome requires four bars and no limitation';
        END IF;
        expected_asset_return := outcome_price_return_decimal34(
            (NEW.record#>>'{observations,asset_reference,close}')::numeric,
            (NEW.record#>>'{observations,asset_target,close}')::numeric
        );
        expected_benchmark_return := outcome_price_return_decimal34(
            (NEW.record#>>'{observations,benchmark_reference,close}')::numeric,
            (NEW.record#>>'{observations,benchmark_target,close}')::numeric
        );
        expected_relative_return := outcome_decimal34(
            expected_asset_return - expected_benchmark_return
        );
        IF NEW.asset_return IS DISTINCT FROM expected_asset_return
            OR NEW.benchmark_return IS DISTINCT FROM expected_benchmark_return
            OR NEW.benchmark_relative_return IS DISTINCT FROM expected_relative_return THEN
            RAISE EXCEPTION 'prospective outcome returns do not exactly recompute';
        END IF;
    END IF;

    SELECT count(*) INTO retained_attempt_count
    FROM research_prospective_outcome_attempts WHERE plan_id = NEW.plan_id;
    IF jsonb_array_length(NEW.record->'attempts') <> retained_attempt_count
        OR retained_attempt_count NOT BETWEEN 1 AND 6 THEN
        RAISE EXCEPTION 'prospective outcome omits retained attempts';
    END IF;
    IF (
        SELECT count(DISTINCT value->>'attempt_id') <> retained_attempt_count
            OR count(DISTINCT (value->>'attempt_number')::integer) <> retained_attempt_count
            OR bool_or((value->>'attempt_number')::integer <> position)
        FROM jsonb_array_elements(NEW.record->'attempts')
            WITH ORDINALITY AS item(value, position)
    ) THEN
        RAISE EXCEPTION 'prospective outcome attempts are not unique and ordered';
    END IF;
    FOR attempt IN SELECT value FROM jsonb_array_elements(NEW.record->'attempts') LOOP
        IF (attempt->>'completed_at')::timestamptz > NEW.evaluated_at
            OR NOT EXISTS (
                SELECT 1 FROM research_prospective_outcome_attempts
                WHERE attempt_id = (attempt->>'attempt_id')::uuid
                  AND plan_id = NEW.plan_id AND record = attempt
            ) THEN
            RAISE EXCEPTION 'prospective outcome references an absent or future attempt';
        END IF;
    END LOOP;
    SELECT value->>'status' INTO last_attempt_status
    FROM jsonb_array_elements(NEW.record->'attempts') WITH ORDINALITY AS item(value, position)
    ORDER BY position DESC LIMIT 1;
    IF (NEW.status = 'completed' AND last_attempt_status <> 'succeeded')
        OR (NEW.status = 'data_unavailable' AND last_attempt_status <> 'terminal_failure') THEN
        RAISE EXCEPTION 'prospective outcome terminal attempt does not match status';
    END IF;
    RETURN NEW;
END
$$;

INSERT INTO schema_migrations (version) VALUES ('0027_outcome_science_invariants');

COMMIT;
