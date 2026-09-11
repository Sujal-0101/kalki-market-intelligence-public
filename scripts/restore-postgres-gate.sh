#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "Usage: scripts/restore-postgres-gate.sh BACKUP.dump" >&2
    exit 2
fi
archive=$(readlink -f -- "$1")
if [ ! -f "$archive" ] || [ -L "$archive" ]; then
    echo "Backup must be a regular non-symlink file." >&2
    exit 2
fi
if [ ! -f "$archive.sha256" ] || [ ! -f "$archive.counts" ]; then
    echo "Backup checksum or count manifest is absent." >&2
    exit 2
fi
(cd -- "$(dirname -- "$archive")" && sha256sum --check "$(basename -- "$archive").sha256")
expected_counts=$(cat -- "$archive.counts")

image=postgres:18.0-alpine3.22@sha256:48c8ad3a7284b82be4482a52076d47d879fd6fb084a1cbfccbd551f9331b0e40
container=kalki-restore-gate-$$
cleanup() {
    docker container rm --force "$container" > /dev/null 2>&1 || true
}
trap cleanup EXIT HUP INT TERM

docker run --detach --name "$container" --network none \
    --tmpfs /var/lib/postgresql/data:rw,noexec,nosuid,size=768m \
    --env POSTGRES_HOST_AUTH_METHOD=trust --env POSTGRES_DB=kalki_restore \
    "$image" > /dev/null

attempt=0
consecutive_ready=0
while [ "$consecutive_ready" -lt 3 ]
do
    attempt=$((attempt + 1))
    if docker exec "$container" pg_isready --username postgres --dbname kalki_restore \
        > /dev/null 2>&1
    then
        consecutive_ready=$((consecutive_ready + 1))
    else
        consecutive_ready=0
    fi
    if [ "$attempt" -ge 45 ]; then
        echo "Restore database did not become healthy." >&2
        exit 1
    fi
    sleep 1
done

docker exec --interactive "$container" pg_restore --exit-on-error --no-owner --no-privileges \
    --username postgres --dbname kalki_restore < "$archive"
has_radar=$(docker exec "$container" psql --username postgres --dbname kalki_restore \
    --no-align --tuples-only --command \
    "SELECT to_regclass('public.research_briefs') IS NOT NULL;")
if [ "$has_radar" = t ]; then
    has_verifier=$(docker exec "$container" psql --username postgres --dbname kalki_restore \
        --no-align --tuples-only --command \
        "SELECT to_regclass('public.research_verifier_reviews') IS NOT NULL;")
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
    has_human_leads=$(docker exec "$container" psql --username postgres --dbname kalki_restore \
        --no-align --tuples-only --command \
        "SELECT to_regclass('public.research_human_leads') IS NOT NULL;")
    if [ "$has_human_leads" = t ]; then
        human_lead_counts="
        UNION ALL SELECT 'research_human_lead_events', count(*) FROM research_human_lead_events
        UNION ALL SELECT 'research_human_leads', count(*) FROM research_human_leads"
    else
        human_lead_counts=""
    fi
    has_human_feedback=$(docker exec "$container" psql --username postgres --dbname kalki_restore \
        --no-align --tuples-only --command \
        "SELECT to_regclass('public.research_human_feedback') IS NOT NULL;")
    if [ "$has_human_feedback" = t ]; then
        human_feedback_counts=" UNION ALL SELECT 'research_human_feedback', count(*) FROM research_human_feedback"
    else
        human_feedback_counts=""
    fi
    has_human_results=$(docker exec "$container" psql --username postgres --dbname kalki_restore --no-align --tuples-only --command "SELECT to_regclass('public.research_human_results') IS NOT NULL;")
    if [ "$has_human_results" = t ]; then
        human_result_counts=" UNION ALL SELECT 'research_human_results', count(*) FROM research_human_results UNION ALL SELECT 'research_human_result_deliveries', count(*) FROM research_human_result_deliveries"
    else
        human_result_counts=""
    fi
    has_analyst_attempts=$(docker exec "$container" psql --username postgres --dbname kalki_restore --no-align --tuples-only --command "SELECT to_regclass('public.research_analyst_attempts') IS NOT NULL;")
    if [ "$has_analyst_attempts" = t ]; then
        analyst_attempt_counts=" UNION ALL SELECT 'research_analyst_attempts', count(*) FROM research_analyst_attempts"
    else
        analyst_attempt_counts=""
    fi
    has_funnel_telemetry=$(docker exec "$container" psql --username postgres --dbname kalki_restore --no-align --tuples-only --command "SELECT to_regclass('public.research_pipeline_events') IS NOT NULL;")
    if [ "$has_funnel_telemetry" = t ]; then
        funnel_telemetry_counts=" UNION ALL SELECT 'research_detector_receipts', count(*) FROM research_detector_receipts UNION ALL SELECT 'research_funnel_telemetry_state', count(*) FROM research_funnel_telemetry_state UNION ALL SELECT 'research_pipeline_events', count(*) FROM research_pipeline_events"
    else
        funnel_telemetry_counts=""
    fi
    has_screening_decisions=$(docker exec "$container" psql --username postgres --dbname kalki_restore --no-align --tuples-only --command "SELECT to_regclass('public.research_autonomous_screening_decisions') IS NOT NULL;")
    if [ "$has_screening_decisions" = t ]; then
        screening_decision_counts=" UNION ALL SELECT 'research_autonomous_screening_decisions', count(*) FROM research_autonomous_screening_decisions UNION ALL SELECT 'research_autonomous_screening_state', count(*) FROM research_autonomous_screening_state"
    else
        screening_decision_counts=""
    fi
    has_prospective_outcomes=$(docker exec "$container" psql --username postgres --dbname kalki_restore --no-align --tuples-only --command "SELECT to_regclass('public.research_prospective_outcome_plans') IS NOT NULL;")
    if [ "$has_prospective_outcomes" = t ]; then
        prospective_outcome_counts=" UNION ALL SELECT 'research_prospective_outcome_attempts', count(*) FROM research_prospective_outcome_attempts UNION ALL SELECT 'research_prospective_outcome_jobs', count(*) FROM research_prospective_outcome_jobs UNION ALL SELECT 'research_prospective_outcome_plans', count(*) FROM research_prospective_outcome_plans UNION ALL SELECT 'research_prospective_outcomes', count(*) FROM research_prospective_outcomes"
    else
        prospective_outcome_counts=""
    fi
    has_ownership_intelligence=$(docker exec "$container" psql --username postgres --dbname kalki_restore --no-align --tuples-only --command "SELECT to_regclass('public.research_ownership_receipts') IS NOT NULL;")
    if [ "$has_ownership_intelligence" = t ]; then
        ownership_intelligence_counts=" UNION ALL SELECT 'research_ownership_jobs', count(*) FROM research_ownership_jobs UNION ALL SELECT 'research_ownership_receipts', count(*) FROM research_ownership_receipts UNION ALL SELECT 'research_ownership_routing_receipts', count(*) FROM research_ownership_routing_receipts UNION ALL SELECT 'research_ownership_state', count(*) FROM research_ownership_state"
    else
        ownership_intelligence_counts=""
    fi
    has_financing_intelligence=$(docker exec "$container" psql --username postgres --dbname kalki_restore --no-align --tuples-only --command "SELECT to_regclass('public.research_financing_receipts') IS NOT NULL;")
    if [ "$has_financing_intelligence" = t ]; then
        financing_intelligence_counts=" UNION ALL SELECT 'research_financing_jobs', count(*) FROM research_financing_jobs UNION ALL SELECT 'research_financing_receipts', count(*) FROM research_financing_receipts UNION ALL SELECT 'research_financing_routing_receipts', count(*) FROM research_financing_routing_receipts UNION ALL SELECT 'research_financing_state', count(*) FROM research_financing_state"
    else
        financing_intelligence_counts=""
    fi
    has_event_novelty=$(docker exec "$container" psql --username postgres --dbname kalki_restore --no-align --tuples-only --command "SELECT to_regclass('public.research_event_lineage') IS NOT NULL;")
    if [ "$has_event_novelty" = t ]; then
        event_novelty_counts=" UNION ALL SELECT 'research_event_disclosures', count(*) FROM research_event_disclosures UNION ALL SELECT 'research_event_lineage', count(*) FROM research_event_lineage UNION ALL SELECT 'research_event_novelty_state', count(*) FROM research_event_novelty_state"
    else
        event_novelty_counts=""
    fi
    has_focus_universe=$(docker exec "$container" psql --username postgres --dbname kalki_restore --no-align --tuples-only --command "SELECT to_regclass('public.research_focus_membership_events') IS NOT NULL;")
    if [ "$has_focus_universe" = t ]; then
        focus_universe_counts=" UNION ALL SELECT 'research_focus_membership_events', count(*) FROM research_focus_membership_events UNION ALL SELECT 'research_focus_universe_state', count(*) FROM research_focus_universe_state"
    else
        focus_universe_counts=""
    fi
    has_validated_sec_links=$(docker exec "$container" psql --username postgres --dbname kalki_restore --no-align --tuples-only --command "SELECT to_regclass('public.research_sec_link_receipts') IS NOT NULL;")
    if [ "$has_validated_sec_links" = t ]; then
        validated_sec_link_counts=" UNION ALL SELECT 'research_sec_link_receipts', count(*) FROM research_sec_link_receipts UNION ALL SELECT 'research_sec_link_validation_state', count(*) FROM research_sec_link_validation_state"
    else
        validated_sec_link_counts=""
    fi
    has_engineering_measurements=$(docker exec "$container" psql --username postgres --dbname kalki_restore --no-align --tuples-only --command "SELECT to_regclass('public.research_engineering_measurements') IS NOT NULL;")
    if [ "$has_engineering_measurements" = t ]; then
        engineering_measurement_counts=" UNION ALL SELECT 'research_engineering_measurement_state', count(*) FROM research_engineering_measurement_state UNION ALL SELECT 'research_engineering_metric_definitions', count(*) FROM research_engineering_metric_definitions UNION ALL SELECT 'research_engineering_measurements', count(*) FROM research_engineering_measurements UNION ALL SELECT 'research_filing_latency_receipts', count(*) FROM research_filing_latency_receipts"
    else
        engineering_measurement_counts=""
    fi
    has_accounting_intelligence=$(docker exec "$container" psql --username postgres --dbname kalki_restore --no-align --tuples-only --command "SELECT to_regclass('public.research_accounting_receipts') IS NOT NULL;")
    if [ "$has_accounting_intelligence" = t ]; then
        accounting_intelligence_counts=" UNION ALL SELECT 'research_accounting_jobs', count(*) FROM research_accounting_jobs UNION ALL SELECT 'research_accounting_receipts', count(*) FROM research_accounting_receipts UNION ALL SELECT 'research_accounting_routing_receipts', count(*) FROM research_accounting_routing_receipts UNION ALL SELECT 'research_accounting_state', count(*) FROM research_accounting_state"
    else
        accounting_intelligence_counts=""
    fi
    has_filing_change=$(docker exec "$container" psql --username postgres --dbname kalki_restore --no-align --tuples-only --command "SELECT to_regclass('public.research_filing_change_snapshots') IS NOT NULL;")
    if [ "$has_filing_change" = t ] && printf '%s\n' "$expected_counts" | grep -q '^research_filing_change_snapshots|'; then
        filing_change_counts=" UNION ALL SELECT 'research_filing_change_selections', count(*) FROM research_filing_change_selections UNION ALL SELECT 'research_filing_change_snapshots', count(*) FROM research_filing_change_snapshots"
    else
        filing_change_counts=""
    fi
    has_contradiction_receipts=$(docker exec "$container" psql --username postgres --dbname kalki_restore --no-align --tuples-only --command "SELECT to_regclass('public.research_contradiction_receipts') IS NOT NULL;")
    if [ "$has_contradiction_receipts" = t ] && printf '%s\n' "$expected_counts" | grep -q '^research_contradiction_receipts|'; then
        contradiction_receipt_counts=" UNION ALL SELECT 'research_contradiction_receipts', count(*) FROM research_contradiction_receipts"
    else
        contradiction_receipt_counts=""
    fi
    restored_counts=$(docker exec "$container" psql --username postgres --dbname kalki_restore \
        --no-align --tuples-only --field-separator '|' --command "
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
    ")
else
    restored_counts=$(docker exec "$container" psql --username postgres --dbname kalki_restore \
        --no-align --tuples-only --field-separator '|' --command "
        SELECT 'prediction_corrections', count(*) FROM prediction_corrections
        UNION ALL SELECT 'prediction_outcomes', count(*) FROM prediction_outcomes
        UNION ALL SELECT 'predictions', count(*) FROM predictions
        UNION ALL SELECT 'schema_migrations', count(*) FROM schema_migrations
        UNION ALL SELECT 'web_security_audit_events', count(*) FROM web_security_audit_events
        ORDER BY 1
    ")
fi
if [ "$restored_counts" != "$expected_counts" ]; then
    echo "Restored row counts do not match the backup manifest." >&2
    exit 1
fi
docker exec "$container" psql --username postgres --dbname kalki_restore \
    --set=ON_ERROR_STOP=1 --command \
    "TRUNCATE web_admin_sessions, web_login_attempts, web_request_events;" > /dev/null
migration_versions=$(docker exec "$container" psql --username postgres --dbname kalki_restore \
    --tuples-only --no-align --command \
    "SELECT string_agg(version, ',' ORDER BY version) FROM schema_migrations;")
case "$migration_versions" in
    0001_prediction_outcomes,0002_web_operations,0003_publication_list_index | \
    0001_prediction_outcomes,0002_web_operations,0003_publication_list_index,0004_live_research_radar | \
    0001_prediction_outcomes,0002_web_operations,0003_publication_list_index,0004_live_research_radar,0005_hierarchical_verifier | \
    0001_prediction_outcomes,0002_web_operations,0003_publication_list_index,0004_live_research_radar,0005_hierarchical_verifier,0006_tier0_decisions | \
    0001_prediction_outcomes,0002_web_operations,0003_publication_list_index,0004_live_research_radar,0005_hierarchical_verifier,0006_tier0_decisions,0007_human_research_leads | \
    0001_prediction_outcomes,0002_web_operations,0003_publication_list_index,0004_live_research_radar,0005_hierarchical_verifier,0006_tier0_decisions,0007_human_research_leads,0008_human_research_feedback | \
    0001_prediction_outcomes,0002_web_operations,0003_publication_list_index,0004_live_research_radar,0005_hierarchical_verifier,0006_tier0_decisions,0007_human_research_leads,0008_human_research_feedback,0009_human_research_results | \
    0001_prediction_outcomes,0002_web_operations,0003_publication_list_index,0004_live_research_radar,0005_hierarchical_verifier,0006_tier0_decisions,0007_human_research_leads,0008_human_research_feedback,0009_human_research_results,0010_analyst_attempt_receipts | \
    0001_prediction_outcomes,0002_web_operations,0003_publication_list_index,0004_live_research_radar,0005_hierarchical_verifier,0006_tier0_decisions,0007_human_research_leads,0008_human_research_feedback,0009_human_research_results,0010_analyst_attempt_receipts,0011_funnel_telemetry | \
    0001_prediction_outcomes,0002_web_operations,0003_publication_list_index,0004_live_research_radar,0005_hierarchical_verifier,0006_tier0_decisions,0007_human_research_leads,0008_human_research_feedback,0009_human_research_results,0010_analyst_attempt_receipts,0011_funnel_telemetry,0012_human_result_provenance | \
    0001_prediction_outcomes,0002_web_operations,0003_publication_list_index,0004_live_research_radar,0005_hierarchical_verifier,0006_tier0_decisions,0007_human_research_leads,0008_human_research_feedback,0009_human_research_results,0010_analyst_attempt_receipts,0011_funnel_telemetry,0012_human_result_provenance,0013_autonomous_screening_decisions | \
    0001_prediction_outcomes,0002_web_operations,0003_publication_list_index,0004_live_research_radar,0005_hierarchical_verifier,0006_tier0_decisions,0007_human_research_leads,0008_human_research_feedback,0009_human_research_results,0010_analyst_attempt_receipts,0011_funnel_telemetry,0012_human_result_provenance,0013_autonomous_screening_decisions,0014_prospective_outcomes | \
    0001_prediction_outcomes,0002_web_operations,0003_publication_list_index,0004_live_research_radar,0005_hierarchical_verifier,0006_tier0_decisions,0007_human_research_leads,0008_human_research_feedback,0009_human_research_results,0010_analyst_attempt_receipts,0011_funnel_telemetry,0012_human_result_provenance,0013_autonomous_screening_decisions,0014_prospective_outcomes,0015_ownership_intelligence | \
    0001_prediction_outcomes,0002_web_operations,0003_publication_list_index,0004_live_research_radar,0005_hierarchical_verifier,0006_tier0_decisions,0007_human_research_leads,0008_human_research_feedback,0009_human_research_results,0010_analyst_attempt_receipts,0011_funnel_telemetry,0012_human_result_provenance,0013_autonomous_screening_decisions,0014_prospective_outcomes,0015_ownership_intelligence,0016_ownership_index_identity | \
    0001_prediction_outcomes,0002_web_operations,0003_publication_list_index,0004_live_research_radar,0005_hierarchical_verifier,0006_tier0_decisions,0007_human_research_leads,0008_human_research_feedback,0009_human_research_results,0010_analyst_attempt_receipts,0011_funnel_telemetry,0012_human_result_provenance,0013_autonomous_screening_decisions,0014_prospective_outcomes,0015_ownership_intelligence,0016_ownership_index_identity,0017_financing_intelligence | \
    0001_prediction_outcomes,0002_web_operations,0003_publication_list_index,0004_live_research_radar,0005_hierarchical_verifier,0006_tier0_decisions,0007_human_research_leads,0008_human_research_feedback,0009_human_research_results,0010_analyst_attempt_receipts,0011_funnel_telemetry,0012_human_result_provenance,0013_autonomous_screening_decisions,0014_prospective_outcomes,0015_ownership_intelligence,0016_ownership_index_identity,0017_financing_intelligence,0018_event_novelty_lineage | \
    0001_prediction_outcomes,0002_web_operations,0003_publication_list_index,0004_live_research_radar,0005_hierarchical_verifier,0006_tier0_decisions,0007_human_research_leads,0008_human_research_feedback,0009_human_research_results,0010_analyst_attempt_receipts,0011_funnel_telemetry,0012_human_result_provenance,0013_autonomous_screening_decisions,0014_prospective_outcomes,0015_ownership_intelligence,0016_ownership_index_identity,0017_financing_intelligence,0018_event_novelty_lineage,0019_focus_universe | \
    0001_prediction_outcomes,0002_web_operations,0003_publication_list_index,0004_live_research_radar,0005_hierarchical_verifier,0006_tier0_decisions,0007_human_research_leads,0008_human_research_feedback,0009_human_research_results,0010_analyst_attempt_receipts,0011_funnel_telemetry,0012_human_result_provenance,0013_autonomous_screening_decisions,0014_prospective_outcomes,0015_ownership_intelligence,0016_ownership_index_identity,0017_financing_intelligence,0018_event_novelty_lineage,0019_focus_universe,0020_validated_sec_links | \
    0001_prediction_outcomes,0002_web_operations,0003_publication_list_index,0004_live_research_radar,0005_hierarchical_verifier,0006_tier0_decisions,0007_human_research_leads,0008_human_research_feedback,0009_human_research_results,0010_analyst_attempt_receipts,0011_funnel_telemetry,0012_human_result_provenance,0013_autonomous_screening_decisions,0014_prospective_outcomes,0015_ownership_intelligence,0016_ownership_index_identity,0017_financing_intelligence,0018_event_novelty_lineage,0019_focus_universe,0020_validated_sec_links,0021_engineering_measurements | \
    0001_prediction_outcomes,0002_web_operations,0003_publication_list_index,0004_live_research_radar,0005_hierarchical_verifier,0006_tier0_decisions,0007_human_research_leads,0008_human_research_feedback,0009_human_research_results,0010_analyst_attempt_receipts,0011_funnel_telemetry,0012_human_result_provenance,0013_autonomous_screening_decisions,0014_prospective_outcomes,0015_ownership_intelligence,0016_ownership_index_identity,0017_financing_intelligence,0018_event_novelty_lineage,0019_focus_universe,0020_validated_sec_links,0021_engineering_measurements,0022_accounting_compliance,0023_sec_complete_submission_paths | \
    0001_prediction_outcomes,0002_web_operations,0003_publication_list_index,0004_live_research_radar,0005_hierarchical_verifier,0006_tier0_decisions,0007_human_research_leads,0008_human_research_feedback,0009_human_research_results,0010_analyst_attempt_receipts,0011_funnel_telemetry,0012_human_result_provenance,0013_autonomous_screening_decisions,0014_prospective_outcomes,0015_ownership_intelligence,0016_ownership_index_identity,0017_financing_intelligence,0018_event_novelty_lineage,0019_focus_universe,0020_validated_sec_links,0021_engineering_measurements,0022_accounting_compliance,0023_sec_complete_submission_paths,0024_stale_analyst_attempt_recovery | \
    0001_prediction_outcomes,0002_web_operations,0003_publication_list_index,0004_live_research_radar,0005_hierarchical_verifier,0006_tier0_decisions,0007_human_research_leads,0008_human_research_feedback,0009_human_research_results,0010_analyst_attempt_receipts,0011_funnel_telemetry,0012_human_result_provenance,0013_autonomous_screening_decisions,0014_prospective_outcomes,0015_ownership_intelligence,0016_ownership_index_identity,0017_financing_intelligence,0018_event_novelty_lineage,0019_focus_universe,0020_validated_sec_links,0021_engineering_measurements,0022_accounting_compliance,0023_sec_complete_submission_paths,0024_stale_analyst_attempt_recovery,0025_filing_change_lifecycle | \
    0001_prediction_outcomes,0002_web_operations,0003_publication_list_index,0004_live_research_radar,0005_hierarchical_verifier,0006_tier0_decisions,0007_human_research_leads,0008_human_research_feedback,0009_human_research_results,0010_analyst_attempt_receipts,0011_funnel_telemetry,0012_human_result_provenance,0013_autonomous_screening_decisions,0014_prospective_outcomes,0015_ownership_intelligence,0016_ownership_index_identity,0017_financing_intelligence,0018_event_novelty_lineage,0019_focus_universe,0020_validated_sec_links,0021_engineering_measurements,0022_accounting_compliance,0023_sec_complete_submission_paths,0024_stale_analyst_attempt_recovery,0025_filing_change_lifecycle,0026_contradiction_receipts | \
    0001_prediction_outcomes,0002_web_operations,0003_publication_list_index,0004_live_research_radar,0005_hierarchical_verifier,0006_tier0_decisions,0007_human_research_leads,0008_human_research_feedback,0009_human_research_results,0010_analyst_attempt_receipts,0011_funnel_telemetry,0012_human_result_provenance,0013_autonomous_screening_decisions,0014_prospective_outcomes,0015_ownership_intelligence,0016_ownership_index_identity,0017_financing_intelligence,0018_event_novelty_lineage,0019_focus_universe,0020_validated_sec_links,0021_engineering_measurements,0022_accounting_compliance,0023_sec_complete_submission_paths,0024_stale_analyst_attempt_recovery,0025_filing_change_lifecycle,0026_contradiction_receipts,0027_outcome_science_invariants)
        ;;
    *)
        echo "Restored migration ledger has an unsupported or gapped history." >&2
        exit 1
        ;;
esac

printf 'Isolated restore gate passed; row counts matched and transient sessions were cleared.\n'
