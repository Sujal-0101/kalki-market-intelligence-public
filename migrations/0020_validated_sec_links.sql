BEGIN;

CREATE TABLE research_sec_link_validation_state (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    started_at timestamptz NOT NULL,
    validation_version text NOT NULL CHECK (validation_version = '1.0.0')
);
INSERT INTO research_sec_link_validation_state (started_at, validation_version)
VALUES (clock_timestamp(), '1.0.0');

CREATE TABLE research_sec_link_receipts (
    receipt_id uuid PRIMARY KEY,
    canonical_cik text NOT NULL CHECK (canonical_cik ~ '^[0-9]{10}$'),
    accession_number text NOT NULL REFERENCES research_candidates(accession_number),
    complete_submission_url text NOT NULL CHECK (
        char_length(complete_submission_url) BETWEEN 1 AND 2048
        AND complete_submission_url ~ '^https://www[.]sec[.]gov/Archives/edgar/data/'
    ),
    archive_index_url text NOT NULL CHECK (
        char_length(archive_index_url) BETWEEN 1 AND 2048
        AND archive_index_url ~ '-index[.]html$'
    ),
    primary_document_url text NOT NULL CHECK (
        char_length(primary_document_url) BETWEEN 1 AND 2048
        AND primary_document_url ~ '[.](htm|html)$'
    ),
    inline_xbrl_url text CHECK (
        inline_xbrl_url IS NULL OR (
            char_length(inline_xbrl_url) BETWEEN 1 AND 2048
            AND inline_xbrl_url ~ '^https://www[.]sec[.]gov/ixviewer/doc/action[?]doc='
        )
    ),
    complete_submission_sha256 text NOT NULL CHECK (
        complete_submission_sha256 ~ '^[0-9a-f]{64}$'
    ),
    archive_index_sha256 text NOT NULL CHECK (archive_index_sha256 ~ '^[0-9a-f]{64}$'),
    primary_document_sha256 text NOT NULL CHECK (
        primary_document_sha256 ~ '^[0-9a-f]{64}$'
    ),
    inline_xbrl_validated boolean NOT NULL,
    validated_at timestamptz NOT NULL,
    validation_version text NOT NULL CHECK (validation_version = '1.0.0'),
    record jsonb NOT NULL,
    UNIQUE (accession_number, complete_submission_sha256, validation_version),
    CHECK (inline_xbrl_validated = (inline_xbrl_url IS NOT NULL))
);
CREATE INDEX research_sec_link_receipts_lookup_idx
    ON research_sec_link_receipts (
        accession_number, complete_submission_sha256, validation_version, receipt_id
    );

CREATE FUNCTION validate_sec_link_receipt()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    candidate_cik text;
    candidate_url text;
    expected_base text;
    primary_name text;
BEGIN
    SELECT lpad(cik, 10, '0'), source_url INTO candidate_cik, candidate_url
    FROM research_candidates WHERE accession_number = NEW.accession_number;
    IF candidate_cik IS DISTINCT FROM NEW.canonical_cik
        OR candidate_url IS DISTINCT FROM NEW.complete_submission_url THEN
        RAISE EXCEPTION 'SEC link receipt does not match its discovered filing';
    END IF;
    expected_base := 'https://www.sec.gov/Archives/edgar/data/'
        || coalesce(nullif(ltrim(NEW.canonical_cik, '0'), ''), '0') || '/'
        || replace(NEW.accession_number, '-', '');
    primary_name := replace(NEW.primary_document_url, expected_base || '/', '');
    IF NEW.complete_submission_url <> expected_base || '/' || NEW.accession_number || '.txt'
        OR NEW.archive_index_url <> expected_base || '/' || NEW.accession_number || '-index.html'
        OR NEW.primary_document_url <> expected_base || '/' || primary_name
        OR primary_name !~ '^[A-Za-z0-9][A-Za-z0-9._-]*[.](htm|html)$'
        OR (NEW.inline_xbrl_url IS NOT NULL AND NEW.inline_xbrl_url <>
            'https://www.sec.gov/ixviewer/doc/action?doc='
            || replace(NEW.primary_document_url, 'https://www.sec.gov', '')) THEN
        RAISE EXCEPTION 'SEC link receipt URLs do not reconcile to one filing';
    END IF;
    IF NEW.record->>'receipt_id' IS DISTINCT FROM NEW.receipt_id::text
        OR NEW.record->>'canonical_cik' IS DISTINCT FROM NEW.canonical_cik
        OR NEW.record->>'accession_number' IS DISTINCT FROM NEW.accession_number
        OR NEW.record->>'complete_submission_url' IS DISTINCT FROM NEW.complete_submission_url
        OR NEW.record->>'archive_index_url' IS DISTINCT FROM NEW.archive_index_url
        OR NEW.record->>'primary_document_url' IS DISTINCT FROM NEW.primary_document_url
        OR NEW.record->>'inline_xbrl_url' IS DISTINCT FROM NEW.inline_xbrl_url
        OR NEW.record->>'complete_submission_sha256'
            IS DISTINCT FROM NEW.complete_submission_sha256
        OR NEW.record->>'archive_index_sha256' IS DISTINCT FROM NEW.archive_index_sha256
        OR NEW.record->>'primary_document_sha256'
            IS DISTINCT FROM NEW.primary_document_sha256
        OR (NEW.record->>'inline_xbrl_validated')::boolean
            IS DISTINCT FROM NEW.inline_xbrl_validated
        OR (NEW.record->>'validated_at')::timestamptz IS DISTINCT FROM NEW.validated_at
        OR NEW.record->>'validation_version' IS DISTINCT FROM NEW.validation_version THEN
        RAISE EXCEPTION 'SEC link receipt columns do not match the closed record';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER research_sec_link_receipts_validate
    BEFORE INSERT ON research_sec_link_receipts
    FOR EACH ROW EXECUTE FUNCTION validate_sec_link_receipt();
CREATE TRIGGER research_sec_link_receipts_no_update_delete
    BEFORE UPDATE OR DELETE ON research_sec_link_receipts
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_sec_link_receipts_no_truncate
    BEFORE TRUNCATE ON research_sec_link_receipts
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_sec_link_validation_state_no_update_delete
    BEFORE UPDATE OR DELETE ON research_sec_link_validation_state
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_sec_link_validation_state_no_truncate
    BEFORE TRUNCATE ON research_sec_link_validation_state
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();

ALTER TABLE research_briefs ADD COLUMN sec_link_receipt_id uuid UNIQUE
    REFERENCES research_sec_link_receipts(receipt_id);

CREATE OR REPLACE FUNCTION require_approved_verification_disposition()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.sec_link_receipt_id IS NULL OR NOT EXISTS (
        SELECT 1 FROM research_sec_link_receipts l
        WHERE l.receipt_id = NEW.sec_link_receipt_id
          AND l.accession_number = NEW.accession_number
          AND l.complete_submission_sha256 = NEW.source_document_sha256
          AND l.complete_submission_url = NEW.record->>'source_url'
          AND l.validated_at <= NEW.published_at
    ) THEN
        RAISE EXCEPTION 'new research brief lacks its validated SEC link receipt';
    END IF;
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

INSERT INTO schema_migrations (version) VALUES ('0020_validated_sec_links');

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kalki_app') THEN
        EXECUTE 'GRANT SELECT ON research_sec_link_validation_state TO kalki_app';
        EXECUTE 'GRANT SELECT, INSERT ON research_sec_link_receipts TO kalki_app';
    END IF;
END
$$;

COMMIT;
