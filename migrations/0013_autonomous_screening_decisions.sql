BEGIN;

CREATE TABLE research_autonomous_screening_state (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    started_at timestamptz NOT NULL,
    schema_version text NOT NULL CHECK (schema_version = '1.0.0')
);

INSERT INTO research_autonomous_screening_state (started_at, schema_version)
VALUES (clock_timestamp(), '1.0.0');

CREATE TABLE research_autonomous_screening_decisions (
    decision_id uuid PRIMARY KEY,
    accession_number text NOT NULL UNIQUE REFERENCES research_candidates(accession_number),
    decided_at timestamptz NOT NULL,
    disposition text NOT NULL CHECK (
        disposition IN ('QUALIFIED', 'SCREENED_OUT', 'ANALYSIS_INCOMPLETE')
    ),
    reason text NOT NULL CHECK (reason IN (
        'VALIDATED_PUBLICATION', 'DETERMINISTIC_QUALIFICATION_NOT_MET',
        'NO_VALIDATED_FINDINGS', 'INSUFFICIENT_EVIDENCE',
        'VERIFICATION_DISAGREEMENT', 'ANALYST_TIMEOUT',
        'ANALYST_PROVIDER_FAILURE', 'ANALYST_CONTRACT_REJECTED',
        'EVIDENCE_VALIDATION_REJECTED', 'NUMERIC_CONFLICT',
        'PROVENANCE_FAILURE', 'VERIFIER_UNAVAILABLE', 'VERIFIER_FAILURE',
        'SOURCE_RETRIEVAL_FAILURE', 'FILING_PARSE_FAILURE',
        'COMPANYFACTS_NORMALIZATION_FAILURE', 'DETERMINISTIC_PROCESSING_FAILURE',
        'PERSISTENCE_FAILURE', 'RETRY_EXHAUSTED', 'OTHER_BOUNDED_FAILURE'
    )),
    work_attempt integer NOT NULL CHECK (work_attempt BETWEEN 1 AND 6),
    run_id uuid NOT NULL,
    analyst_attempt_ids uuid[] NOT NULL CHECK (cardinality(analyst_attempt_ids) <= 24),
    source_document_sha256 text CHECK (
        source_document_sha256 IS NULL OR source_document_sha256 ~ '^[0-9a-f]{64}$'
    ),
    schema_version text NOT NULL CHECK (schema_version = '1.0.0'),
    record jsonb NOT NULL,
    CHECK (
        (disposition = 'QUALIFIED' AND reason = 'VALIDATED_PUBLICATION')
        OR
        (disposition = 'SCREENED_OUT' AND reason IN (
            'DETERMINISTIC_QUALIFICATION_NOT_MET', 'NO_VALIDATED_FINDINGS',
            'INSUFFICIENT_EVIDENCE', 'VERIFICATION_DISAGREEMENT'
        ))
        OR
        (disposition = 'ANALYSIS_INCOMPLETE' AND reason NOT IN (
            'VALIDATED_PUBLICATION', 'DETERMINISTIC_QUALIFICATION_NOT_MET',
            'NO_VALIDATED_FINDINGS', 'INSUFFICIENT_EVIDENCE',
            'VERIFICATION_DISAGREEMENT', 'LEGACY_REASON_UNAVAILABLE', 'UNKNOWN'
        ))
    ),
    CHECK (
        disposition <> 'QUALIFIED'
        OR (cardinality(analyst_attempt_ids) > 0 AND source_document_sha256 IS NOT NULL)
    ),
    CHECK (reason <> 'NO_VALIDATED_FINDINGS' OR cardinality(analyst_attempt_ids) > 0)
);

CREATE INDEX research_autonomous_screening_decisions_time_idx
    ON research_autonomous_screening_decisions (decided_at DESC, decision_id DESC);
CREATE INDEX research_autonomous_screening_decisions_result_idx
    ON research_autonomous_screening_decisions (
        disposition, decided_at DESC, decision_id DESC
    );

CREATE FUNCTION validate_autonomous_screening_decision()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    referenced_attempt_id uuid;
    distinct_attempt_count integer;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM research_candidates c
        WHERE c.accession_number = NEW.accession_number
          AND c.discovered_at <= NEW.decided_at
    ) THEN
        RAISE EXCEPTION 'screening decision cannot precede candidate discovery';
    END IF;
    SELECT count(DISTINCT attempt_id) INTO distinct_attempt_count
    FROM unnest(NEW.analyst_attempt_ids) AS ids(attempt_id);
    IF distinct_attempt_count <> cardinality(NEW.analyst_attempt_ids) THEN
        RAISE EXCEPTION 'screening decision analyst attempt IDs must be unique';
    END IF;
    FOREACH referenced_attempt_id IN ARRAY NEW.analyst_attempt_ids LOOP
        IF NOT EXISTS (
            SELECT 1 FROM research_analyst_attempts a
            WHERE a.attempt_id = referenced_attempt_id
              AND a.origin = 'candidate'
              AND a.candidate_accession_number = NEW.accession_number
              AND a.state = 'completed'
        ) THEN
            RAISE EXCEPTION 'screening decision references an absent or incomplete attempt';
        END IF;
    END LOOP;
    IF NEW.record->>'decision_id' <> NEW.decision_id::text
        OR NEW.record->>'accession_number' <> NEW.accession_number
        OR NEW.record->>'disposition' <> NEW.disposition
        OR NEW.record->>'reason' <> NEW.reason
        OR (NEW.record->>'work_attempt')::integer <> NEW.work_attempt
        OR NEW.record->>'run_id' <> NEW.run_id::text
        OR NEW.record->>'schema_version' <> NEW.schema_version
        OR (NEW.record->>'decided_at')::timestamptz IS DISTINCT FROM NEW.decided_at
        OR NEW.record->'analyst_attempt_ids' IS DISTINCT FROM to_jsonb(NEW.analyst_attempt_ids)
        OR NEW.record->>'source_document_sha256'
            IS DISTINCT FROM NEW.source_document_sha256 THEN
        RAISE EXCEPTION 'screening decision columns do not match the closed record';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER research_autonomous_screening_decisions_validate
    BEFORE INSERT ON research_autonomous_screening_decisions
    FOR EACH ROW EXECUTE FUNCTION validate_autonomous_screening_decision();
CREATE TRIGGER research_autonomous_screening_decisions_no_update_delete
    BEFORE UPDATE OR DELETE ON research_autonomous_screening_decisions
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_autonomous_screening_decisions_no_truncate
    BEFORE TRUNCATE ON research_autonomous_screening_decisions
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_autonomous_screening_state_no_update_delete
    BEFORE UPDATE OR DELETE ON research_autonomous_screening_state
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_autonomous_screening_state_no_truncate
    BEFORE TRUNCATE ON research_autonomous_screening_state
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();

ALTER TABLE research_briefs DROP CONSTRAINT research_briefs_schema_version_check;
ALTER TABLE research_briefs ADD CONSTRAINT research_briefs_schema_version_check
    CHECK (schema_version IN ('1.0.0', '2.0.0', '3.0.0'));
ALTER TABLE research_briefs ADD COLUMN autonomous_decision_id uuid UNIQUE
    REFERENCES research_autonomous_screening_decisions(decision_id);

CREATE OR REPLACE FUNCTION require_approved_verification_disposition()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.schema_version = '2.0.0' THEN
        IF NEW.verification_disposition_id IS NULL OR NEW.autonomous_decision_id IS NULL THEN
            RAISE EXCEPTION 'new version 2 briefs require verification and terminal decision lineage';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM research_verification_dispositions d
            WHERE d.disposition_id = NEW.verification_disposition_id
              AND d.accession_number = NEW.accession_number
              AND d.disposition = 'approved'
        ) THEN
            RAISE EXCEPTION 'research brief lacks its approved verification disposition';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM research_autonomous_screening_decisions d
            WHERE d.decision_id = NEW.autonomous_decision_id
              AND d.accession_number = NEW.accession_number
              AND d.disposition = 'QUALIFIED'
              AND d.reason = 'VALIDATED_PUBLICATION'
              AND d.decided_at = NEW.published_at
        ) THEN
            RAISE EXCEPTION 'research brief lacks its matching qualified decision';
        END IF;
    ELSIF NEW.schema_version = '3.0.0' THEN
        IF NEW.autonomous_decision_id IS NULL THEN
            RAISE EXCEPTION 'version 3 briefs require terminal autonomous decision lineage';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM research_autonomous_screening_decisions d
            WHERE d.decision_id = NEW.autonomous_decision_id
              AND d.accession_number = NEW.accession_number
              AND d.disposition = 'QUALIFIED'
              AND d.reason = 'VALIDATED_PUBLICATION'
              AND d.decided_at = NEW.published_at
        ) THEN
            RAISE EXCEPTION 'research brief lacks its matching qualified decision';
        END IF;
        IF NEW.record->>'schema_version' <> '3.0.0'
            OR NEW.record->'publication_gate'->>'status' <> 'passed'
            OR NEW.record->'publication_gate'->>'mode' <> 'deterministic_only'
            OR NEW.record->'publication_gate'->>'deterministic_validation_version' <> '1.0.0'
            OR NEW.record->'publication_gate'->>'independent_verifier_status' <> 'disabled'
            OR (NEW.record->'publication_gate'->>'validated_at')::timestamptz
                IS DISTINCT FROM NEW.published_at
            OR NEW.record->'verification' IS DISTINCT FROM 'null'::jsonb
            OR NEW.verification_disposition_id IS NOT NULL THEN
            RAISE EXCEPTION 'version 3 deterministic-only publication lineage is inconsistent';
        END IF;
    ELSE
        RAISE EXCEPTION 'new research briefs require version 2 or 3 validation lineage';
    END IF;
    RETURN NEW;
END
$$;

INSERT INTO schema_migrations (version) VALUES ('0013_autonomous_screening_decisions');

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kalki_app') THEN
        EXECUTE 'GRANT SELECT ON research_autonomous_screening_state TO kalki_app';
        EXECUTE 'GRANT SELECT, INSERT ON research_autonomous_screening_decisions TO kalki_app';
    END IF;
END
$$;

COMMIT;
