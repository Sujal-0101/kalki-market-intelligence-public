BEGIN;

ALTER TABLE research_candidates DROP CONSTRAINT research_candidates_status_check;
ALTER TABLE research_candidates ADD CONSTRAINT research_candidates_status_check CHECK (
    status IN (
        'pending', 'processing', 'published', 'skipped', 'retry_wait', 'failed', 'quarantined'
    )
);

CREATE TABLE research_verifier_reviews (
    review_id uuid PRIMARY KEY,
    candidate_id uuid NOT NULL,
    accession_number text NOT NULL REFERENCES research_candidates(accession_number),
    review_number integer NOT NULL CHECK (review_number IN (1, 2)),
    completed_at timestamptz NOT NULL,
    verdict text NOT NULL CHECK (verdict IN ('approve', 'challenge')),
    model_name text NOT NULL CHECK (length(model_name) BETWEEN 1 AND 255),
    model_digest text NOT NULL CHECK (model_digest ~ '^[0-9a-f]{64}$'),
    prompt_version text NOT NULL CHECK (prompt_version = 'verifier-v1'),
    schema_version text NOT NULL CHECK (schema_version = '1.0.0'),
    challenge_categories text[] NOT NULL,
    evidence_ids uuid[] NOT NULL CHECK (cardinality(evidence_ids) BETWEEN 1 AND 8),
    record jsonb NOT NULL
);

CREATE INDEX research_verifier_reviews_candidate_idx
    ON research_verifier_reviews (candidate_id, review_number, completed_at);

CREATE TABLE research_verification_retries (
    retry_id uuid PRIMARY KEY,
    candidate_id uuid NOT NULL,
    accession_number text NOT NULL UNIQUE REFERENCES research_candidates(accession_number),
    reserved_at timestamptz NOT NULL,
    review_id uuid NOT NULL UNIQUE REFERENCES research_verifier_reviews(review_id),
    reconsideration jsonb NOT NULL
);

CREATE FUNCTION validate_verification_retry()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM research_verifier_reviews r
        WHERE r.review_id = NEW.review_id
          AND r.candidate_id = NEW.candidate_id
          AND r.accession_number = NEW.accession_number
          AND r.review_number = 1
          AND r.verdict = 'challenge'
    ) THEN
        RAISE EXCEPTION 'semantic retry requires its matching first challenge review';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER research_verification_retries_validate
    BEFORE INSERT ON research_verification_retries
    FOR EACH ROW EXECUTE FUNCTION validate_verification_retry();

CREATE TABLE research_verification_dispositions (
    disposition_id uuid PRIMARY KEY,
    candidate_id uuid NOT NULL,
    accession_number text NOT NULL UNIQUE REFERENCES research_candidates(accession_number),
    decided_at timestamptz NOT NULL,
    disposition text NOT NULL CHECK (
        disposition IN ('approved', 'verification_disagreement', 'analyst_retry_rejected')
    ),
    retry_count integer NOT NULL CHECK (retry_count IN (0, 1)),
    analyst_model_name text NOT NULL CHECK (length(analyst_model_name) BETWEEN 1 AND 255),
    analyst_model_digest text NOT NULL CHECK (analyst_model_digest ~ '^[0-9a-f]{64}$'),
    verifier_model_name text NOT NULL CHECK (length(verifier_model_name) BETWEEN 1 AND 255),
    verifier_model_digest text NOT NULL CHECK (verifier_model_digest ~ '^[0-9a-f]{64}$'),
    review_ids uuid[] NOT NULL CHECK (cardinality(review_ids) BETWEEN 1 AND 2),
    challenge_categories text[] NOT NULL,
    evidence_ids uuid[] NOT NULL,
    record jsonb NOT NULL,
    CHECK (
        (disposition = 'approved' AND cardinality(challenge_categories) = 0
            AND cardinality(evidence_ids) = 0)
        OR
        (disposition <> 'approved' AND cardinality(challenge_categories) BETWEEN 1 AND 9
            AND cardinality(evidence_ids) BETWEEN 1 AND 8)
    )
);

CREATE FUNCTION validate_verification_disposition()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    expected_reviews integer;
    matching_reviews integer;
    distinct_reviews integer;
    final_verdict text;
    final_model_name text;
    final_model_digest text;
BEGIN
    expected_reviews := CASE
        WHEN NEW.disposition = 'analyst_retry_rejected' THEN 1
        ELSE NEW.retry_count + 1
    END;
    IF cardinality(NEW.review_ids) <> expected_reviews THEN
        RAISE EXCEPTION 'verification disposition has an invalid review count';
    END IF;
    SELECT count(DISTINCT review_id) INTO distinct_reviews
    FROM unnest(NEW.review_ids) AS ids(review_id);
    IF distinct_reviews <> expected_reviews THEN
        RAISE EXCEPTION 'verification disposition review IDs must be unique';
    END IF;
    SELECT count(*) INTO matching_reviews
    FROM research_verifier_reviews r
    WHERE r.review_id = ANY(NEW.review_ids)
      AND r.candidate_id = NEW.candidate_id
      AND r.accession_number = NEW.accession_number;
    IF matching_reviews <> expected_reviews THEN
        RAISE EXCEPTION 'verification disposition references mismatched reviews';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM research_verifier_reviews r
        WHERE r.review_id = NEW.review_ids[1] AND r.review_number = 1
    ) THEN
        RAISE EXCEPTION 'verification disposition must begin with review one';
    END IF;
    IF expected_reviews = 2 AND NOT EXISTS (
        SELECT 1 FROM research_verifier_reviews r
        WHERE r.review_id = NEW.review_ids[2] AND r.review_number = 2
    ) THEN
        RAISE EXCEPTION 'verification disposition must end with review two';
    END IF;
    SELECT r.verdict, r.model_name, r.model_digest
        INTO final_verdict, final_model_name, final_model_digest
    FROM research_verifier_reviews r
    WHERE r.review_id = NEW.review_ids[cardinality(NEW.review_ids)];
    IF final_model_name <> NEW.verifier_model_name
        OR final_model_digest <> NEW.verifier_model_digest THEN
        RAISE EXCEPTION 'verification disposition model lineage does not match final review';
    END IF;
    IF NEW.disposition = 'approved' AND final_verdict <> 'approve' THEN
        RAISE EXCEPTION 'approved disposition requires an approving final review';
    END IF;
    IF NEW.disposition = 'verification_disagreement'
        AND (NEW.retry_count <> 1 OR final_verdict <> 'challenge') THEN
        RAISE EXCEPTION 'persistent disagreement requires a second challenge review';
    END IF;
    IF NEW.disposition = 'analyst_retry_rejected' AND NEW.retry_count <> 1 THEN
        RAISE EXCEPTION 'analyst retry rejection requires one reserved retry';
    END IF;
    IF NEW.retry_count = 1 AND NOT EXISTS (
        SELECT 1
        FROM research_verification_retries w
        WHERE w.candidate_id = NEW.candidate_id
          AND w.accession_number = NEW.accession_number
          AND w.review_id = NEW.review_ids[1]
    ) THEN
        RAISE EXCEPTION 'retry disposition lacks its durable retry reservation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER research_verification_dispositions_validate
    BEFORE INSERT ON research_verification_dispositions
    FOR EACH ROW EXECUTE FUNCTION validate_verification_disposition();

ALTER TABLE research_briefs DROP CONSTRAINT research_briefs_schema_version_check;
ALTER TABLE research_briefs ADD CONSTRAINT research_briefs_schema_version_check
    CHECK (schema_version IN ('1.0.0', '2.0.0'));
ALTER TABLE research_briefs ADD COLUMN verification_disposition_id uuid
    REFERENCES research_verification_dispositions(disposition_id);

ALTER TABLE research_worker_status
    ADD COLUMN verifier_enabled boolean NOT NULL DEFAULT false;
ALTER TABLE research_worker_status
    ADD COLUMN verifier_model_name text CHECK (
        verifier_model_name IS NULL OR length(verifier_model_name) BETWEEN 1 AND 255
    );
ALTER TABLE research_worker_status ADD CONSTRAINT research_worker_status_verifier_check CHECK (
    verifier_enabled = (verifier_model_name IS NOT NULL)
);

CREATE FUNCTION require_approved_verification_disposition()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.schema_version <> '2.0.0' OR NEW.verification_disposition_id IS NULL THEN
        RAISE EXCEPTION 'new research briefs require version 2 independent verification';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM research_verification_dispositions d
        WHERE d.disposition_id = NEW.verification_disposition_id
          AND d.accession_number = NEW.accession_number
          AND d.disposition = 'approved'
    ) THEN
        RAISE EXCEPTION 'research brief lacks its approved verification disposition';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER research_briefs_require_verification
    BEFORE INSERT ON research_briefs
    FOR EACH ROW EXECUTE FUNCTION require_approved_verification_disposition();

CREATE TABLE research_operation_counters (
    worker_name text PRIMARY KEY CHECK (worker_name = 'filing-radar'),
    analyst_candidates bigint NOT NULL DEFAULT 0 CHECK (analyst_candidates >= 0),
    deterministic_rejections bigint NOT NULL DEFAULT 0 CHECK (deterministic_rejections >= 0),
    verifier_reviews bigint NOT NULL DEFAULT 0 CHECK (verifier_reviews >= 0),
    verifier_approvals bigint NOT NULL DEFAULT 0 CHECK (verifier_approvals >= 0),
    verifier_challenges bigint NOT NULL DEFAULT 0 CHECK (verifier_challenges >= 0),
    analyst_retries bigint NOT NULL DEFAULT 0 CHECK (analyst_retries >= 0),
    verifier_persistent_disagreements bigint NOT NULL DEFAULT 0
        CHECK (verifier_persistent_disagreements >= 0),
    verifier_errors bigint NOT NULL DEFAULT 0 CHECK (verifier_errors >= 0),
    final_publications bigint NOT NULL DEFAULT 0 CHECK (final_publications >= 0),
    updated_at timestamptz NOT NULL
);

INSERT INTO research_operation_counters (worker_name, updated_at)
VALUES ('filing-radar', statement_timestamp());

CREATE TRIGGER research_verifier_reviews_no_update_delete
    BEFORE UPDATE OR DELETE ON research_verifier_reviews
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_verifier_reviews_no_truncate
    BEFORE TRUNCATE ON research_verifier_reviews
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();

CREATE TRIGGER research_verification_retries_no_update_delete
    BEFORE UPDATE OR DELETE ON research_verification_retries
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_verification_retries_no_truncate
    BEFORE TRUNCATE ON research_verification_retries
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();

CREATE TRIGGER research_verification_dispositions_no_update_delete
    BEFORE UPDATE OR DELETE ON research_verification_dispositions
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_verification_dispositions_no_truncate
    BEFORE TRUNCATE ON research_verification_dispositions
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();

INSERT INTO schema_migrations (version) VALUES ('0005_hierarchical_verifier');

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kalki_app') THEN
        EXECUTE 'GRANT SELECT, INSERT ON research_verifier_reviews, research_verification_retries, research_verification_dispositions TO kalki_app';
        EXECUTE 'GRANT SELECT, UPDATE ON research_operation_counters TO kalki_app';
    END IF;
END
$$;

COMMIT;
