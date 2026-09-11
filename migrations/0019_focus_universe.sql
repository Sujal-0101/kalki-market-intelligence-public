BEGIN;

CREATE TABLE research_focus_universe_state (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    started_at timestamptz NOT NULL,
    schema_version text NOT NULL CHECK (schema_version = '1.0.0')
);
INSERT INTO research_focus_universe_state (started_at, schema_version)
VALUES (clock_timestamp(), '1.0.0');

CREATE TABLE research_focus_membership_events (
    event_id uuid PRIMARY KEY,
    canonical_cik text NOT NULL CHECK (canonical_cik ~ '^[0-9]{10}$'),
    ticker text CHECK (ticker IS NULL OR char_length(ticker) BETWEEN 1 AND 16),
    company_name text NOT NULL CHECK (char_length(company_name) BETWEEN 1 AND 255),
    action text NOT NULL CHECK (action IN ('added', 'removed')),
    reason text NOT NULL CHECK (reason IN (
        'widely_followed', 'user_interest', 'curated_review'
    )),
    effective_at timestamptz NOT NULL,
    recorded_at timestamptz NOT NULL,
    universe_version text NOT NULL CHECK (
        char_length(universe_version) BETWEEN 1 AND 64
        AND universe_version ~ '^[A-Z0-9._-]+$'
    ),
    supersedes_event_id uuid REFERENCES research_focus_membership_events(event_id),
    schema_version text NOT NULL CHECK (schema_version = '1.0.0'),
    record jsonb NOT NULL,
    CHECK (recorded_at >= effective_at),
    CHECK (event_id IS DISTINCT FROM supersedes_event_id)
);
CREATE UNIQUE INDEX research_focus_membership_events_supersedes_idx
    ON research_focus_membership_events (supersedes_event_id)
    WHERE supersedes_event_id IS NOT NULL;
CREATE INDEX research_focus_membership_events_point_in_time_idx
    ON research_focus_membership_events (
        canonical_cik, recorded_at DESC, event_id DESC
    );

CREATE FUNCTION validate_focus_membership_event()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    prior_event research_focus_membership_events%ROWTYPE;
BEGIN
    IF NEW.supersedes_event_id IS NULL THEN
        IF NEW.action <> 'added' THEN
            RAISE EXCEPTION 'focus membership history must begin with an add';
        END IF;
        IF EXISTS (
            SELECT 1 FROM research_focus_membership_events
            WHERE canonical_cik = NEW.canonical_cik
        ) THEN
            RAISE EXCEPTION 'focus membership issuer already has a history';
        END IF;
    ELSE
        SELECT * INTO prior_event FROM research_focus_membership_events
        WHERE event_id = NEW.supersedes_event_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'focus membership superseded event does not exist';
        END IF;
        IF prior_event.canonical_cik IS DISTINCT FROM NEW.canonical_cik
            OR prior_event.company_name IS DISTINCT FROM NEW.company_name THEN
            RAISE EXCEPTION 'focus membership cannot change issuer identity';
        END IF;
        IF prior_event.action = NEW.action THEN
            RAISE EXCEPTION 'focus membership transitions must alternate';
        END IF;
        IF NEW.recorded_at <= prior_event.recorded_at THEN
            RAISE EXCEPTION 'focus membership recording time must advance';
        END IF;
        IF EXISTS (
            SELECT 1 FROM research_focus_membership_events
            WHERE supersedes_event_id = prior_event.event_id
        ) THEN
            RAISE EXCEPTION 'focus membership history cannot branch';
        END IF;
    END IF;
    IF NEW.record->>'event_id' IS DISTINCT FROM NEW.event_id::text
        OR NEW.record->>'canonical_cik' IS DISTINCT FROM NEW.canonical_cik
        OR NEW.record->>'ticker' IS DISTINCT FROM NEW.ticker
        OR NEW.record->>'company_name' IS DISTINCT FROM NEW.company_name
        OR NEW.record->>'action' IS DISTINCT FROM NEW.action
        OR NEW.record->>'reason' IS DISTINCT FROM NEW.reason
        OR (NEW.record->>'effective_at')::timestamptz IS DISTINCT FROM NEW.effective_at
        OR (NEW.record->>'recorded_at')::timestamptz IS DISTINCT FROM NEW.recorded_at
        OR NEW.record->>'universe_version' IS DISTINCT FROM NEW.universe_version
        OR NEW.record->>'supersedes_event_id'
            IS DISTINCT FROM NEW.supersedes_event_id::text
        OR NEW.record->>'schema_version' IS DISTINCT FROM NEW.schema_version THEN
        RAISE EXCEPTION 'focus membership columns do not match the closed record';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER research_focus_membership_events_validate
    BEFORE INSERT ON research_focus_membership_events
    FOR EACH ROW EXECUTE FUNCTION validate_focus_membership_event();
CREATE TRIGGER research_focus_membership_events_no_update_delete
    BEFORE UPDATE OR DELETE ON research_focus_membership_events
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_focus_membership_events_no_truncate
    BEFORE TRUNCATE ON research_focus_membership_events
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_focus_universe_state_no_update_delete
    BEFORE UPDATE OR DELETE ON research_focus_universe_state
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER research_focus_universe_state_no_truncate
    BEFORE TRUNCATE ON research_focus_universe_state
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();

INSERT INTO schema_migrations (version) VALUES ('0019_focus_universe');

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kalki_app') THEN
        EXECUTE 'GRANT SELECT ON research_focus_universe_state TO kalki_app';
        EXECUTE 'GRANT SELECT, INSERT ON research_focus_membership_events TO kalki_app';
    END IF;
END
$$;

COMMIT;
