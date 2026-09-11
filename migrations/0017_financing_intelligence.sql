BEGIN;

CREATE TABLE research_financing_state (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    started_at timestamptz NOT NULL,
    schema_version text NOT NULL CHECK (schema_version = '1.0.0')
);
INSERT INTO research_financing_state (started_at, schema_version)
VALUES (clock_timestamp(), '1.0.0');

CREATE TABLE research_financing_jobs (
    accession_number text PRIMARY KEY CHECK (
        accession_number ~ '^[0-9]{10}-[0-9]{2}-[0-9]{6}$'
    ),
    index_ciks text[] NOT NULL CHECK (
        cardinality(index_ciks) BETWEEN 1 AND 16
    ),
    index_names text[] NOT NULL CHECK (
        cardinality(index_names) = cardinality(index_ciks)
    ),
    form text NOT NULL CHECK (form IN (
        'S-1', 'S-1/A', 'S-3', 'S-3/A', '424B1', '424B2', '424B3',
        '424B4', '424B5', '424B7', '8-K', '8-K/A'
    )),
    filed_on date NOT NULL,
    discovered_at timestamptz NOT NULL,
    source_index_url text NOT NULL CHECK (
        source_index_url ~ '^https://www[.]sec[.]gov/Archives/edgar/daily-index/[0-9]{4}/QTR[1-4]/master[.][0-9]{8}[.]idx$'
    ),
    source_index_sha256 text NOT NULL CHECK (source_index_sha256 ~ '^[0-9a-f]{64}$'),
    status text NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'processing', 'retry_wait', 'completed', 'no_terms', 'failed')
    ),
    attempts smallint NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 3),
    next_attempt_at timestamptz,
    claimed_at timestamptz,
    completed_at timestamptz,
    resolved_issuer_cik text CHECK (resolved_issuer_cik ~ '^[0-9]{10}$'),
    resolved_issuer_name text CHECK (
        resolved_issuer_name IS NULL OR char_length(resolved_issuer_name) BETWEEN 1 AND 255
    ),
    last_error_category text CHECK (last_error_category IN (
        'metadata_unavailable', 'primary_document_error', 'parse_error',
        'persistence_error', 'other'
    )),
    terminal_reason text CHECK (terminal_reason IN ('no_supported_terms')),
    updated_at timestamptz NOT NULL,
    CHECK (discovered_at >= filed_on::timestamp AT TIME ZONE 'UTC'),
    CHECK ((status = 'processing') = (claimed_at IS NOT NULL)),
    CHECK ((status = 'retry_wait') = (next_attempt_at IS NOT NULL)),
    CHECK ((status IN ('completed', 'no_terms', 'failed')) = (completed_at IS NOT NULL)),
    CHECK ((status IN ('retry_wait', 'failed')) = (last_error_category IS NOT NULL)),
    CHECK ((status = 'no_terms') = (terminal_reason IS NOT NULL)),
    CHECK ((status = 'completed') = (resolved_issuer_cik IS NOT NULL)),
    CHECK ((resolved_issuer_cik IS NULL) = (resolved_issuer_name IS NULL)),
    CHECK (status <> 'failed' OR attempts = 3)
);
CREATE INDEX research_financing_jobs_claim_idx
    ON research_financing_jobs (status, next_attempt_at, filed_on, accession_number)
    WHERE status IN ('pending', 'retry_wait');

CREATE TABLE research_financing_receipts (
    accession_number text PRIMARY KEY CHECK (
        accession_number ~ '^[0-9]{10}-[0-9]{2}-[0-9]{6}$'
    ),
    issuer_cik text NOT NULL CHECK (issuer_cik ~ '^[0-9]{10}$'),
    issuer_name text NOT NULL CHECK (char_length(issuer_name) BETWEEN 1 AND 255),
    form text NOT NULL CHECK (form IN (
        'S-1', 'S-1/A', 'S-3', 'S-3/A', '424B1', '424B2', '424B3',
        '424B4', '424B5', '424B7', '8-K', '8-K/A'
    )),
    accepted_at timestamptz NOT NULL,
    retrieved_at timestamptz NOT NULL,
    source_url text NOT NULL CHECK (
        source_url ~ '^https://www[.]sec[.]gov/Archives/edgar/data/'
    ),
    source_content_sha256 text NOT NULL CHECK (source_content_sha256 ~ '^[0-9a-f]{64}$'),
    parser_version text NOT NULL CHECK (parser_version = 'sec-financing-v1'),
    term_count smallint NOT NULL CHECK (term_count BETWEEN 1 AND 32),
    record jsonb NOT NULL,
    CHECK (retrieved_at >= accepted_at)
);
CREATE INDEX research_financing_receipts_issuer_time_idx
    ON research_financing_receipts (issuer_cik, accepted_at DESC, accession_number DESC);
CREATE INDEX research_financing_receipts_form_time_idx
    ON research_financing_receipts (form, accepted_at DESC, accession_number DESC);

CREATE TABLE research_financing_routing_receipts (
    accession_number text PRIMARY KEY REFERENCES research_financing_receipts(accession_number),
    source_content_sha256 text NOT NULL CHECK (source_content_sha256 ~ '^[0-9a-f]{64}$'),
    event_context text NOT NULL CHECK (event_context IN (
        'REGISTRATION_CAPACITY', 'EQUITY_FINANCING', 'DEBT_FINANCING', 'MULTI_INSTRUMENT'
    )),
    tier smallint NOT NULL CHECK (tier = 0),
    outcome text NOT NULL CHECK (outcome = 'retain'),
    reason text NOT NULL CHECK (reason = 'financing_context'),
    requires_model boolean NOT NULL CHECK (requires_model = false),
    routing_version text NOT NULL CHECK (routing_version = 'financing-tier0-v1'),
    record jsonb NOT NULL
);

CREATE FUNCTION validate_financing_receipt()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.record->>'accession_number' IS DISTINCT FROM NEW.accession_number
        OR NEW.record->>'issuer_cik' IS DISTINCT FROM NEW.issuer_cik
        OR NEW.record->>'issuer_name' IS DISTINCT FROM NEW.issuer_name
        OR NEW.record->>'form' IS DISTINCT FROM NEW.form
        OR (NEW.record->>'accepted_at')::timestamptz IS DISTINCT FROM NEW.accepted_at
        OR (NEW.record->>'retrieved_at')::timestamptz IS DISTINCT FROM NEW.retrieved_at
        OR NEW.record->>'source_url' IS DISTINCT FROM NEW.source_url
        OR NEW.record->>'source_content_sha256' IS DISTINCT FROM NEW.source_content_sha256
        OR NEW.record->>'parser_version' IS DISTINCT FROM NEW.parser_version
        OR jsonb_array_length(NEW.record->'terms') IS DISTINCT FROM NEW.term_count THEN
        RAISE EXCEPTION 'financing receipt columns do not match the closed record';
    END IF;
    RETURN NEW;
END
$$;

CREATE FUNCTION validate_financing_routing_receipt()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE immutable_source_hash text;
BEGIN
    SELECT source_content_sha256 INTO immutable_source_hash
    FROM research_financing_receipts WHERE accession_number = NEW.accession_number;
    IF immutable_source_hash IS NULL
        OR immutable_source_hash IS DISTINCT FROM NEW.source_content_sha256
        OR NEW.record->>'accession_number' IS DISTINCT FROM NEW.accession_number
        OR NEW.record->>'source_content_sha256' IS DISTINCT FROM NEW.source_content_sha256
        OR NEW.record->>'event_context' IS DISTINCT FROM NEW.event_context
        OR NEW.record->>'routing_version' IS DISTINCT FROM NEW.routing_version
        OR (NEW.record#>>'{decision,tier}')::smallint IS DISTINCT FROM NEW.tier
        OR NEW.record#>>'{decision,outcome}' IS DISTINCT FROM NEW.outcome
        OR NEW.record#>>'{decision,reason}' IS DISTINCT FROM NEW.reason
        OR (NEW.record#>>'{decision,requires_model}')::boolean
            IS DISTINCT FROM NEW.requires_model THEN
        RAISE EXCEPTION 'financing routing columns do not match receipt or closed record';
    END IF;
    RETURN NEW;
END
$$;

CREATE FUNCTION protect_financing_job_lifecycle()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.accession_number IS DISTINCT FROM OLD.accession_number
        OR NEW.index_ciks IS DISTINCT FROM OLD.index_ciks
        OR NEW.index_names IS DISTINCT FROM OLD.index_names
        OR NEW.form IS DISTINCT FROM OLD.form
        OR NEW.filed_on IS DISTINCT FROM OLD.filed_on
        OR NEW.discovered_at IS DISTINCT FROM OLD.discovered_at
        OR NEW.source_index_url IS DISTINCT FROM OLD.source_index_url
        OR NEW.source_index_sha256 IS DISTINCT FROM OLD.source_index_sha256 THEN
        RAISE EXCEPTION 'financing discovery identity and provenance are immutable';
    END IF;
    IF OLD.status IN ('completed', 'no_terms', 'failed') THEN
        RAISE EXCEPTION 'terminal financing jobs are immutable';
    END IF;
    IF (OLD.status = 'pending' AND NEW.status <> 'processing')
        OR (OLD.status = 'retry_wait' AND NEW.status <> 'processing')
        OR (OLD.status = 'processing'
            AND NEW.status NOT IN ('retry_wait', 'completed', 'no_terms', 'failed')) THEN
        RAISE EXCEPTION 'invalid financing job transition';
    END IF;
    IF NEW.status = 'processing' AND NEW.attempts <> OLD.attempts THEN
        RAISE EXCEPTION 'financing claim cannot consume an attempt before work finishes';
    END IF;
    IF OLD.status = 'processing' AND NEW.status IN ('completed', 'no_terms', 'failed')
        AND NEW.attempts <> OLD.attempts + 1 THEN
        RAISE EXCEPTION 'financing terminal completion must record exactly one attempt';
    END IF;
    IF OLD.status = 'processing' AND NEW.status = 'retry_wait'
        AND NEW.attempts NOT IN (OLD.attempts, OLD.attempts + 1) THEN
        RAISE EXCEPTION 'financing retry must preserve a lease or record one attempt';
    END IF;
    IF NEW.status = 'completed' AND NOT EXISTS (
        SELECT 1 FROM research_financing_receipts r
        JOIN research_financing_routing_receipts t USING (accession_number)
        WHERE r.accession_number = NEW.accession_number
          AND r.issuer_cik = NEW.resolved_issuer_cik
          AND r.form = NEW.form
    ) THEN
        RAISE EXCEPTION 'completed financing job requires its immutable receipt pair';
    END IF;
    IF NEW.status = 'no_terms' AND EXISTS (
        SELECT 1 FROM research_financing_receipts
        WHERE accession_number = NEW.accession_number
    ) THEN
        RAISE EXCEPTION 'no-terms financing job cannot have an intelligence receipt';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER research_financing_receipts_validate
    BEFORE INSERT ON research_financing_receipts
    FOR EACH ROW EXECUTE FUNCTION validate_financing_receipt();
CREATE TRIGGER research_financing_routing_receipts_validate
    BEFORE INSERT ON research_financing_routing_receipts
    FOR EACH ROW EXECUTE FUNCTION validate_financing_routing_receipt();
CREATE TRIGGER research_financing_jobs_lifecycle
    BEFORE UPDATE ON research_financing_jobs
    FOR EACH ROW EXECUTE FUNCTION protect_financing_job_lifecycle();

CREATE TRIGGER research_financing_receipts_no_update_delete
    BEFORE UPDATE OR DELETE ON research_financing_receipts
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_financing_receipts_no_truncate
    BEFORE TRUNCATE ON research_financing_receipts
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_financing_routing_receipts_no_update_delete
    BEFORE UPDATE OR DELETE ON research_financing_routing_receipts
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_financing_routing_receipts_no_truncate
    BEFORE TRUNCATE ON research_financing_routing_receipts
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_financing_jobs_no_delete
    BEFORE DELETE ON research_financing_jobs
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_financing_jobs_no_truncate
    BEFORE TRUNCATE ON research_financing_jobs
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_financing_state_no_update_delete
    BEFORE UPDATE OR DELETE ON research_financing_state
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_financing_state_no_truncate
    BEFORE TRUNCATE ON research_financing_state
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kalki_app') THEN
        EXECUTE 'GRANT SELECT ON research_financing_state TO kalki_app';
        EXECUTE 'GRANT SELECT, INSERT ON research_financing_receipts,
            research_financing_routing_receipts, research_financing_jobs TO kalki_app';
        EXECUTE 'GRANT UPDATE (
            status, attempts, next_attempt_at, claimed_at, completed_at,
            resolved_issuer_cik, resolved_issuer_name, last_error_category,
            terminal_reason, updated_at
        ) ON research_financing_jobs TO kalki_app';
    END IF;
END
$$;

INSERT INTO schema_migrations (version) VALUES ('0017_financing_intelligence');
COMMIT;
