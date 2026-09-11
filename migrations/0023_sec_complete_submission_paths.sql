BEGIN;

-- SEC daily indexes publish the complete-submission document at the flat archive
-- path while submissions metadata commonly derives the equivalent nested path.
-- Candidate identity remains authoritative; only these two exact official shapes
-- may participate in an immutable validated-link receipt.
CREATE OR REPLACE FUNCTION validate_sec_link_receipt()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    candidate_cik text;
    candidate_url text;
    expected_root text;
    expected_base text;
    expected_flat_complete text;
    expected_nested_complete text;
    primary_name text;
BEGIN
    SELECT lpad(cik, 10, '0'), source_url INTO candidate_cik, candidate_url
    FROM research_candidates WHERE accession_number = NEW.accession_number;
    IF candidate_cik IS DISTINCT FROM NEW.canonical_cik
        OR candidate_url IS DISTINCT FROM NEW.complete_submission_url THEN
        RAISE EXCEPTION 'SEC link receipt does not match its discovered filing';
    END IF;
    expected_root := 'https://www.sec.gov/Archives/edgar/data/'
        || coalesce(nullif(ltrim(NEW.canonical_cik, '0'), ''), '0');
    expected_base := expected_root || '/' || replace(NEW.accession_number, '-', '');
    expected_flat_complete := expected_root || '/' || NEW.accession_number || '.txt';
    expected_nested_complete := expected_base || '/' || NEW.accession_number || '.txt';
    primary_name := replace(NEW.primary_document_url, expected_base || '/', '');
    IF NEW.complete_submission_url NOT IN (
            expected_flat_complete, expected_nested_complete
        )
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

INSERT INTO schema_migrations (version) VALUES ('0023_sec_complete_submission_paths');

COMMIT;
