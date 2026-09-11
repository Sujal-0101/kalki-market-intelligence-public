#!/bin/sh
set -eu

umask 077
repository_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
compose_file=${KALKI_COMPOSE_FILE:-$repository_dir/compose.production.yaml}
project_name=${KALKI_COMPOSE_PROJECT:-kalki-production}
backup_root=${KALKI_BACKUP_ROOT:-$repository_dir/backups/postgres}

case "$backup_root" in
    /|"$repository_dir")
        echo "Refusing an unsafe backup root." >&2
        exit 2
        ;;
esac
if [ -L "$backup_root" ]; then
    echo "Backup root must not be a symbolic link." >&2
    exit 2
fi
mkdir -p -- "$backup_root"
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
archive=$backup_root/kalki-$timestamp.dump
counts=$archive.counts

docker compose --project-name "$project_name" --file "$compose_file" exec -T postgres \
    pg_dump --username kalki_owner --dbname kalki --format=custom --no-owner --no-privileges \
    > "$archive"
has_verifier=$(docker compose --project-name "$project_name" --file "$compose_file" exec -T \
    postgres psql --username kalki_owner --dbname kalki --no-align --tuples-only \
    --command "SELECT to_regclass('public.research_verifier_reviews') IS NOT NULL;")
if [ "$has_verifier" = t ]; then
    verifier_counts="
        UNION ALL SELECT 'research_operation_counters', count(*) FROM research_operation_counters
        UNION ALL SELECT 'research_verification_dispositions', count(*)
            FROM research_verification_dispositions
        UNION ALL SELECT 'research_verification_retries', count(*)
            FROM research_verification_retries
        UNION ALL SELECT 'research_verifier_reviews', count(*) FROM research_verifier_reviews"
else
    verifier_counts=""
fi
has_human_leads=$(docker compose --project-name "$project_name" --file "$compose_file" exec -T \
    postgres psql --username kalki_owner --dbname kalki --no-align --tuples-only \
    --command "SELECT to_regclass('public.research_human_leads') IS NOT NULL;")
if [ "$has_human_leads" = t ]; then
    human_lead_counts="
        UNION ALL SELECT 'research_human_lead_events', count(*) FROM research_human_lead_events
        UNION ALL SELECT 'research_human_leads', count(*) FROM research_human_leads"
else
    human_lead_counts=""
fi
has_human_feedback=$(docker compose --project-name "$project_name" --file "$compose_file" exec -T \
    postgres psql --username kalki_owner --dbname kalki --no-align --tuples-only \
    --command "SELECT to_regclass('public.research_human_feedback') IS NOT NULL;")
if [ "$has_human_feedback" = t ]; then
    human_feedback_counts=" UNION ALL SELECT 'research_human_feedback', count(*) FROM research_human_feedback"
else
    human_feedback_counts=""
fi
has_human_results=$(docker compose --project-name "$project_name" --file "$compose_file" exec -T \
    postgres psql --username kalki_owner --dbname kalki --no-align --tuples-only \
    --command "SELECT to_regclass('public.research_human_results') IS NOT NULL;")
if [ "$has_human_results" = t ]; then
    human_result_counts=" UNION ALL SELECT 'research_human_results', count(*) FROM research_human_results UNION ALL SELECT 'research_human_result_deliveries', count(*) FROM research_human_result_deliveries"
else
    human_result_counts=""
fi
has_analyst_attempts=$(docker compose --project-name "$project_name" --file "$compose_file" exec -T \
    postgres psql --username kalki_owner --dbname kalki --no-align --tuples-only \
    --command "SELECT to_regclass('public.research_analyst_attempts') IS NOT NULL;")
if [ "$has_analyst_attempts" = t ]; then
    analyst_attempt_counts=" UNION ALL SELECT 'research_analyst_attempts', count(*) FROM research_analyst_attempts"
else
    analyst_attempt_counts=""
fi
has_funnel_telemetry=$(docker compose --project-name "$project_name" --file "$compose_file" exec -T \
    postgres psql --username kalki_owner --dbname kalki --no-align --tuples-only \
    --command "SELECT to_regclass('public.research_pipeline_events') IS NOT NULL;")
if [ "$has_funnel_telemetry" = t ]; then
    funnel_telemetry_counts="
        UNION ALL SELECT 'research_detector_receipts', count(*) FROM research_detector_receipts
        UNION ALL SELECT 'research_funnel_telemetry_state', count(*) FROM research_funnel_telemetry_state
        UNION ALL SELECT 'research_pipeline_events', count(*) FROM research_pipeline_events"
else
    funnel_telemetry_counts=""
fi
has_screening_decisions=$(docker compose --project-name "$project_name" --file "$compose_file" exec -T \
    postgres psql --username kalki_owner --dbname kalki --no-align --tuples-only \
    --command "SELECT to_regclass('public.research_autonomous_screening_decisions') IS NOT NULL;")
if [ "$has_screening_decisions" = t ]; then
    screening_decision_counts=" UNION ALL SELECT 'research_autonomous_screening_decisions', count(*) FROM research_autonomous_screening_decisions UNION ALL SELECT 'research_autonomous_screening_state', count(*) FROM research_autonomous_screening_state"
else
    screening_decision_counts=""
fi
has_prospective_outcomes=$(docker compose --project-name "$project_name" --file "$compose_file" exec -T \
    postgres psql --username kalki_owner --dbname kalki --no-align --tuples-only \
    --command "SELECT to_regclass('public.research_prospective_outcome_plans') IS NOT NULL;")
if [ "$has_prospective_outcomes" = t ]; then
    prospective_outcome_counts="
        UNION ALL SELECT 'research_prospective_outcome_attempts', count(*)
            FROM research_prospective_outcome_attempts
        UNION ALL SELECT 'research_prospective_outcome_jobs', count(*)
            FROM research_prospective_outcome_jobs
        UNION ALL SELECT 'research_prospective_outcome_plans', count(*)
            FROM research_prospective_outcome_plans
        UNION ALL SELECT 'research_prospective_outcomes', count(*)
            FROM research_prospective_outcomes"
else
    prospective_outcome_counts=""
fi
has_ownership_intelligence=$(docker compose --project-name "$project_name" --file "$compose_file" exec -T \
    postgres psql --username kalki_owner --dbname kalki --no-align --tuples-only \
    --command "SELECT to_regclass('public.research_ownership_receipts') IS NOT NULL;")
if [ "$has_ownership_intelligence" = t ]; then
    ownership_intelligence_counts="
        UNION ALL SELECT 'research_ownership_jobs', count(*)
            FROM research_ownership_jobs
        UNION ALL SELECT 'research_ownership_receipts', count(*)
            FROM research_ownership_receipts
        UNION ALL SELECT 'research_ownership_routing_receipts', count(*)
            FROM research_ownership_routing_receipts
        UNION ALL SELECT 'research_ownership_state', count(*)
            FROM research_ownership_state"
else
    ownership_intelligence_counts=""
fi
has_financing_intelligence=$(docker compose --project-name "$project_name" --file "$compose_file" exec -T \
    postgres psql --username kalki_owner --dbname kalki --no-align --tuples-only \
    --command "SELECT to_regclass('public.research_financing_receipts') IS NOT NULL;")
if [ "$has_financing_intelligence" = t ]; then
    financing_intelligence_counts="
        UNION ALL SELECT 'research_financing_jobs', count(*)
            FROM research_financing_jobs
        UNION ALL SELECT 'research_financing_receipts', count(*)
            FROM research_financing_receipts
        UNION ALL SELECT 'research_financing_routing_receipts', count(*)
            FROM research_financing_routing_receipts
        UNION ALL SELECT 'research_financing_state', count(*)
            FROM research_financing_state"
else
    financing_intelligence_counts=""
fi
has_event_novelty=$(docker compose --project-name "$project_name" --file "$compose_file" exec -T \
    postgres psql --username kalki_owner --dbname kalki --no-align --tuples-only \
    --command "SELECT to_regclass('public.research_event_lineage') IS NOT NULL;")
if [ "$has_event_novelty" = t ]; then
    event_novelty_counts="
        UNION ALL SELECT 'research_event_disclosures', count(*)
            FROM research_event_disclosures
        UNION ALL SELECT 'research_event_lineage', count(*) FROM research_event_lineage
        UNION ALL SELECT 'research_event_novelty_state', count(*)
            FROM research_event_novelty_state"
else
    event_novelty_counts=""
fi
has_focus_universe=$(docker compose --project-name "$project_name" --file "$compose_file" exec -T \
    postgres psql --username kalki_owner --dbname kalki --no-align --tuples-only \
    --command "SELECT to_regclass('public.research_focus_membership_events') IS NOT NULL;")
if [ "$has_focus_universe" = t ]; then
    focus_universe_counts="
        UNION ALL SELECT 'research_focus_membership_events', count(*)
            FROM research_focus_membership_events
        UNION ALL SELECT 'research_focus_universe_state', count(*)
            FROM research_focus_universe_state"
else
    focus_universe_counts=""
fi
has_validated_sec_links=$(docker compose --project-name "$project_name" --file "$compose_file" exec -T \
    postgres psql --username kalki_owner --dbname kalki --no-align --tuples-only \
    --command "SELECT to_regclass('public.research_sec_link_receipts') IS NOT NULL;")
if [ "$has_validated_sec_links" = t ]; then
    validated_sec_link_counts="
        UNION ALL SELECT 'research_sec_link_receipts', count(*)
            FROM research_sec_link_receipts
        UNION ALL SELECT 'research_sec_link_validation_state', count(*)
            FROM research_sec_link_validation_state"
else
    validated_sec_link_counts=""
fi
has_engineering_measurements=$(docker compose --project-name "$project_name" --file "$compose_file" exec -T \
    postgres psql --username kalki_owner --dbname kalki --no-align --tuples-only \
    --command "SELECT to_regclass('public.research_engineering_measurements') IS NOT NULL;")
if [ "$has_engineering_measurements" = t ]; then
    engineering_measurement_counts="
        UNION ALL SELECT 'research_engineering_measurement_state', count(*)
            FROM research_engineering_measurement_state
        UNION ALL SELECT 'research_engineering_metric_definitions', count(*)
            FROM research_engineering_metric_definitions
        UNION ALL SELECT 'research_engineering_measurements', count(*)
            FROM research_engineering_measurements
        UNION ALL SELECT 'research_filing_latency_receipts', count(*)
            FROM research_filing_latency_receipts"
else
    engineering_measurement_counts=""
fi
has_accounting_intelligence=$(docker compose --project-name "$project_name" --file "$compose_file" exec -T \
    postgres psql --username kalki_owner --dbname kalki --no-align --tuples-only \
    --command "SELECT to_regclass('public.research_accounting_receipts') IS NOT NULL;")
if [ "$has_accounting_intelligence" = t ]; then
    accounting_intelligence_counts="
        UNION ALL SELECT 'research_accounting_jobs', count(*)
            FROM research_accounting_jobs
        UNION ALL SELECT 'research_accounting_receipts', count(*)
            FROM research_accounting_receipts
        UNION ALL SELECT 'research_accounting_routing_receipts', count(*)
            FROM research_accounting_routing_receipts
        UNION ALL SELECT 'research_accounting_state', count(*)
            FROM research_accounting_state"
else
    accounting_intelligence_counts=""
fi
has_filing_change=$(docker compose --project-name "$project_name" --file "$compose_file" exec -T \
    postgres psql --username kalki_owner --dbname kalki --no-align --tuples-only \
    --command "SELECT to_regclass('public.research_filing_change_snapshots') IS NOT NULL;")
if [ "$has_filing_change" = t ]; then
    filing_change_counts="
        UNION ALL SELECT 'research_filing_change_selections', count(*)
            FROM research_filing_change_selections
        UNION ALL SELECT 'research_filing_change_snapshots', count(*)
            FROM research_filing_change_snapshots"
else
    filing_change_counts=""
fi
has_contradiction_receipts=$(docker compose --project-name "$project_name" --file "$compose_file" exec -T \
    postgres psql --username kalki_owner --dbname kalki --no-align --tuples-only \
    --command "SELECT to_regclass('public.research_contradiction_receipts') IS NOT NULL;")
if [ "$has_contradiction_receipts" = t ]; then
    contradiction_receipt_counts="
        UNION ALL SELECT 'research_contradiction_receipts', count(*)
            FROM research_contradiction_receipts"
else
    contradiction_receipt_counts=""
fi
docker compose --project-name "$project_name" --file "$compose_file" exec -T postgres \
    psql --username kalki_owner --dbname kalki --no-align --tuples-only --field-separator '|' \
    --command "
        SELECT 'prediction_corrections', count(*) FROM prediction_corrections
        UNION ALL SELECT 'prediction_outcomes', count(*) FROM prediction_outcomes
        UNION ALL SELECT 'predictions', count(*) FROM predictions
        UNION ALL SELECT 'research_briefs', count(*) FROM research_briefs
        UNION ALL SELECT 'research_candidates', count(*) FROM research_candidates
        UNION ALL SELECT 'research_notification_deliveries', count(*)
            FROM research_notification_deliveries
        UNION ALL SELECT 'research_runs', count(*) FROM research_runs
        UNION ALL SELECT 'research_worker_status', count(*) FROM research_worker_status
        $verifier_counts
        $human_lead_counts
        $human_feedback_counts
        $human_result_counts
        $analyst_attempt_counts
        $funnel_telemetry_counts
        $screening_decision_counts
        $prospective_outcome_counts
        $ownership_intelligence_counts
        $financing_intelligence_counts
        $event_novelty_counts
        $focus_universe_counts
        $validated_sec_link_counts
        $engineering_measurement_counts
        $accounting_intelligence_counts
        $filing_change_counts
        $contradiction_receipt_counts
        UNION ALL SELECT 'schema_migrations', count(*) FROM schema_migrations
        UNION ALL SELECT 'web_security_audit_events', count(*) FROM web_security_audit_events
        ORDER BY 1
    " > "$counts"
sha256sum "$archive" > "$archive.sha256"
docker compose --project-name "$project_name" --file "$compose_file" exec -T postgres \
    pg_restore --list < "$archive" > /dev/null

printf 'Backup created and structurally validated: %s\n' "$archive"
printf 'Treat the archive as sensitive; no automatic deletion or upload was performed.\n'
