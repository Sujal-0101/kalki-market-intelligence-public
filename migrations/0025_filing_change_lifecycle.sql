BEGIN;

CREATE TABLE research_filing_change_snapshots (
    manifest_sha256 text PRIMARY KEY CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
    accession_number text NOT NULL CHECK (accession_number ~ '^\d{10}-\d{2}-\d{6}$'),
    canonical_cik text NOT NULL CHECK (canonical_cik ~ '^\d{10}$'),
    filing_form text NOT NULL CHECK (filing_form IN (
        '10-K', '10-K/A', '10-Q', '10-Q/A', 'S-1', 'S-1/A', 'S-3', 'S-3/A',
        '424B2', '424B3', '424B4', '424B5', '424B7', '424B8', '424H', 'FWP'
    )),
    filed_at timestamptz NOT NULL,
    available_at timestamptz NOT NULL,
    retrieved_at timestamptz NOT NULL,
    source_url text NOT NULL CHECK (
        source_url ~ '^https://www[.]sec[.]gov/Archives/edgar/data/'
        AND length(source_url) <= 2048
    ),
    source_content_sha256 text NOT NULL CHECK (source_content_sha256 ~ '^[0-9a-f]{64}$'),
    normalized_visible_sha256 text NOT NULL CHECK (
        normalized_visible_sha256 ~ '^[0-9a-f]{64}$'
    ),
    section_count integer NOT NULL CHECK (section_count BETWEEN 1 AND 64),
    extraction_version text NOT NULL CHECK (
        extraction_version = 'filing-change-sections-v1'
    ),
    schema_version text NOT NULL CHECK (schema_version = '1.0.0'),
    record jsonb NOT NULL CHECK (pg_column_size(record) <= 2000000),
    CHECK (available_at >= filed_at AND retrieved_at >= available_at)
);

CREATE INDEX research_filing_change_snapshots_issuer_time_idx
    ON research_filing_change_snapshots (
        canonical_cik, available_at, retrieved_at, accession_number
    );

CREATE TABLE research_filing_change_selections (
    receipt_id uuid PRIMARY KEY,
    relationship text NOT NULL CHECK (relationship IN (
        'amendment_of', 'successive_periodic_report', 'prospectus_update'
    )),
    previous_accession_number text NOT NULL CHECK (
        previous_accession_number ~ '^\d{10}-\d{2}-\d{6}$'
    ),
    current_accession_number text NOT NULL CHECK (
        current_accession_number ~ '^\d{10}-\d{2}-\d{6}$'
    ),
    previous_manifest_sha256 text NOT NULL REFERENCES research_filing_change_snapshots,
    current_manifest_sha256 text NOT NULL REFERENCES research_filing_change_snapshots,
    selected_characters integer NOT NULL CHECK (selected_characters BETWEEN 0 AND 3600),
    selection_sha256 text NOT NULL UNIQUE CHECK (selection_sha256 ~ '^[0-9a-f]{64}$'),
    recorded_at timestamptz NOT NULL,
    extraction_version text NOT NULL CHECK (
        extraction_version = 'filing-change-sections-v1'
    ),
    selection_version text NOT NULL CHECK (
        selection_version = 'filing-change-selection-v1'
    ),
    schema_version text NOT NULL CHECK (schema_version = '1.0.0'),
    record jsonb NOT NULL CHECK (pg_column_size(record) <= 100000),
    CHECK (previous_accession_number <> current_accession_number),
    CHECK (previous_manifest_sha256 <> current_manifest_sha256)
);

CREATE INDEX research_filing_change_selections_current_idx
    ON research_filing_change_selections (
        current_accession_number, recorded_at, receipt_id
    );

CREATE FUNCTION validate_filing_change_snapshot()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.record->>'manifest_sha256' IS DISTINCT FROM NEW.manifest_sha256
        OR NEW.record->>'accession_number' IS DISTINCT FROM NEW.accession_number
        OR lpad(NEW.record->>'cik', 10, '0') IS DISTINCT FROM NEW.canonical_cik
        OR NEW.record->>'filing_form' IS DISTINCT FROM NEW.filing_form
        OR (NEW.record->>'filed_at')::timestamptz IS DISTINCT FROM NEW.filed_at
        OR (NEW.record->>'available_at')::timestamptz IS DISTINCT FROM NEW.available_at
        OR (NEW.record->>'retrieved_at')::timestamptz IS DISTINCT FROM NEW.retrieved_at
        OR NEW.record->>'source_url' IS DISTINCT FROM NEW.source_url
        OR position(
            '/Archives/edgar/data/'
            || coalesce(nullif(ltrim(NEW.canonical_cik, '0'), ''), '0') || '/'
            IN NEW.source_url
        ) = 0
        OR (
            position('/' || replace(NEW.accession_number, '-', '') || '/' IN NEW.source_url) = 0
            AND right(NEW.source_url, length(NEW.accession_number) + 5)
                <> '/' || NEW.accession_number || '.txt'
        )
        OR NEW.record->>'source_content_sha256' IS DISTINCT FROM NEW.source_content_sha256
        OR NEW.record->>'normalized_visible_sha256'
            IS DISTINCT FROM NEW.normalized_visible_sha256
        OR jsonb_array_length(NEW.record->'sections') IS DISTINCT FROM NEW.section_count
        OR NEW.record->>'extraction_version' IS DISTINCT FROM NEW.extraction_version
        OR NEW.record->>'schema_version' IS DISTINCT FROM NEW.schema_version THEN
        RAISE EXCEPTION 'filing-change snapshot columns do not match the closed record';
    END IF;
    RETURN NEW;
END
$$;

CREATE FUNCTION validate_filing_change_selection()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    previous_snapshot research_filing_change_snapshots%ROWTYPE;
    current_snapshot research_filing_change_snapshots%ROWTYPE;
BEGIN
    SELECT * INTO previous_snapshot FROM research_filing_change_snapshots
    WHERE manifest_sha256 = NEW.previous_manifest_sha256;
    SELECT * INTO current_snapshot FROM research_filing_change_snapshots
    WHERE manifest_sha256 = NEW.current_manifest_sha256;
    IF previous_snapshot.manifest_sha256 IS NULL OR current_snapshot.manifest_sha256 IS NULL
        OR previous_snapshot.accession_number IS DISTINCT FROM NEW.previous_accession_number
        OR current_snapshot.accession_number IS DISTINCT FROM NEW.current_accession_number
        OR previous_snapshot.canonical_cik IS DISTINCT FROM current_snapshot.canonical_cik
        OR previous_snapshot.available_at >= current_snapshot.available_at
        OR previous_snapshot.retrieved_at > current_snapshot.retrieved_at
        OR NEW.recorded_at IS DISTINCT FROM greatest(
            previous_snapshot.retrieved_at, current_snapshot.retrieved_at
        )
        OR NEW.record->>'receipt_id' IS DISTINCT FROM NEW.receipt_id::text
        OR NEW.record->>'relationship' IS DISTINCT FROM NEW.relationship
        OR NEW.record->>'previous_accession_number'
            IS DISTINCT FROM NEW.previous_accession_number
        OR NEW.record->>'current_accession_number'
            IS DISTINCT FROM NEW.current_accession_number
        OR NEW.record->>'previous_manifest_sha256'
            IS DISTINCT FROM NEW.previous_manifest_sha256
        OR NEW.record->>'current_manifest_sha256'
            IS DISTINCT FROM NEW.current_manifest_sha256
        OR (NEW.record->>'selected_characters')::integer
            IS DISTINCT FROM NEW.selected_characters
        OR NEW.record->>'selection_sha256' IS DISTINCT FROM NEW.selection_sha256
        OR NEW.record->>'extraction_version' IS DISTINCT FROM NEW.extraction_version
        OR NEW.record->>'selection_version' IS DISTINCT FROM NEW.selection_version
        OR NEW.record->>'schema_version' IS DISTINCT FROM NEW.schema_version THEN
        RAISE EXCEPTION 'filing-change selection does not match its closed snapshots/record';
    END IF;
    IF NEW.relationship = 'amendment_of' AND (
            right(current_snapshot.filing_form, 2) <> '/A'
            OR right(previous_snapshot.filing_form, 2) = '/A'
            OR regexp_replace(current_snapshot.filing_form, '/A$', '')
                <> previous_snapshot.filing_form
        ) THEN
        RAISE EXCEPTION 'filing-change amendment relationship does not match its forms';
    ELSIF NEW.relationship = 'successive_periodic_report' AND (
            previous_snapshot.filing_form NOT IN ('10-K', '10-Q')
            OR current_snapshot.filing_form <> previous_snapshot.filing_form
        ) THEN
        RAISE EXCEPTION 'filing-change periodic relationship does not match its forms';
    ELSIF NEW.relationship = 'prospectus_update' AND (
            previous_snapshot.filing_form NOT IN (
                'S-1', 'S-1/A', 'S-3', 'S-3/A', '424B2', '424B3', '424B4',
                '424B5', '424B7', '424B8', '424H', 'FWP'
            )
            OR current_snapshot.filing_form NOT IN (
                'S-1', 'S-1/A', 'S-3', 'S-3/A', '424B2', '424B3', '424B4',
                '424B5', '424B7', '424B8', '424H', 'FWP'
            )
        ) THEN
        RAISE EXCEPTION 'filing-change prospectus relationship does not match its forms';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER research_filing_change_snapshots_validate
    BEFORE INSERT ON research_filing_change_snapshots
    FOR EACH ROW EXECUTE FUNCTION validate_filing_change_snapshot();
CREATE TRIGGER research_filing_change_snapshots_no_update_delete
    BEFORE UPDATE OR DELETE ON research_filing_change_snapshots
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_filing_change_snapshots_no_truncate
    BEFORE TRUNCATE ON research_filing_change_snapshots
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();

CREATE TRIGGER research_filing_change_selections_validate
    BEFORE INSERT ON research_filing_change_selections
    FOR EACH ROW EXECUTE FUNCTION validate_filing_change_selection();
CREATE TRIGGER research_filing_change_selections_no_update_delete
    BEFORE UPDATE OR DELETE ON research_filing_change_selections
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_filing_change_selections_no_truncate
    BEFORE TRUNCATE ON research_filing_change_selections
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();

INSERT INTO schema_migrations (version) VALUES ('0025_filing_change_lifecycle');

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kalki_app') THEN
        EXECUTE 'GRANT SELECT, INSERT ON research_filing_change_snapshots TO kalki_app';
        EXECUTE 'GRANT SELECT, INSERT ON research_filing_change_selections TO kalki_app';
    END IF;
END
$$;

COMMIT;
