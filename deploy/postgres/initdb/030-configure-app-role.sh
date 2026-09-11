#!/bin/sh
set -eu

password_file=/run/secrets/postgres_app_password
if [ ! -f "$password_file" ]; then
    echo "PostgreSQL application password secret is absent." >&2
    exit 1
fi
app_password=$(tr -d '\r\n' < "$password_file")
case "$app_password" in
    *[!A-Za-z0-9_-]*|'')
        echo "PostgreSQL application password must be URL-safe characters only." >&2
        exit 1
        ;;
esac
if [ "${#app_password}" -lt 32 ] || [ "${#app_password}" -gt 128 ]; then
    echo "PostgreSQL application password must contain 32-128 characters." >&2
    exit 1
fi

psql --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kalki_app') THEN
        CREATE ROLE kalki_app LOGIN;
    END IF;
END
\$\$;
ALTER ROLE kalki_app PASSWORD '$app_password';
ALTER ROLE kalki_app SET statement_timeout = '5s';
ALTER ROLE kalki_app SET idle_in_transaction_session_timeout = '5s';
ALTER ROLE kalki_app SET lock_timeout = '2s';
REVOKE ALL ON DATABASE kalki FROM PUBLIC;
GRANT CONNECT ON DATABASE kalki TO kalki_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO kalki_app;
GRANT SELECT ON schema_migrations, predictions, prediction_corrections, prediction_outcomes
    TO kalki_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON web_admin_sessions TO kalki_app;
GRANT SELECT, INSERT, DELETE ON web_login_attempts, web_request_events TO kalki_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO kalki_app;
GRANT SELECT, INSERT ON web_security_audit_events TO kalki_app;
GRANT SELECT, INSERT, UPDATE ON research_candidates, research_worker_status TO kalki_app;
GRANT SELECT, INSERT ON research_briefs, research_runs, research_notification_deliveries
    TO kalki_app;
GRANT SELECT, INSERT ON research_verifier_reviews, research_verification_retries,
    research_verification_dispositions
    TO kalki_app;
GRANT SELECT, UPDATE ON research_operation_counters TO kalki_app;
SQL
