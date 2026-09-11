BEGIN;

CREATE TABLE web_admin_sessions (
    token_sha256 text PRIMARY KEY CHECK (token_sha256 ~ '^[0-9a-f]{64}$'),
    username text NOT NULL CHECK (username ~ '^[A-Za-z0-9_.-]{3,64}$'),
    client_sha256 text NOT NULL CHECK (client_sha256 ~ '^[0-9a-f]{64}$'),
    csrf_token text NOT NULL CHECK (length(csrf_token) BETWEEN 32 AND 256),
    created_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    CHECK (last_seen_at >= created_at),
    CHECK (expires_at > created_at),
    CHECK (revoked_at IS NULL OR revoked_at >= created_at)
);

CREATE INDEX web_admin_sessions_expiry_idx
    ON web_admin_sessions (expires_at);

CREATE TABLE web_security_audit_events (
    event_id uuid PRIMARY KEY,
    occurred_at timestamptz NOT NULL,
    event_type text NOT NULL CHECK (
        event_type IN (
            'login_succeeded',
            'login_failed',
            'login_rate_limited',
            'request_rate_limited',
            'session_rejected',
            'admin_viewed',
            'logout_succeeded',
            'csrf_rejected'
        )
    ),
    actor text CHECK (actor IS NULL OR actor ~ '^[A-Za-z0-9_.-]{3,64}$'),
    client_sha256 text NOT NULL CHECK (client_sha256 ~ '^[0-9a-f]{64}$'),
    detail text NOT NULL CHECK (
        detail IN (
            'login form token rejected',
            'login attempt rate limited',
            'credentials rejected',
            'admin session issued',
            'admin request rate limited',
            'admin dashboard viewed',
            'admin research detail viewed',
            'admin API session rejected',
            'logout token rejected',
            'admin session revoked',
            'admin page session rejected'
        )
    )
);

CREATE INDEX web_security_audit_occurred_idx
    ON web_security_audit_events (occurred_at DESC, event_id DESC);

CREATE TRIGGER web_security_audit_no_update_delete
    BEFORE UPDATE OR DELETE ON web_security_audit_events
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
CREATE TRIGGER web_security_audit_no_truncate
    BEFORE TRUNCATE ON web_security_audit_events
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();

CREATE TABLE web_login_attempts (
    attempt_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_sha256 text NOT NULL CHECK (client_sha256 ~ '^[0-9a-f]{64}$'),
    attempted_at timestamptz NOT NULL
);

CREATE INDEX web_login_attempts_client_time_idx
    ON web_login_attempts (client_sha256, attempted_at);

CREATE TABLE web_request_events (
    request_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_sha256 text NOT NULL CHECK (client_sha256 ~ '^[0-9a-f]{64}$'),
    requested_at timestamptz NOT NULL
);

CREATE INDEX web_request_events_client_time_idx
    ON web_request_events (client_sha256, requested_at);

INSERT INTO schema_migrations (version) VALUES ('0002_web_operations');

COMMIT;
