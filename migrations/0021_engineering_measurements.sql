BEGIN;

CREATE TABLE research_engineering_measurement_state (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    started_at timestamptz NOT NULL,
    measurement_version text NOT NULL CHECK (measurement_version = '1.0.0')
);
INSERT INTO research_engineering_measurement_state (started_at, measurement_version)
VALUES (clock_timestamp(), '1.0.0');

CREATE TABLE research_engineering_metric_definitions (
    metric_name text NOT NULL,
    metric_version text NOT NULL CHECK (metric_version = '1.0.0'),
    shape text NOT NULL CHECK (shape IN ('ratio', 'distribution', 'gauge')),
    unit text NOT NULL CHECK (unit IN (
        'fraction', 'calls_per_filing', 'characters', 'tokens', 'milliseconds',
        'count', 'seconds', 'millicelsius', 'load_per_cpu_milli', 'bytes'
    )),
    bounded_fraction boolean NOT NULL,
    definition_code text NOT NULL CHECK (definition_code ~ '^[A-Z0-9_]{3,96}$'),
    definition_sha256 text NOT NULL CHECK (definition_sha256 ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY (metric_name, metric_version),
    UNIQUE (definition_sha256),
    CHECK ((unit = 'fraction') = bounded_fraction),
    CHECK ((shape = 'ratio') = (unit IN ('fraction', 'calls_per_filing')))
);

INSERT INTO research_engineering_metric_definitions (
    metric_name, metric_version, shape, unit, bounded_fraction,
    definition_code, definition_sha256
) VALUES
    ('actual_input_tokens', '1.0.0', 'distribution', 'tokens', false,
     'PROVIDER_REPORTED_PROMPT_TOKENS_PER_QWEN_CALL',
     'fc3e90ef20567d6b063811c1c48824596fe4662b4f2a84cc5fad2a5feabd0cd9'),
    ('analyst_latency_ms', '1.0.0', 'distribution', 'milliseconds', false,
     'COMPLETED_ANALYST_CALL_LATENCY_MILLISECONDS',
     '1d2bf9275770307b3a5a10ca98c8ab9d83a8402d6c884b6ba97b9cbc4c676f85'),
    ('analyst_timeout_rate', '1.0.0', 'ratio', 'fraction', true,
     'TIMEOUT_ANALYST_CALLS_OVER_COMPLETED_ANALYST_CALLS',
     '4839f845dcdb6cabe6e559ff121c0675ad6d83e1c8436950a7223410cff46e01'),
    ('authoritative_disclosure_to_alert_ms', '1.0.0', 'distribution', 'milliseconds', false,
     'AUTHORITATIVE_FIRST_KNOWN_TO_SENT_ALERT_MILLISECONDS',
     '3aaa3bbf473e24736917b06baa1a9d822883ba55e2ac254526560ead54fa41bc'),
    ('authoritative_disclosure_to_discovery_ms', '1.0.0', 'distribution', 'milliseconds', false,
     'AUTHORITATIVE_FIRST_KNOWN_TO_SEC_DISCOVERY_MILLISECONDS',
     '68faef9137a797f68634b47b8e7b8ae2b67da6798b119af21ef54c65273756ec'),
    ('cpu_load_per_cpu_milli', '1.0.0', 'gauge', 'load_per_cpu_milli', false,
     'HOST_ONE_MINUTE_LOAD_PER_LOGICAL_CPU_MILLI',
     'c4862c0c889ea85ff206f2391443bc0b20b06167a3809285ab6846af5b1d4b62'),
    ('cpu_temperature_millicelsius', '1.0.0', 'gauge', 'millicelsius', false,
     'HOST_CPU_PACKAGE_TEMPERATURE_MILLICELSIUS',
     'f6dd6614a3e9ebd65b4d65004d6b5bd3a26f1ebbc4907bda9c867681efafd9f8'),
    ('discord_exact_once_rate', '1.0.0', 'ratio', 'fraction', true,
     'UNIQUE_BRIEFS_WITH_ONE_SENT_DELIVERY_OVER_DELIVERY_ELIGIBLE_BRIEFS',
     '6659dcec74c406ae132621a5134861b20df3ebece761f01a01ac139bdcbaf6d6'),
    ('discovery_to_publication_ms', '1.0.0', 'distribution', 'milliseconds', false,
     'SEC_DISCOVERY_TO_IMMUTABLE_PUBLICATION_MILLISECONDS',
     '3419b04960e606cec1e8d9582f9598494e7cc68c3db63e03086178eb5954df15'),
    ('evidence_characters', '1.0.0', 'distribution', 'characters', false,
     'BOUNDED_EVIDENCE_CHARACTERS_PER_QWEN_CALL',
     '8dc72949ed74efbbd4f3b5b026d4502917a445682174daecbd84365443cc84aa'),
    ('false_new_publication_rate', '1.0.0', 'ratio', 'fraction', true,
     'RECAP_OR_DUPLICATE_PUBLICATIONS_OVER_REVIEWED_PUBLICATIONS',
     '53297cf4553de4c1d825d76530442f42b3d2b34d23067a39718d7e5cca83f76b'),
    ('fresh_event_precision', '1.0.0', 'ratio', 'fraction', true,
     'CONFIRMED_FRESH_EVENTS_OVER_PUBLISHED_FRESH_EVENTS',
     'c6be79a66e662731366cc9325544bfd57e1f8276ed5b48af4056327c8f158f9a'),
    ('material_update_recall', '1.0.0', 'ratio', 'fraction', true,
     'DETECTED_MATERIAL_UPDATES_OVER_LABELED_MATERIAL_UPDATES',
     '65751687f94534138922db557054ff63ec57b3fd36f44fcf624c23f295c440be'),
    ('memory_available_bytes', '1.0.0', 'gauge', 'bytes', false,
     'HOST_AVAILABLE_MEMORY_BYTES',
     'c8795977b5ee5e10f2fef10515d26a894b2cd1928a399768a5616d37f25fd5c9'),
    ('publication_exact_once_rate', '1.0.0', 'ratio', 'fraction', true,
     'UNIQUE_QUALIFIED_ACCESSIONS_WITH_ONE_BRIEF_OVER_QUALIFIED_ACCESSIONS',
     '0222c5de6dff67e2a0277781f790036aa43455e51211c0c31707a1a4740113de'),
    ('queue_depth', '1.0.0', 'gauge', 'count', false,
     'CLAIMABLE_DEEP_ANALYSIS_QUEUE_DEPTH_AT_OBSERVATION',
     '9af0fd33b1e9328800fb6668f730ddef3524d337f508da53d0099f505e5433b7'),
    ('queue_oldest_age_seconds', '1.0.0', 'gauge', 'seconds', false,
     'OLDEST_CLAIMABLE_DEEP_ANALYSIS_QUEUE_AGE_SECONDS',
     '3b66bcda82d960ff811153a5b1ae15ef2a13a6898c17a95a0a68181feeb0795c'),
    ('qwen_calls_per_filing', '1.0.0', 'ratio', 'calls_per_filing', false,
     'COMPLETED_QWEN_CALLS_OVER_DEEP_ANALYZED_FILINGS',
     'ee8b468d3a4b7d6ba01710b7e26165076d842f0bdaa64b7542bb2409872bd49e'),
    ('recap_suppression_accuracy', '1.0.0', 'ratio', 'fraction', true,
     'CORRECTLY_SUPPRESSED_RECAPS_OVER_LABELED_RECAPS',
     'abcb86de91889f30d23c5011f2ecd9db9a7e0aa73de7088594b75a10dc3b01be'),
    ('swap_used_bytes', '1.0.0', 'gauge', 'bytes', false,
     'HOST_SWAP_USED_BYTES',
     '6583cc601d84b46eca082b4ddf2f06f478dfdc26211c39d33a582f0854a9d869');

CREATE TABLE research_engineering_measurements (
    receipt_id uuid PRIMARY KEY,
    metric_name text NOT NULL,
    metric_version text NOT NULL CHECK (metric_version = '1.0.0'),
    definition_sha256 text NOT NULL CHECK (definition_sha256 ~ '^[0-9a-f]{64}$'),
    window_started_at timestamptz NOT NULL,
    window_ended_at timestamptz NOT NULL,
    measured_at timestamptz NOT NULL,
    availability text NOT NULL CHECK (availability IN ('available', 'partial', 'unavailable')),
    unavailable_reason text CHECK (unavailable_reason IS NULL OR unavailable_reason IN (
        'no_observations', 'telemetry_epoch_incomplete', 'reference_labels_unavailable',
        'actual_token_counts_unavailable', 'sensor_unavailable',
        'authoritative_first_known_unavailable', 'publication_unavailable',
        'alert_unavailable'
    )),
    coverage_started_at timestamptz,
    sample_count bigint NOT NULL CHECK (sample_count BETWEEN 0 AND 1000000000000000000),
    numerator bigint CHECK (numerator BETWEEN 0 AND 1000000000000000000),
    denominator bigint CHECK (denominator BETWEEN 1 AND 1000000000000000000),
    scaled_value_millionths bigint CHECK (
        scaled_value_millionths BETWEEN 0 AND 1000000000000000000
    ),
    minimum_value bigint CHECK (minimum_value BETWEEN 0 AND 1000000000000000000),
    p50_value bigint CHECK (p50_value BETWEEN 0 AND 1000000000000000000),
    p90_value bigint CHECK (p90_value BETWEEN 0 AND 1000000000000000000),
    p95_value bigint CHECK (p95_value BETWEEN 0 AND 1000000000000000000),
    maximum_value bigint CHECK (maximum_value BETWEEN 0 AND 1000000000000000000),
    gauge_value bigint CHECK (gauge_value BETWEEN 0 AND 1000000000000000000),
    record jsonb NOT NULL,
    FOREIGN KEY (metric_name, metric_version)
        REFERENCES research_engineering_metric_definitions(metric_name, metric_version),
    CHECK (window_ended_at >= window_started_at),
    CHECK (measured_at >= window_ended_at),
    CHECK (
        (availability = 'unavailable' AND unavailable_reason IS NOT NULL
            AND coverage_started_at IS NULL AND sample_count = 0)
        OR (availability = 'available' AND unavailable_reason IS NULL
            AND coverage_started_at IS NULL)
        OR (availability = 'partial' AND unavailable_reason IS NULL
            AND coverage_started_at > window_started_at
            AND coverage_started_at <= window_ended_at)
    )
);
CREATE INDEX research_engineering_measurements_window_idx
    ON research_engineering_measurements (
        metric_name, window_ended_at DESC, measured_at DESC, receipt_id DESC
    );

CREATE TABLE research_filing_latency_receipts (
    receipt_id uuid PRIMARY KEY,
    accession_number text NOT NULL REFERENCES research_candidates(accession_number),
    event_lineage_id uuid REFERENCES research_event_lineage(lineage_id),
    authoritative_first_known_at timestamptz,
    discovered_at timestamptz NOT NULL,
    published_at timestamptz,
    alerted_at timestamptz,
    first_known_to_discovery_ms bigint CHECK (
        first_known_to_discovery_ms BETWEEN 0 AND 1000000000000000000
    ),
    first_known_to_discovery_reason text CHECK (
        first_known_to_discovery_reason IS NULL
        OR first_known_to_discovery_reason = 'authoritative_first_known_unavailable'
    ),
    discovery_to_publication_ms bigint CHECK (
        discovery_to_publication_ms BETWEEN 0 AND 1000000000000000000
    ),
    discovery_to_publication_reason text CHECK (
        discovery_to_publication_reason IS NULL
        OR discovery_to_publication_reason = 'publication_unavailable'
    ),
    first_known_to_alert_ms bigint CHECK (
        first_known_to_alert_ms BETWEEN 0 AND 1000000000000000000
    ),
    first_known_to_alert_reason text CHECK (first_known_to_alert_reason IS NULL OR
        first_known_to_alert_reason IN (
            'authoritative_first_known_unavailable', 'alert_unavailable'
        )
    ),
    measured_at timestamptz NOT NULL,
    measurement_version text NOT NULL CHECK (measurement_version = '1.0.0'),
    record jsonb NOT NULL,
    UNIQUE NULLS NOT DISTINCT (
        accession_number, event_lineage_id, published_at, alerted_at, measurement_version
    ),
    CHECK (authoritative_first_known_at IS NULL OR event_lineage_id IS NOT NULL),
    CHECK (authoritative_first_known_at IS NULL OR authoritative_first_known_at <= discovered_at),
    CHECK (published_at IS NULL OR published_at >= discovered_at),
    CHECK (alerted_at IS NULL OR (published_at IS NOT NULL AND alerted_at >= published_at)),
    CHECK (measured_at >= COALESCE(alerted_at, published_at, discovered_at)),
    CHECK ((first_known_to_discovery_ms IS NULL) <> (first_known_to_discovery_reason IS NULL)),
    CHECK ((discovery_to_publication_ms IS NULL) <> (discovery_to_publication_reason IS NULL)),
    CHECK ((first_known_to_alert_ms IS NULL) <> (first_known_to_alert_reason IS NULL))
);
CREATE INDEX research_filing_latency_receipts_time_idx
    ON research_filing_latency_receipts (measured_at DESC, receipt_id DESC);

CREATE FUNCTION validate_engineering_measurement()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    definition research_engineering_metric_definitions%ROWTYPE;
    has_values boolean;
BEGIN
    IF NEW.record - ARRAY[
        'receipt_id', 'metric_name', 'definition_sha256', 'window_started_at',
        'window_ended_at', 'measured_at', 'availability', 'unavailable_reason',
        'coverage_started_at', 'sample_count', 'numerator', 'denominator',
        'scaled_value_millionths', 'minimum_value', 'p50_value', 'p90_value',
        'p95_value', 'maximum_value', 'gauge_value', 'measurement_version'
    ] <> '{}'::jsonb THEN
        RAISE EXCEPTION 'engineering measurement contains fields outside the closed contract';
    END IF;
    SELECT * INTO definition FROM research_engineering_metric_definitions
    WHERE metric_name = NEW.metric_name AND metric_version = NEW.metric_version;
    IF NOT FOUND OR definition.definition_sha256 IS DISTINCT FROM NEW.definition_sha256 THEN
        RAISE EXCEPTION 'engineering measurement definition does not reconcile';
    END IF;
    has_values := NEW.numerator IS NOT NULL OR NEW.denominator IS NOT NULL
        OR NEW.scaled_value_millionths IS NOT NULL OR NEW.minimum_value IS NOT NULL
        OR NEW.p50_value IS NOT NULL OR NEW.p90_value IS NOT NULL
        OR NEW.p95_value IS NOT NULL OR NEW.maximum_value IS NOT NULL
        OR NEW.gauge_value IS NOT NULL;
    IF NEW.availability = 'unavailable' THEN
        IF has_values THEN
            RAISE EXCEPTION 'unavailable engineering measurement cannot retain a value';
        END IF;
        IF NEW.unavailable_reason NOT IN ('no_observations', 'telemetry_epoch_incomplete')
            AND NOT (
                NEW.unavailable_reason = 'reference_labels_unavailable'
                AND NEW.metric_name IN (
                    'false_new_publication_rate', 'recap_suppression_accuracy',
                    'material_update_recall', 'fresh_event_precision'
                )
            )
            AND NOT (
                NEW.unavailable_reason = 'actual_token_counts_unavailable'
                AND NEW.metric_name = 'actual_input_tokens'
            )
            AND NOT (
                NEW.unavailable_reason = 'sensor_unavailable'
                AND NEW.metric_name IN (
                    'cpu_temperature_millicelsius', 'cpu_load_per_cpu_milli',
                    'memory_available_bytes', 'swap_used_bytes'
                )
            )
            AND NOT (
                NEW.unavailable_reason = 'authoritative_first_known_unavailable'
                AND NEW.metric_name IN (
                    'authoritative_disclosure_to_discovery_ms',
                    'authoritative_disclosure_to_alert_ms'
                )
            )
            AND NOT (
                NEW.unavailable_reason = 'publication_unavailable'
                AND NEW.metric_name = 'discovery_to_publication_ms'
            )
            AND NOT (
                NEW.unavailable_reason = 'alert_unavailable'
                AND NEW.metric_name = 'authoritative_disclosure_to_alert_ms'
            ) THEN
            RAISE EXCEPTION 'unavailable reason is invalid for this engineering metric';
        END IF;
    ELSIF definition.shape = 'ratio' THEN
        IF NEW.numerator IS NULL OR NEW.denominator IS NULL
            OR NEW.sample_count <> NEW.denominator
            OR NEW.scaled_value_millionths <> NEW.numerator * 1000000 / NEW.denominator
            OR (definition.bounded_fraction AND NEW.numerator > NEW.denominator)
            OR NEW.minimum_value IS NOT NULL OR NEW.p50_value IS NOT NULL
            OR NEW.p90_value IS NOT NULL OR NEW.p95_value IS NOT NULL
            OR NEW.maximum_value IS NOT NULL OR NEW.gauge_value IS NOT NULL THEN
            RAISE EXCEPTION 'engineering ratio measurement has an invalid shape';
        END IF;
    ELSIF definition.shape = 'distribution' THEN
        IF NEW.sample_count < 1 OR NEW.minimum_value IS NULL OR NEW.p50_value IS NULL
            OR NEW.p90_value IS NULL OR NEW.p95_value IS NULL OR NEW.maximum_value IS NULL
            OR NOT (NEW.minimum_value <= NEW.p50_value AND NEW.p50_value <= NEW.p90_value
                AND NEW.p90_value <= NEW.p95_value AND NEW.p95_value <= NEW.maximum_value)
            OR NEW.numerator IS NOT NULL OR NEW.denominator IS NOT NULL
            OR NEW.scaled_value_millionths IS NOT NULL OR NEW.gauge_value IS NOT NULL THEN
            RAISE EXCEPTION 'engineering distribution measurement has an invalid shape';
        END IF;
    ELSE
        IF NEW.window_started_at <> NEW.window_ended_at OR NEW.sample_count <> 1
            OR NEW.gauge_value IS NULL OR NEW.numerator IS NOT NULL
            OR NEW.denominator IS NOT NULL OR NEW.scaled_value_millionths IS NOT NULL
            OR NEW.minimum_value IS NOT NULL OR NEW.p50_value IS NOT NULL
            OR NEW.p90_value IS NOT NULL OR NEW.p95_value IS NOT NULL
            OR NEW.maximum_value IS NOT NULL THEN
            RAISE EXCEPTION 'engineering gauge measurement has an invalid shape';
        END IF;
    END IF;
    IF NEW.record->>'receipt_id' IS DISTINCT FROM NEW.receipt_id::text
        OR NEW.record->>'metric_name' IS DISTINCT FROM NEW.metric_name
        OR NEW.record->>'definition_sha256' IS DISTINCT FROM NEW.definition_sha256
        OR (NEW.record->>'window_started_at')::timestamptz IS DISTINCT FROM NEW.window_started_at
        OR (NEW.record->>'window_ended_at')::timestamptz IS DISTINCT FROM NEW.window_ended_at
        OR (NEW.record->>'measured_at')::timestamptz IS DISTINCT FROM NEW.measured_at
        OR NEW.record->>'availability' IS DISTINCT FROM NEW.availability
        OR NEW.record->>'unavailable_reason' IS DISTINCT FROM NEW.unavailable_reason
        OR (NEW.record->>'coverage_started_at')::timestamptz IS DISTINCT FROM NEW.coverage_started_at
        OR (NEW.record->>'sample_count')::bigint IS DISTINCT FROM NEW.sample_count
        OR (NEW.record->>'numerator')::bigint IS DISTINCT FROM NEW.numerator
        OR (NEW.record->>'denominator')::bigint IS DISTINCT FROM NEW.denominator
        OR (NEW.record->>'scaled_value_millionths')::bigint
            IS DISTINCT FROM NEW.scaled_value_millionths
        OR (NEW.record->>'minimum_value')::bigint IS DISTINCT FROM NEW.minimum_value
        OR (NEW.record->>'p50_value')::bigint IS DISTINCT FROM NEW.p50_value
        OR (NEW.record->>'p90_value')::bigint IS DISTINCT FROM NEW.p90_value
        OR (NEW.record->>'p95_value')::bigint IS DISTINCT FROM NEW.p95_value
        OR (NEW.record->>'maximum_value')::bigint IS DISTINCT FROM NEW.maximum_value
        OR (NEW.record->>'gauge_value')::bigint IS DISTINCT FROM NEW.gauge_value
        OR NEW.record->>'measurement_version' IS DISTINCT FROM NEW.metric_version THEN
        RAISE EXCEPTION 'engineering measurement columns do not match the closed record';
    END IF;
    RETURN NEW;
END
$$;

CREATE FUNCTION validate_filing_latency_receipt()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    candidate_discovered_at timestamptz;
    lineage_first_known_at timestamptz;
    lineage_accession text;
BEGIN
    IF NEW.record - ARRAY[
        'receipt_id', 'accession_number', 'event_lineage_id',
        'authoritative_first_known_at', 'discovered_at', 'published_at', 'alerted_at',
        'first_known_to_discovery', 'discovery_to_publication', 'first_known_to_alert',
        'measured_at', 'measurement_version'
    ] <> '{}'::jsonb
        OR (NEW.record->'first_known_to_discovery') - ARRAY['value_ms', 'unavailable_reason']
            <> '{}'::jsonb
        OR (NEW.record->'discovery_to_publication') - ARRAY['value_ms', 'unavailable_reason']
            <> '{}'::jsonb
        OR (NEW.record->'first_known_to_alert') - ARRAY['value_ms', 'unavailable_reason']
            <> '{}'::jsonb THEN
        RAISE EXCEPTION 'filing latency receipt contains fields outside the closed contract';
    END IF;
    SELECT discovered_at INTO candidate_discovered_at FROM research_candidates
    WHERE accession_number = NEW.accession_number;
    IF candidate_discovered_at IS DISTINCT FROM NEW.discovered_at THEN
        RAISE EXCEPTION 'filing latency discovery does not match durable discovery';
    END IF;
    IF NEW.event_lineage_id IS NOT NULL THEN
        SELECT l.authoritative_first_known_at, d.accession_number
            INTO lineage_first_known_at, lineage_accession
        FROM research_event_lineage l
        JOIN research_event_disclosures d ON d.disclosure_id = l.current_disclosure_id
        WHERE l.lineage_id = NEW.event_lineage_id;
        IF lineage_first_known_at IS DISTINCT FROM NEW.authoritative_first_known_at
            OR lineage_accession IS DISTINCT FROM NEW.accession_number THEN
            RAISE EXCEPTION 'filing latency first-known source does not reconcile';
        END IF;
    END IF;
    IF NEW.published_at IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM research_briefs b
        WHERE b.accession_number = NEW.accession_number AND b.published_at = NEW.published_at
    ) THEN
        RAISE EXCEPTION 'filing latency publication does not match an immutable brief';
    END IF;
    IF NEW.alerted_at IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM research_notification_deliveries n
        JOIN research_briefs b ON b.brief_id = n.brief_id
        WHERE b.accession_number = NEW.accession_number AND n.status = 'sent'
          AND n.completed_at = NEW.alerted_at
    ) THEN
        RAISE EXCEPTION 'filing latency alert does not match a sent delivery';
    END IF;
    IF NEW.authoritative_first_known_at IS NULL THEN
        IF NEW.first_known_to_discovery_ms IS NOT NULL
            OR NEW.first_known_to_discovery_reason <> 'authoritative_first_known_unavailable'
            OR NEW.first_known_to_alert_ms IS NOT NULL
            OR NEW.first_known_to_alert_reason <> 'authoritative_first_known_unavailable' THEN
            RAISE EXCEPTION 'unknown first-known time must make dependent latencies unavailable';
        END IF;
    ELSE
        IF NEW.first_known_to_discovery_ms <>
                floor(extract(epoch FROM NEW.discovered_at - NEW.authoritative_first_known_at) * 1000)
            OR NEW.first_known_to_discovery_reason IS NOT NULL THEN
            RAISE EXCEPTION 'first-known to discovery latency does not reconcile';
        END IF;
        IF NEW.alerted_at IS NULL THEN
            IF NEW.first_known_to_alert_ms IS NOT NULL
                OR NEW.first_known_to_alert_reason <> 'alert_unavailable' THEN
                RAISE EXCEPTION 'missing alert must remain unavailable';
            END IF;
        ELSIF NEW.first_known_to_alert_ms <>
                floor(extract(epoch FROM NEW.alerted_at - NEW.authoritative_first_known_at) * 1000)
            OR NEW.first_known_to_alert_reason IS NOT NULL THEN
            RAISE EXCEPTION 'first-known to alert latency does not reconcile';
        END IF;
    END IF;
    IF NEW.published_at IS NULL THEN
        IF NEW.discovery_to_publication_ms IS NOT NULL
            OR NEW.discovery_to_publication_reason <> 'publication_unavailable' THEN
            RAISE EXCEPTION 'missing publication must remain unavailable';
        END IF;
    ELSIF NEW.discovery_to_publication_ms <>
            floor(extract(epoch FROM NEW.published_at - NEW.discovered_at) * 1000)
        OR NEW.discovery_to_publication_reason IS NOT NULL THEN
        RAISE EXCEPTION 'discovery to publication latency does not reconcile';
    END IF;
    IF NEW.record->>'receipt_id' IS DISTINCT FROM NEW.receipt_id::text
        OR NEW.record->>'accession_number' IS DISTINCT FROM NEW.accession_number
        OR NEW.record->>'event_lineage_id' IS DISTINCT FROM NEW.event_lineage_id::text
        OR (NEW.record->>'authoritative_first_known_at')::timestamptz
            IS DISTINCT FROM NEW.authoritative_first_known_at
        OR (NEW.record->>'discovered_at')::timestamptz IS DISTINCT FROM NEW.discovered_at
        OR (NEW.record->>'published_at')::timestamptz IS DISTINCT FROM NEW.published_at
        OR (NEW.record->>'alerted_at')::timestamptz IS DISTINCT FROM NEW.alerted_at
        OR (NEW.record#>>'{first_known_to_discovery,value_ms}')::bigint
            IS DISTINCT FROM NEW.first_known_to_discovery_ms
        OR NEW.record#>>'{first_known_to_discovery,unavailable_reason}'
            IS DISTINCT FROM NEW.first_known_to_discovery_reason
        OR (NEW.record#>>'{discovery_to_publication,value_ms}')::bigint
            IS DISTINCT FROM NEW.discovery_to_publication_ms
        OR NEW.record#>>'{discovery_to_publication,unavailable_reason}'
            IS DISTINCT FROM NEW.discovery_to_publication_reason
        OR (NEW.record#>>'{first_known_to_alert,value_ms}')::bigint
            IS DISTINCT FROM NEW.first_known_to_alert_ms
        OR NEW.record#>>'{first_known_to_alert,unavailable_reason}'
            IS DISTINCT FROM NEW.first_known_to_alert_reason
        OR (NEW.record->>'measured_at')::timestamptz IS DISTINCT FROM NEW.measured_at
        OR NEW.record->>'measurement_version' IS DISTINCT FROM NEW.measurement_version THEN
        RAISE EXCEPTION 'filing latency columns do not match the closed record';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER research_engineering_measurements_validate
    BEFORE INSERT ON research_engineering_measurements
    FOR EACH ROW EXECUTE FUNCTION validate_engineering_measurement();
CREATE TRIGGER research_filing_latency_receipts_validate
    BEFORE INSERT ON research_filing_latency_receipts
    FOR EACH ROW EXECUTE FUNCTION validate_filing_latency_receipt();

CREATE TRIGGER research_engineering_measurement_state_no_update_delete
    BEFORE UPDATE OR DELETE ON research_engineering_measurement_state
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_engineering_measurement_state_no_truncate
    BEFORE TRUNCATE ON research_engineering_measurement_state
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_engineering_metric_definitions_no_update_delete
    BEFORE UPDATE OR DELETE ON research_engineering_metric_definitions
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_engineering_metric_definitions_no_truncate
    BEFORE TRUNCATE ON research_engineering_metric_definitions
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_engineering_measurements_no_update_delete
    BEFORE UPDATE OR DELETE ON research_engineering_measurements
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_engineering_measurements_no_truncate
    BEFORE TRUNCATE ON research_engineering_measurements
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_filing_latency_receipts_no_update_delete
    BEFORE UPDATE OR DELETE ON research_filing_latency_receipts
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_filing_latency_receipts_no_truncate
    BEFORE TRUNCATE ON research_filing_latency_receipts
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();

INSERT INTO schema_migrations (version) VALUES ('0021_engineering_measurements');

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kalki_app') THEN
        EXECUTE 'GRANT SELECT ON research_engineering_measurement_state, research_engineering_metric_definitions TO kalki_app';
        EXECUTE 'GRANT SELECT, INSERT ON research_engineering_measurements, research_filing_latency_receipts TO kalki_app';
    END IF;
END
$$;

COMMIT;
