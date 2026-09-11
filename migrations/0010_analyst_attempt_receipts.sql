BEGIN;

CREATE TABLE research_analyst_attempts (
    attempt_id uuid PRIMARY KEY,
    invocation_id uuid NOT NULL,
    origin text NOT NULL CHECK (origin IN ('candidate', 'human')),
    candidate_accession_number text REFERENCES research_candidates(accession_number),
    lead_id uuid REFERENCES research_human_leads(lead_id),
    ticker text CHECK (ticker IS NULL OR ticker ~ '^[A-Z0-9][A-Z0-9.\-]{0,14}$'),
    cik text NOT NULL CHECK (cik ~ '^\d{1,10}$'),
    accession_number text NOT NULL CHECK (accession_number ~ '^\d{10}-\d{2}-\d{6}$'),
    filing_form text NOT NULL CHECK (length(filing_form) BETWEEN 1 AND 255),
    work_attempt integer NOT NULL CHECK (work_attempt BETWEEN 1 AND 6),
    semantic_retry boolean NOT NULL,
    provider_name text NOT NULL CHECK (length(provider_name) BETWEEN 1 AND 255),
    model_name text NOT NULL CHECK (length(model_name) BETWEEN 1 AND 255),
    model_digest text NOT NULL CHECK (model_digest ~ '^[0-9a-f]{64}$'),
    prompt_version text NOT NULL CHECK (prompt_version = 'analyst-v2'),
    output_schema_version text NOT NULL CHECK (output_schema_version = '1.0.0'),
    validation_version text NOT NULL CHECK (validation_version = '1.0.0'),
    role text NOT NULL CHECK (role IN (
        'document_interpreter', 'catalyst_analyst', 'partnership_analyst',
        'management_commentary_analyst', 'contradiction_analyst',
        'bull_bear_risk_analyst'
    )),
    attempt_number integer NOT NULL CHECK (attempt_number BETWEEN 1 AND 2),
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    latency_ms bigint CHECK (latency_ms IS NULL OR latency_ms BETWEEN 0 AND 7200000),
    input_evidence_count integer NOT NULL CHECK (input_evidence_count BETWEEN 1 AND 8),
    input_evidence_characters integer NOT NULL CHECK (
        input_evidence_characters BETWEEN 1 AND 32000
    ),
    system_prompt_characters integer NOT NULL CHECK (
        system_prompt_characters BETWEEN 1 AND 100000
    ),
    user_prompt_characters integer NOT NULL CHECK (
        user_prompt_characters BETWEEN 1 AND 100000
    ),
    context_tokens integer NOT NULL CHECK (context_tokens BETWEEN 1024 AND 32768),
    maximum_output_tokens integer NOT NULL CHECK (maximum_output_tokens BETWEEN 128 AND 4096),
    response_sha256 text CHECK (response_sha256 IS NULL OR response_sha256 ~ '^[0-9a-f]{64}$'),
    response_characters integer CHECK (
        response_characters IS NULL OR response_characters BETWEEN 0 AND 2000000
    ),
    response_bytes integer CHECK (response_bytes IS NULL OR response_bytes BETWEEN 0 AND 10000000),
    prompt_tokens integer CHECK (prompt_tokens IS NULL OR prompt_tokens BETWEEN 0 AND 1000000),
    generated_tokens integer CHECK (
        generated_tokens IS NULL OR generated_tokens BETWEEN 0 AND 1000000
    ),
    parse_status text CHECK (parse_status IS NULL OR parse_status IN (
        'not_checked', 'passed', 'failed'
    )),
    schema_status text CHECK (schema_status IS NULL OR schema_status IN (
        'not_checked', 'passed', 'failed'
    )),
    evidence_status text CHECK (evidence_status IS NULL OR evidence_status IN (
        'not_checked', 'passed', 'failed'
    )),
    failure_layer text CHECK (failure_layer IS NULL OR failure_layer IN (
        'none', 'format', 'content_evidence', 'runtime'
    )),
    failure_category text CHECK (failure_category IS NULL OR failure_category IN (
        'malformed_json', 'extra_prose', 'missing_required_field', 'invalid_type',
        'invalid_enum', 'invalid_evidence_id', 'unsupported_claim', 'numeric_conflict',
        'provenance_failure', 'timeout', 'refusal', 'provider_error', 'other'
    )),
    failure_path text CHECK (
        failure_path IS NULL OR length(failure_path) BETWEEN 1 AND 255
    ),
    retry_eligible boolean,
    retry_scope text CHECK (retry_scope IS NULL OR retry_scope IN (
        'none', 'pipeline', 'work_item'
    )),
    outcome text CHECK (outcome IS NULL OR outcome IN (
        'accepted', 'rejected', 'runtime_error'
    )),
    terminal_disposition text CHECK (terminal_disposition IS NULL OR terminal_disposition IN (
        'accepted', 'retry_pending', 'rejected', 'provider_error', 'refusal'
    )),
    state text NOT NULL CHECK (state IN ('started', 'completed')),
    record jsonb NOT NULL,
    UNIQUE (invocation_id, attempt_number),
    CHECK (
        (origin = 'candidate' AND candidate_accession_number = accession_number AND lead_id IS NULL)
        OR (origin = 'human' AND candidate_accession_number IS NULL AND lead_id IS NOT NULL)
    ),
    CHECK (
        (response_sha256 IS NULL AND response_characters IS NULL AND response_bytes IS NULL)
        OR (response_sha256 IS NOT NULL AND response_characters IS NOT NULL AND response_bytes IS NOT NULL)
    ),
    CHECK (completed_at IS NULL OR completed_at >= started_at),
    CHECK (
        (state = 'started' AND completed_at IS NULL AND latency_ms IS NULL
            AND parse_status IS NULL AND schema_status IS NULL AND evidence_status IS NULL
            AND failure_layer IS NULL AND failure_category IS NULL AND failure_path IS NULL
            AND retry_eligible IS NULL AND retry_scope IS NULL AND outcome IS NULL
            AND terminal_disposition IS NULL)
        OR
        (state = 'completed' AND completed_at IS NOT NULL AND latency_ms IS NOT NULL
            AND parse_status IS NOT NULL AND schema_status IS NOT NULL
            AND evidence_status IS NOT NULL AND failure_layer IS NOT NULL
            AND retry_eligible IS NOT NULL AND retry_scope IS NOT NULL
            AND outcome IS NOT NULL AND terminal_disposition IS NOT NULL)
    ),
    CHECK (
        state = 'started'
        OR retry_eligible = (retry_scope <> 'none')
    ),
    CHECK (
        state = 'started'
        OR retry_eligible = (terminal_disposition = 'retry_pending')
    ),
    CHECK (
        state = 'started' OR outcome <> 'accepted' OR (
            response_sha256 IS NOT NULL AND parse_status = 'passed'
            AND schema_status = 'passed' AND evidence_status = 'passed'
            AND failure_layer = 'none' AND failure_category IS NULL
            AND failure_path IS NULL AND terminal_disposition = 'accepted'
        )
    ),
    CHECK (
        state = 'started' OR outcome <> 'runtime_error' OR (
            parse_status = 'not_checked' AND schema_status = 'not_checked'
            AND evidence_status = 'not_checked' AND failure_layer = 'runtime'
            AND failure_category IS NOT NULL
        )
    ),
    CHECK (
        state = 'started' OR outcome <> 'rejected' OR (
            failure_layer IN ('format', 'content_evidence')
            AND failure_category IS NOT NULL
        )
    )
);

CREATE INDEX research_analyst_attempts_completed_idx
    ON research_analyst_attempts (completed_at DESC, attempt_id DESC);
CREATE INDEX research_analyst_attempts_candidate_idx
    ON research_analyst_attempts (candidate_accession_number, role, work_attempt, attempt_number)
    WHERE origin = 'candidate';
CREATE INDEX research_analyst_attempts_human_idx
    ON research_analyst_attempts (lead_id, role, work_attempt, attempt_number)
    WHERE origin = 'human';
CREATE INDEX research_analyst_attempts_metrics_idx
    ON research_analyst_attempts (started_at, state, failure_layer, failure_category);

CREATE FUNCTION require_started_analyst_attempt()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.state <> 'started' THEN
        RAISE EXCEPTION 'analyst attempts must be inserted before provider invocation';
    END IF;
    RETURN NEW;
END
$$;

CREATE FUNCTION protect_analyst_attempt_completion()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.state <> 'started' OR NEW.state <> 'completed' THEN
        RAISE EXCEPTION 'analyst attempts may be completed exactly once';
    END IF;
    IF ROW(
        NEW.attempt_id, NEW.invocation_id, NEW.origin, NEW.candidate_accession_number,
        NEW.lead_id, NEW.ticker, NEW.cik, NEW.accession_number, NEW.filing_form,
        NEW.work_attempt, NEW.semantic_retry, NEW.provider_name, NEW.model_name,
        NEW.model_digest, NEW.prompt_version, NEW.output_schema_version,
        NEW.validation_version, NEW.role, NEW.attempt_number, NEW.started_at,
        NEW.input_evidence_count, NEW.input_evidence_characters,
        NEW.system_prompt_characters, NEW.user_prompt_characters,
        NEW.context_tokens, NEW.maximum_output_tokens
    ) IS DISTINCT FROM ROW(
        OLD.attempt_id, OLD.invocation_id, OLD.origin, OLD.candidate_accession_number,
        OLD.lead_id, OLD.ticker, OLD.cik, OLD.accession_number, OLD.filing_form,
        OLD.work_attempt, OLD.semantic_retry, OLD.provider_name, OLD.model_name,
        OLD.model_digest, OLD.prompt_version, OLD.output_schema_version,
        OLD.validation_version, OLD.role, OLD.attempt_number, OLD.started_at,
        OLD.input_evidence_count, OLD.input_evidence_characters,
        OLD.system_prompt_characters, OLD.user_prompt_characters,
        OLD.context_tokens, OLD.maximum_output_tokens
    ) THEN
        RAISE EXCEPTION 'analyst attempt identity and input metadata are immutable';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER research_analyst_attempts_complete_once
    BEFORE UPDATE ON research_analyst_attempts
    FOR EACH ROW EXECUTE FUNCTION protect_analyst_attempt_completion();
CREATE TRIGGER research_analyst_attempts_require_start
    BEFORE INSERT ON research_analyst_attempts
    FOR EACH ROW EXECUTE FUNCTION require_started_analyst_attempt();
CREATE TRIGGER research_analyst_attempts_no_delete
    BEFORE DELETE ON research_analyst_attempts
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_analyst_attempts_no_truncate
    BEFORE TRUNCATE ON research_analyst_attempts
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();

INSERT INTO schema_migrations (version) VALUES ('0010_analyst_attempt_receipts');

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kalki_app') THEN
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON research_analyst_attempts TO kalki_app';
    END IF;
END
$$;

COMMIT;
