BEGIN;

CREATE TABLE research_event_novelty_state (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    started_at timestamptz NOT NULL,
    schema_version text NOT NULL CHECK (schema_version = '1.0.0')
);
INSERT INTO research_event_novelty_state (started_at, schema_version)
VALUES (clock_timestamp(), '1.0.0');

CREATE TABLE research_event_disclosures (
    disclosure_id uuid PRIMARY KEY,
    issuer_cik text NOT NULL CHECK (issuer_cik ~ '^[0-9]{10}$'),
    issuer_name text NOT NULL CHECK (char_length(issuer_name) BETWEEN 1 AND 255),
    category text NOT NULL CHECK (category = 'STRATEGIC_PARTNERSHIP'),
    context text NOT NULL CHECK (context IN ('CURRENT_EVENT', 'HISTORICAL_CONTEXT')),
    event_fingerprint text NOT NULL CHECK (event_fingerprint ~ '^[0-9a-f]{64}$'),
    fact_fingerprint text NOT NULL CHECK (fact_fingerprint ~ '^[0-9a-f]{64}$'),
    source_class text NOT NULL CHECK (source_class IN (
        'sec', 'sedar_plus', 'company_ir', 'official_release', 'government_regulatory'
    )),
    accession_number text CHECK (
        accession_number IS NULL OR accession_number ~ '^[0-9]{10}-[0-9]{2}-[0-9]{6}$'
    ),
    source_url text NOT NULL CHECK (
        char_length(source_url) BETWEEN 1 AND 2048 AND source_url ~ '^https://'
    ),
    source_content_sha256 text NOT NULL CHECK (source_content_sha256 ~ '^[0-9a-f]{64}$'),
    published_at timestamptz,
    available_at timestamptz,
    retrieved_at timestamptz NOT NULL,
    extractor_version text NOT NULL CHECK (extractor_version = 'strategic-partnership-v1'),
    schema_version text NOT NULL CHECK (schema_version = '1.0.0'),
    record jsonb NOT NULL,
    CHECK (source_class <> 'sec' OR accession_number IS NOT NULL),
    CHECK (available_at IS NULL OR published_at IS NULL OR available_at >= published_at),
    CHECK (available_at IS NULL OR retrieved_at >= available_at),
    CHECK (available_at IS NOT NULL OR published_at IS NULL OR retrieved_at >= published_at),
    UNIQUE (issuer_cik, category, source_content_sha256, event_fingerprint)
);
CREATE INDEX research_event_disclosures_lookup_idx
    ON research_event_disclosures (
        issuer_cik, category, COALESCE(published_at, retrieved_at), disclosure_id
    );
CREATE INDEX research_event_disclosures_fingerprint_idx
    ON research_event_disclosures (event_fingerprint, fact_fingerprint, disclosure_id);

CREATE TABLE research_event_lineage (
    lineage_id uuid PRIMARY KEY,
    current_disclosure_id uuid NOT NULL REFERENCES research_event_disclosures(disclosure_id),
    prior_related_disclosure_id uuid REFERENCES research_event_disclosures(disclosure_id),
    authoritative_first_known_disclosure_id uuid
        REFERENCES research_event_disclosures(disclosure_id),
    authoritative_first_known_at timestamptz,
    evaluated_at timestamptz NOT NULL,
    disposition text NOT NULL CHECK (disposition IN (
        'NEW_EVENT', 'MATERIAL_UPDATE', 'RECAP_EXISTING_EVENT',
        'DUPLICATE_DISCLOSURE', 'HISTORICAL_CONTEXT', 'UNKNOWN_NOVELTY'
    )),
    reason text NOT NULL CHECK (reason IN (
        'COMPLETE_SEARCH_NO_RELATED_EVENT', 'SUPPORTED_MATERIAL_FACT_CHANGED',
        'SAME_EVENT_NO_NEW_MATERIAL_FACT', 'SAME_SOURCE_DOCUMENT',
        'EXPLICIT_HISTORICAL_CONTEXT', 'PRIOR_SEARCH_INCOMPLETE',
        'AMBIGUOUS_EVENT_RELATIONSHIP'
    )),
    prior_search_complete boolean NOT NULL,
    rule_version text NOT NULL CHECK (rule_version = 'event-novelty-v1'),
    schema_version text NOT NULL CHECK (schema_version = '1.0.0'),
    record jsonb NOT NULL,
    UNIQUE (current_disclosure_id, rule_version),
    CHECK (current_disclosure_id IS DISTINCT FROM prior_related_disclosure_id),
    CHECK (
        (disposition = 'NEW_EVENT' AND reason = 'COMPLETE_SEARCH_NO_RELATED_EVENT'
            AND prior_search_complete AND prior_related_disclosure_id IS NULL)
        OR (disposition = 'MATERIAL_UPDATE' AND reason = 'SUPPORTED_MATERIAL_FACT_CHANGED'
            AND prior_related_disclosure_id IS NOT NULL)
        OR (disposition = 'RECAP_EXISTING_EVENT'
            AND reason = 'SAME_EVENT_NO_NEW_MATERIAL_FACT'
            AND prior_related_disclosure_id IS NOT NULL)
        OR (disposition = 'DUPLICATE_DISCLOSURE' AND reason = 'SAME_SOURCE_DOCUMENT'
            AND prior_related_disclosure_id IS NOT NULL)
        OR (disposition = 'HISTORICAL_CONTEXT' AND reason = 'EXPLICIT_HISTORICAL_CONTEXT')
        OR (disposition = 'UNKNOWN_NOVELTY'
            AND reason IN ('PRIOR_SEARCH_INCOMPLETE', 'AMBIGUOUS_EVENT_RELATIONSHIP'))
    )
);
CREATE INDEX research_event_lineage_result_idx
    ON research_event_lineage (disposition, evaluated_at DESC, lineage_id DESC);

CREATE FUNCTION validate_event_disclosure()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.source_class = 'sec' AND NOT EXISTS (
        SELECT 1 FROM research_candidates c
        WHERE c.accession_number = NEW.accession_number
          AND lpad(c.cik, 10, '0') = NEW.issuer_cik
          AND c.discovered_at <= NEW.retrieved_at
    ) THEN
        RAISE EXCEPTION 'SEC event disclosure lacks its discovered accession and issuer';
    END IF;
    IF NEW.source_class = 'sec'
        AND NEW.source_url !~ '^https://www[.]sec[.]gov/Archives/edgar/data/' THEN
        RAISE EXCEPTION 'SEC event disclosure requires an authoritative archive URL';
    END IF;
    IF NEW.record->>'disclosure_id' IS DISTINCT FROM NEW.disclosure_id::text
        OR NEW.record->>'issuer_cik' IS DISTINCT FROM NEW.issuer_cik
        OR NEW.record->>'issuer_name' IS DISTINCT FROM NEW.issuer_name
        OR NEW.record->>'category' IS DISTINCT FROM NEW.category
        OR NEW.record->>'context' IS DISTINCT FROM NEW.context
        OR NEW.record->>'event_fingerprint' IS DISTINCT FROM NEW.event_fingerprint
        OR NEW.record->>'fact_fingerprint' IS DISTINCT FROM NEW.fact_fingerprint
        OR NEW.record#>>'{source,source_class}' IS DISTINCT FROM NEW.source_class
        OR NEW.record#>>'{source,accession_number}' IS DISTINCT FROM NEW.accession_number
        OR NEW.record#>>'{source,canonical_url}' IS DISTINCT FROM NEW.source_url
        OR NEW.record#>>'{source,source_content_sha256}'
            IS DISTINCT FROM NEW.source_content_sha256
        OR (NEW.record#>>'{source,published_at}')::timestamptz
            IS DISTINCT FROM NEW.published_at
        OR (NEW.record#>>'{source,available_at}')::timestamptz
            IS DISTINCT FROM NEW.available_at
        OR (NEW.record#>>'{source,retrieved_at}')::timestamptz
            IS DISTINCT FROM NEW.retrieved_at
        OR NEW.record->>'extractor_version' IS DISTINCT FROM NEW.extractor_version
        OR NEW.record->>'schema_version' IS DISTINCT FROM NEW.schema_version THEN
        RAISE EXCEPTION 'event disclosure columns do not match the closed record';
    END IF;
    RETURN NEW;
END
$$;

CREATE FUNCTION validate_event_lineage()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    current_issuer text;
    current_category text;
    prior_issuer text;
    prior_category text;
    first_source_published_at timestamptz;
    first_source_hash text;
BEGIN
    SELECT issuer_cik, category INTO current_issuer, current_category
    FROM research_event_disclosures WHERE disclosure_id = NEW.current_disclosure_id;
    IF NEW.prior_related_disclosure_id IS NOT NULL THEN
        SELECT issuer_cik, category INTO prior_issuer, prior_category
        FROM research_event_disclosures WHERE disclosure_id = NEW.prior_related_disclosure_id;
        IF prior_issuer IS DISTINCT FROM current_issuer
            OR prior_category IS DISTINCT FROM current_category THEN
            RAISE EXCEPTION 'event lineage prior disclosure has a different issuer or category';
        END IF;
    END IF;
    IF NEW.authoritative_first_known_disclosure_id IS NOT NULL THEN
        SELECT published_at, source_content_sha256
            INTO first_source_published_at, first_source_hash
        FROM research_event_disclosures
        WHERE disclosure_id = NEW.authoritative_first_known_disclosure_id
          AND issuer_cik = current_issuer AND category = current_category;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'event first-known disclosure has a different issuer or category';
        END IF;
        IF NEW.authoritative_first_known_at IS DISTINCT FROM first_source_published_at THEN
            RAISE EXCEPTION 'event first-known time must match the source or remain unknown';
        END IF;
        IF NEW.record#>>'{authoritative_first_known_disclosure,source_content_sha256}'
            IS DISTINCT FROM first_source_hash THEN
            RAISE EXCEPTION 'event first-known source does not match the closed record';
        END IF;
    ELSIF NEW.authoritative_first_known_at IS NOT NULL THEN
        RAISE EXCEPTION 'event first-known time lacks an authoritative source';
    ELSIF NEW.record->'authoritative_first_known_disclosure'
        IS DISTINCT FROM 'null'::jsonb THEN
        RAISE EXCEPTION 'event first-known record lacks its relational source';
    END IF;
    IF NEW.record->>'lineage_id' IS DISTINCT FROM NEW.lineage_id::text
        OR NEW.record#>>'{current_disclosure,disclosure_id}'
            IS DISTINCT FROM NEW.current_disclosure_id::text
        OR NEW.record#>>'{prior_related_disclosure,disclosure_id}'
            IS DISTINCT FROM NEW.prior_related_disclosure_id::text
        OR (NEW.record->>'authoritative_first_known_at')::timestamptz
            IS DISTINCT FROM NEW.authoritative_first_known_at
        OR (NEW.record->>'evaluated_at')::timestamptz IS DISTINCT FROM NEW.evaluated_at
        OR NEW.record->>'disposition' IS DISTINCT FROM NEW.disposition
        OR NEW.record->>'reason' IS DISTINCT FROM NEW.reason
        OR (NEW.record->>'prior_search_complete')::boolean
            IS DISTINCT FROM NEW.prior_search_complete
        OR NEW.record->>'rule_version' IS DISTINCT FROM NEW.rule_version
        OR NEW.record->>'schema_version' IS DISTINCT FROM NEW.schema_version THEN
        RAISE EXCEPTION 'event lineage columns do not match the closed record';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER research_event_disclosures_validate
    BEFORE INSERT ON research_event_disclosures
    FOR EACH ROW EXECUTE FUNCTION validate_event_disclosure();
CREATE TRIGGER research_event_lineage_validate
    BEFORE INSERT ON research_event_lineage
    FOR EACH ROW EXECUTE FUNCTION validate_event_lineage();
CREATE TRIGGER research_event_disclosures_no_update_delete
    BEFORE UPDATE OR DELETE ON research_event_disclosures
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_event_disclosures_no_truncate
    BEFORE TRUNCATE ON research_event_disclosures
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_event_lineage_no_update_delete
    BEFORE UPDATE OR DELETE ON research_event_lineage
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_event_lineage_no_truncate
    BEFORE TRUNCATE ON research_event_lineage
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_event_novelty_state_no_update_delete
    BEFORE UPDATE OR DELETE ON research_event_novelty_state
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_event_novelty_state_no_truncate
    BEFORE TRUNCATE ON research_event_novelty_state
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();

INSERT INTO schema_migrations (version) VALUES ('0018_event_novelty_lineage');

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kalki_app') THEN
        EXECUTE 'GRANT SELECT ON research_event_novelty_state TO kalki_app';
        EXECUTE 'GRANT SELECT, INSERT ON research_event_disclosures, research_event_lineage TO kalki_app';
    END IF;
END
$$;

COMMIT;
