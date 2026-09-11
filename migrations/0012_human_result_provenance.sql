BEGIN;

ALTER TABLE research_human_results
    ADD COLUMN schema_version text,
    ADD COLUMN source_status text,
    ADD COLUMN accession_number text,
    ADD COLUMN analyst_attempt_ids uuid[],
    ADD COLUMN delivery_channel_id text;

ALTER TABLE research_human_results
    ADD CONSTRAINT research_human_results_schema_version_check
        CHECK (schema_version IS NULL OR schema_version = '2.0.0'),
    ADD CONSTRAINT research_human_results_source_status_check
        CHECK (source_status IS NULL OR source_status IN (
            'resolved', 'unresolved', 'retrieval_failed'
        )),
    ADD CONSTRAINT research_human_results_accession_check
        CHECK (accession_number IS NULL OR accession_number ~ '^\d{10}-\d{2}-\d{6}$'),
    ADD CONSTRAINT research_human_results_attempt_count_check
        CHECK (analyst_attempt_ids IS NULL OR cardinality(analyst_attempt_ids) <= 4),
    ADD CONSTRAINT research_human_results_delivery_channel_check
        CHECK (delivery_channel_id IS NULL OR delivery_channel_id ~ '^\d{17,20}$');

CREATE FUNCTION validate_human_result_v2()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    referenced_attempt_id uuid;
BEGIN
    IF NEW.schema_version <> '2.0.0'
        OR NEW.source_status IS NULL
        OR NEW.analyst_attempt_ids IS NULL
        OR NEW.delivery_channel_id IS NULL THEN
        RAISE EXCEPTION 'future human results require complete version 2 provenance columns';
    END IF;
    IF NEW.record->>'version' <> 'human-research-v2'
        OR NEW.record->>'result_id' <> NEW.result_id::text
        OR NEW.record->>'lead_id' <> NEW.lead_id::text
        OR NEW.record->'source'->>'status' <> NEW.source_status
        OR NEW.record->>'delivery_channel_id' <> NEW.delivery_channel_id THEN
        RAISE EXCEPTION 'human result columns do not match the closed version 2 record';
    END IF;
    IF NEW.source_status = 'resolved' THEN
        IF NEW.accession_number IS NULL
            OR NEW.record->'source'->>'accession_number' <> NEW.accession_number THEN
            RAISE EXCEPTION 'resolved human result requires matching accession lineage';
        END IF;
    ELSIF NEW.accession_number IS NOT NULL THEN
        RAISE EXCEPTION 'unresolved human result cannot claim an accession';
    END IF;
    IF cardinality(NEW.analyst_attempt_ids) <> (
        SELECT count(DISTINCT receipt->'start'->>'attempt_id')
        FROM jsonb_array_elements(NEW.record->'analyst_attempt_receipts') AS receipts(receipt)
    ) THEN
        RAISE EXCEPTION 'human result analyst receipt count is inconsistent';
    END IF;
    FOREACH referenced_attempt_id IN ARRAY NEW.analyst_attempt_ids LOOP
        IF NOT NEW.record->'analyst_attempt_receipts' @> jsonb_build_array(
            jsonb_build_object(
                'start', jsonb_build_object('attempt_id', referenced_attempt_id::text)
            )
        ) THEN
            RAISE EXCEPTION 'human result analyst receipt IDs are inconsistent';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM research_analyst_attempts
            WHERE research_analyst_attempts.attempt_id = referenced_attempt_id
              AND lead_id = NEW.lead_id
              AND origin = 'human'
              AND state = 'completed'
        ) THEN
            RAISE EXCEPTION 'human result references an absent or incomplete analyst attempt';
        END IF;
    END LOOP;
    RETURN NEW;
END
$$;

CREATE TRIGGER research_human_results_require_v2
    BEFORE INSERT ON research_human_results
    FOR EACH ROW EXECUTE FUNCTION validate_human_result_v2();

INSERT INTO schema_migrations (version) VALUES ('0012_human_result_provenance');

COMMIT;
