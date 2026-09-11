BEGIN;

CREATE TABLE research_contradiction_receipts (
    receipt_id uuid PRIMARY KEY,
    claim_id uuid NOT NULL,
    canonical_cik text NOT NULL CHECK (canonical_cik ~ '^\d{10}$'),
    family text NOT NULL CHECK (family IN ('LIQUIDITY', 'DILUTION', 'INSIDER')),
    predicate text NOT NULL CHECK (predicate IN (
        'CASH_AT_LEAST_CURRENT_LIABILITIES',
        'DILUTION_EXPOSURE_PRESENT',
        'NET_INSIDER_ACQUISITION'
    )),
    asserted_truth boolean NOT NULL,
    comparison_scope_id text NOT NULL CHECK (
        length(btrim(comparison_scope_id)) BETWEEN 1 AND 255
    ),
    claim_as_of_date date NOT NULL,
    claim_available_at timestamptz NOT NULL,
    claim_retrieved_at timestamptz NOT NULL,
    knowledge_cutoff_at timestamptz NOT NULL,
    disposition text NOT NULL CHECK (disposition IN (
        'SUPPORTED', 'CONFLICTED', 'INSUFFICIENT', 'NOT_APPLICABLE'
    )),
    observed_truth boolean,
    reason text NOT NULL CHECK (reason IN (
        'EXACT_FACTS_SUPPORT_CLAIM', 'EXACT_FACTS_CONFLICT_WITH_CLAIM',
        'REQUIRED_FACTS_MISSING', 'FACT_PERIODS_INCOMPARABLE',
        'PLANNED_SALE_IS_NOT_EXECUTED_TRANSACTION'
    )),
    fact_count integer NOT NULL CHECK (fact_count BETWEEN 0 AND 8),
    consumed_fact_count integer NOT NULL CHECK (consumed_fact_count BETWEEN 0 AND 8),
    receipt_sha256 text NOT NULL UNIQUE CHECK (receipt_sha256 ~ '^[0-9a-f]{64}$'),
    rule_version text NOT NULL CHECK (rule_version = 'deterministic-contradiction-v2'),
    record jsonb NOT NULL CHECK (pg_column_size(record) <= 100000),
    CHECK (claim_retrieved_at >= claim_available_at),
    CHECK (knowledge_cutoff_at >= claim_available_at),
    CHECK (knowledge_cutoff_at >= claim_retrieved_at),
    CHECK (claim_as_of_date <= knowledge_cutoff_at::date),
    CHECK (
        (family = 'LIQUIDITY' AND predicate = 'CASH_AT_LEAST_CURRENT_LIABILITIES')
        OR (family = 'DILUTION' AND predicate = 'DILUTION_EXPOSURE_PRESENT')
        OR (family = 'INSIDER' AND predicate = 'NET_INSIDER_ACQUISITION')
    ),
    CHECK (
        (disposition = 'SUPPORTED' AND observed_truth IS NOT NULL
            AND reason = 'EXACT_FACTS_SUPPORT_CLAIM')
        OR (disposition = 'CONFLICTED' AND observed_truth IS NOT NULL
            AND reason = 'EXACT_FACTS_CONFLICT_WITH_CLAIM')
        OR (disposition = 'INSUFFICIENT' AND observed_truth IS NULL
            AND reason IN ('REQUIRED_FACTS_MISSING', 'FACT_PERIODS_INCOMPARABLE'))
        OR (disposition = 'NOT_APPLICABLE' AND observed_truth IS NULL
            AND reason = 'PLANNED_SALE_IS_NOT_EXECUTED_TRANSACTION')
    )
);

CREATE INDEX research_contradiction_receipts_issuer_cutoff_idx
    ON research_contradiction_receipts (
        canonical_cik, knowledge_cutoff_at DESC, receipt_id
    );

CREATE FUNCTION validate_contradiction_receipt()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    fact jsonb;
    observed_from_record boolean;
    top_keys text[];
    claim_keys text[];
    fact_keys text[];
BEGIN
    SELECT array_agg(key ORDER BY key) INTO top_keys
    FROM jsonb_object_keys(NEW.record) AS key;
    SELECT array_agg(key ORDER BY key) INTO claim_keys
    FROM jsonb_object_keys(NEW.record->'claim') AS key;
    IF top_keys IS DISTINCT FROM ARRAY[
            'claim', 'consumed_fact_ids', 'disposition', 'facts',
            'knowledge_cutoff_at', 'observed_truth', 'reason', 'receipt_id',
            'receipt_sha256', 'rule_version'
        ]::text[]
        OR claim_keys IS DISTINCT FROM ARRAY[
            'as_of_date', 'asserted_truth', 'available_at', 'claim_id',
            'comparison_scope_id', 'evidence_ids', 'family', 'issuer_cik',
            'predicate', 'retrieved_at', 'source_content_sha256', 'source_record_id'
        ]::text[] THEN
        RAISE EXCEPTION 'contradiction receipt does not use the closed JSON schema';
    END IF;

    IF NEW.record->'observed_truth' = 'null'::jsonb THEN
        observed_from_record := NULL;
    ELSE
        observed_from_record := (NEW.record->>'observed_truth')::boolean;
    END IF;
    IF NEW.record->>'receipt_id' IS DISTINCT FROM NEW.receipt_id::text
        OR NEW.record->'claim'->>'claim_id' IS DISTINCT FROM NEW.claim_id::text
        OR lpad(NEW.record->'claim'->>'issuer_cik', 10, '0')
            IS DISTINCT FROM NEW.canonical_cik
        OR NEW.record->'claim'->>'family' IS DISTINCT FROM NEW.family
        OR NEW.record->'claim'->>'predicate' IS DISTINCT FROM NEW.predicate
        OR (NEW.record->'claim'->>'asserted_truth')::boolean
            IS DISTINCT FROM NEW.asserted_truth
        OR NEW.record->'claim'->>'comparison_scope_id'
            IS DISTINCT FROM NEW.comparison_scope_id
        OR (NEW.record->'claim'->>'as_of_date')::date
            IS DISTINCT FROM NEW.claim_as_of_date
        OR (NEW.record->'claim'->>'available_at')::timestamptz
            IS DISTINCT FROM NEW.claim_available_at
        OR (NEW.record->'claim'->>'retrieved_at')::timestamptz
            IS DISTINCT FROM NEW.claim_retrieved_at
        OR (NEW.record->>'knowledge_cutoff_at')::timestamptz
            IS DISTINCT FROM NEW.knowledge_cutoff_at
        OR NEW.record->>'disposition' IS DISTINCT FROM NEW.disposition
        OR observed_from_record IS DISTINCT FROM NEW.observed_truth
        OR NEW.record->>'reason' IS DISTINCT FROM NEW.reason
        OR jsonb_array_length(NEW.record->'facts') IS DISTINCT FROM NEW.fact_count
        OR jsonb_array_length(NEW.record->'consumed_fact_ids')
            IS DISTINCT FROM NEW.consumed_fact_count
        OR NEW.record->>'receipt_sha256' IS DISTINCT FROM NEW.receipt_sha256
        OR NEW.record->>'rule_version' IS DISTINCT FROM NEW.rule_version
        OR jsonb_array_length(NEW.record->'claim'->'evidence_ids') NOT BETWEEN 1 AND 16 THEN
        RAISE EXCEPTION 'contradiction receipt columns do not match the closed record';
    END IF;

    IF (SELECT count(DISTINCT value->>'fact_id')
        FROM jsonb_array_elements(NEW.record->'facts')) <> NEW.fact_count
        OR (SELECT count(DISTINCT value->>'kind')
            FROM jsonb_array_elements(NEW.record->'facts')) <> NEW.fact_count
        OR (SELECT count(DISTINCT value)
            FROM jsonb_array_elements_text(NEW.record->'consumed_fact_ids'))
            <> NEW.consumed_fact_count
        OR EXISTS (
            SELECT 1 FROM jsonb_array_elements_text(
                NEW.record->'consumed_fact_ids'
            ) AS consumed(value)
            WHERE NOT EXISTS (
                SELECT 1 FROM jsonb_array_elements(NEW.record->'facts') AS item(fact)
                WHERE item.fact->>'fact_id' = consumed.value
            )
        ) THEN
        RAISE EXCEPTION 'contradiction receipt fact identities do not reconcile';
    END IF;

    FOR fact IN SELECT value FROM jsonb_array_elements(NEW.record->'facts')
    LOOP
        SELECT array_agg(key ORDER BY key) INTO fact_keys
        FROM jsonb_object_keys(fact) AS key;
        IF fact_keys IS DISTINCT FROM ARRAY[
                'as_of_date', 'available_at', 'comparison_scope_id', 'currency',
                'evidence_ids', 'fact_id', 'issuer_cik', 'kind', 'retrieved_at',
                'source_content_sha256', 'source_record_id', 'unit', 'value'
            ]::text[]
            OR lpad(fact->>'issuer_cik', 10, '0') IS DISTINCT FROM NEW.canonical_cik
            OR fact->>'comparison_scope_id' IS DISTINCT FROM NEW.comparison_scope_id
            OR (fact->>'available_at')::timestamptz > NEW.knowledge_cutoff_at
            OR (fact->>'retrieved_at')::timestamptz > NEW.knowledge_cutoff_at
            OR (fact->>'retrieved_at')::timestamptz < (fact->>'available_at')::timestamptz
            OR (fact->>'as_of_date')::date > NEW.claim_as_of_date
            OR jsonb_array_length(fact->'evidence_ids') NOT BETWEEN 1 AND 16
            OR fact->>'kind' NOT IN (
                'CASH', 'CURRENT_LIABILITIES', 'SHARES_OUTSTANDING_PRIOR',
                'SHARES_OUTSTANDING_CURRENT', 'REGISTERED_SHARES', 'ISSUABLE_SHARES',
                'DILUTIVE_INSTRUMENT_COUNT', 'INSIDER_ACQUIRED_SHARES',
                'INSIDER_DISPOSED_SHARES', 'FORM_144_PLANNED_SALE_SHARES'
            )
            OR fact->>'unit' NOT IN ('CURRENCY', 'SHARES', 'COUNT')
            OR (
                fact->>'kind' IN ('CASH', 'CURRENT_LIABILITIES')
                AND (fact->>'unit' <> 'CURRENCY' OR fact->'currency' = 'null'::jsonb)
            )
            OR (
                fact->>'kind' NOT IN ('CASH', 'CURRENT_LIABILITIES')
                AND (fact->>'unit' = 'CURRENCY' OR fact->'currency' <> 'null'::jsonb)
            ) THEN
            RAISE EXCEPTION 'contradiction fact violates closed point-in-time lineage';
        END IF;
    END LOOP;
    RETURN NEW;
END
$$;

CREATE TRIGGER research_contradiction_receipts_validate
    BEFORE INSERT ON research_contradiction_receipts
    FOR EACH ROW EXECUTE FUNCTION validate_contradiction_receipt();
CREATE TRIGGER research_contradiction_receipts_no_update_delete
    BEFORE UPDATE OR DELETE ON research_contradiction_receipts
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_contradiction_receipts_no_truncate
    BEFORE TRUNCATE ON research_contradiction_receipts
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();

INSERT INTO schema_migrations (version) VALUES ('0026_contradiction_receipts');

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kalki_app') THEN
        EXECUTE 'GRANT SELECT, INSERT ON research_contradiction_receipts TO kalki_app';
    END IF;
END
$$;

COMMIT;
