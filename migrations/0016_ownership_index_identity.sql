BEGIN;

ALTER TABLE research_ownership_jobs RENAME COLUMN issuer_cik TO first_index_cik;
ALTER TABLE research_ownership_jobs RENAME COLUMN company_name TO first_index_name;
ALTER TABLE research_ownership_jobs
    ADD COLUMN index_ciks text[],
    ADD COLUMN index_names text[],
    ADD COLUMN resolved_issuer_cik text CHECK (
        resolved_issuer_cik IS NULL OR resolved_issuer_cik ~ '^[0-9]{10}$'
    ),
    ADD COLUMN resolved_issuer_name text CHECK (
        resolved_issuer_name IS NULL
        OR char_length(resolved_issuer_name) BETWEEN 1 AND 255
    );

UPDATE research_ownership_jobs
SET index_ciks = ARRAY[first_index_cik], index_names = ARRAY[first_index_name];

ALTER TABLE research_ownership_jobs
    ALTER COLUMN index_ciks SET NOT NULL,
    ALTER COLUMN index_names SET NOT NULL,
    ADD CHECK (cardinality(index_ciks) BETWEEN 1 AND 16),
    ADD CHECK (cardinality(index_names) = cardinality(index_ciks)),
    ADD CHECK (first_index_cik = index_ciks[1]),
    ADD CHECK (first_index_name = index_names[1]),
    ADD CHECK (array_to_string(index_ciks, ',') ~ '^[0-9]{10}(,[0-9]{10})*$'),
    ADD CHECK (
        (status = 'completed') = (
            resolved_issuer_cik IS NOT NULL AND resolved_issuer_name IS NOT NULL
        )
    );

CREATE OR REPLACE FUNCTION protect_ownership_job_lifecycle()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.accession_number IS DISTINCT FROM OLD.accession_number
        OR NEW.first_index_cik IS DISTINCT FROM OLD.first_index_cik
        OR NEW.first_index_name IS DISTINCT FROM OLD.first_index_name
        OR NEW.index_ciks IS DISTINCT FROM OLD.index_ciks
        OR NEW.index_names IS DISTINCT FROM OLD.index_names
        OR NEW.form IS DISTINCT FROM OLD.form
        OR NEW.filed_on IS DISTINCT FROM OLD.filed_on
        OR NEW.discovered_at IS DISTINCT FROM OLD.discovered_at
        OR NEW.source_index_url IS DISTINCT FROM OLD.source_index_url
        OR NEW.source_index_sha256 IS DISTINCT FROM OLD.source_index_sha256 THEN
        RAISE EXCEPTION 'ownership discovery identity and provenance are immutable';
    END IF;
    IF OLD.status IN ('completed', 'failed') THEN
        RAISE EXCEPTION 'terminal ownership jobs are immutable';
    END IF;
    IF (OLD.status = 'pending' AND NEW.status <> 'processing')
        OR (OLD.status = 'retry_wait' AND NEW.status <> 'processing')
        OR (OLD.status = 'processing'
            AND NEW.status NOT IN ('retry_wait', 'completed', 'failed')) THEN
        RAISE EXCEPTION 'invalid ownership job transition';
    END IF;
    IF NEW.status = 'processing' AND NEW.attempts <> OLD.attempts THEN
        RAISE EXCEPTION 'ownership claim cannot consume an attempt before work finishes';
    END IF;
    IF OLD.status = 'processing' AND NEW.status IN ('completed', 'failed')
        AND NEW.attempts <> OLD.attempts + 1 THEN
        RAISE EXCEPTION 'ownership terminal completion must record exactly one attempt';
    END IF;
    IF OLD.status = 'processing' AND NEW.status = 'retry_wait'
        AND NEW.attempts NOT IN (OLD.attempts, OLD.attempts + 1) THEN
        RAISE EXCEPTION 'ownership retry must preserve a lease or record one attempt';
    END IF;
    IF NEW.status <> 'completed' AND (
        NEW.resolved_issuer_cik IS NOT NULL OR NEW.resolved_issuer_name IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'only a completed ownership job may retain resolved issuer identity';
    END IF;
    IF NEW.status = 'completed' AND NOT EXISTS (
        SELECT 1 FROM research_ownership_receipts r
        JOIN research_ownership_routing_receipts t USING (accession_number)
        WHERE r.accession_number = NEW.accession_number
          AND r.issuer_cik = NEW.resolved_issuer_cik
          AND r.record->>'issuer_name' = NEW.resolved_issuer_name
          AND r.form = NEW.form
    ) THEN
        RAISE EXCEPTION 'completed ownership job requires its resolved immutable receipt pair';
    END IF;
    RETURN NEW;
END
$$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kalki_app') THEN
        EXECUTE 'GRANT UPDATE (resolved_issuer_cik, resolved_issuer_name)
            ON research_ownership_jobs TO kalki_app';
    END IF;
END
$$;

INSERT INTO schema_migrations (version) VALUES ('0016_ownership_index_identity');

COMMIT;
