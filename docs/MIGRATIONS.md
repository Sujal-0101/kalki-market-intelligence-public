# Proposed Database Migration Strategy

> **Phase 41 status:** Twenty-two ordered forward SQL migrations define append-only
> prediction/outcome history, durable web operational state, publication ordering,
> live filing-radar and verifier state, Tier-0 provenance, private human research,
> and content-free analyst-attempt receipts. Static, live, and isolated recovery
> gates apply to the current history.

Phase 14 adds the first live upgrade and rollback runner for the reversible publication
ordering index. Take and validate a backup first, then use:

```bash
./scripts/backup-postgres.sh
./scripts/migrate-postgres.sh up
./scripts/migrate-postgres.sh down  # only to roll back migration 0003
```

The runner checks database health and the migration ledger, stops on SQL errors, and
is idempotent for the requested state. Rollback 0003 removes only the query index and
migration marker; it never removes application rows.

Migration 0004 adds mutable candidate/worker state and separately protected
append-only briefs, runs, and notification delivery records. Apply it after a verified
backup with `./scripts/migrate-live-radar.sh`. It intentionally has no down migration:
dropping these tables could destroy publication history, so recovery uses a new
database restored from the verified pre-migration backup.

Migration 0010 adds `research_analyst_attempts`. The worker inserts a bounded
started record before provider I/O and may complete it exactly once. Identity and
input metadata cannot change; completed rows cannot be updated, deleted, or
truncated. Apply it after a verified backup with
`./scripts/migrate-analyst-attempt-receipts.sh`. It has no destructive rollback;
restore a verified pre-migration backup into a new database if schema removal is
ever required.

Migration 0012 evolves private human results without rewriting history. It adds
nullable provenance columns to the existing append-only table; old v1 rows remain
unchanged and therefore expose UNKNOWN/NULL for unavailable lineage. A before-insert
trigger requires all future results to use the closed v2 record, match their
relational source/delivery fields, and reference only completed human-origin analyst
attempts for the same lead. Apply it after a verified backup with
`./scripts/migrate-human-result-provenance.sh`. See
[PHASE36_HUMAN_PROVENANCE.md](PHASE36_HUMAN_PROVENANCE.md).

Migration 0013 adds prospective, append-only autonomous screening decisions with
the mutually exclusive terminal results `QUALIFIED`, `SCREENED_OUT`, and
`ANALYSIS_INCOMPLETE`. It does not backfill or reinterpret legacy candidate rows.
It also permits a version 3 dossier only when a matching qualified decision and
the truthful Qwen-plus-deterministic publication receipt are inserted atomically;
all prior independent-verifier and deterministic database gates remain in force.
Apply it only after a verified backup with
`./scripts/migrate-autonomous-screening-decisions.sh`. The forward migration is
data-preserving and has no destructive down migration.

Migration 0014 adds immutable prospective-outcome plans, attempts, and supporting
results plus restart-safe mutable job heads. It records explicit forward versus
reconstructed origin, exchange-session dates, provider terms/use metadata, retained
bar hashes and timestamps, and deterministic raw/benchmark-relative price returns.
It never edits a brief, prediction, decision, or prior outcome. Apply it only after a
verified backup with `./scripts/migrate-prospective-outcomes.sh`; validate the complete
lifecycle first with `./scripts/test-prospective-outcomes-postgres.sh`. See
[PHASE37_PROSPECTIVE_OUTCOMES.md](PHASE37_PROSPECTIVE_OUTCOMES.md).

Migration 0015 adds immutable primary-source ownership filing and deterministic
routing receipts. Relational query columns are reconciled to the complete closed
JSON contracts, routing must reference the same accession and source hash, and the
application role can only select or insert. It does not enqueue filings into the
existing deep-analysis queue or reinterpret historical filings. Validate the
disposable lifecycle with `./scripts/test-ownership-postgres.sh`, then apply it only
after a verified backup using `./scripts/migrate-ownership-intelligence.sh`.

Migration 0016 corrects the daily-index identity boundary without rewriting the
empty ownership ledgers. SEC ownership accessions are indexed once for the issuer
and again for reporting owners, so the queue now retains the closed set of index
CIKs/names and records a resolved issuer only after submissions metadata and the
primary document agree. Apply it with
`./scripts/migrate-ownership-index-identity.sh` before starting the worker.

Migration 0017 adds the private financing queue and append-only deterministic filing
and routing receipts. Migrations 0018 and 0019 add append-only event-novelty lineage
and private Focus membership history without seeding or rewriting public history.

Migration 0020 adds append-only validated SEC-link receipts and a nullable link key on
historical briefs. It performs no backfill. Every brief inserted after the migration
must reconcile its accession, complete-submission URL/hash and publication time to a
stored receipt; old rows remain unchanged with their historical URL. Validate with
`./scripts/test-validated-sec-links-postgres.sh` and apply only after a verified backup
using `./scripts/migrate-validated-sec-links.sh`.

Migration 0022 adds a private accounting/compliance queue and append-only filing and
model-free Tier-0 routing receipts. It does not backfill or reinterpret historical
filings. Valid supported-form filings without exact closed events terminate as
`no_events`; acquisition and persistence failures remain separate and bounded to three
attempts. Validate the complete lifecycle with `./scripts/test-accounting-postgres.sh`
and apply only after a verified backup using
`./scripts/migrate-accounting-compliance.sh`.

Migration 0023 corrects the prospective SEC-link receipt validator to recognize only
the two official complete-submission archive shapes: the flat path published by the SEC
daily index and the equivalent nested accession-directory path. It continues to require
the exact candidate URL and nested archive-index/primary-document identity. It replaces
only the validation function and does not update candidates, receipts, briefs or history.
Apply it after a verified backup with
`./scripts/migrate-sec-complete-submission-paths.sh` and validate the full fresh history
with `./scripts/test-validated-sec-links-postgres.sh`.

Migration 0024 expands the analyst-attempt latency check from the original two-hour
synchronous-call ceiling to the nonnegative PostgreSQL bigint domain. This lets the
worker truthfully close a lease-expired `started` receipt at the time recovery is
actually observed, even after a long outage. It does not update any existing attempt
or mutable work item. Validate candidate, terminal-parent, private-human, and lease
boundaries with `./scripts/test-analyst-attempt-recovery-postgres.sh`; after a verified
backup, apply it with `./scripts/migrate-stale-analyst-attempt-recovery.sh`.

Migration 0025 adds private append-only Phase 42 filing-change snapshots and selection
receipts. It performs no backfill and does not alter filings, candidates, briefs, model
execution, or public data. Snapshot records retain bounded exact SEC section text so later
comparisons can reproduce their source-side hashes; selection records bind both manifests
and their deterministic bounded delta. Triggers enforce relational/JSON identity, official
CIK/accession URL shape, chronology, same issuer, and closed relationship/form families.
The application role can select and insert but cannot update or delete. Validate with
`./scripts/test-filing-change-lifecycle-postgres.sh` and apply only after a verified backup
using `./scripts/migrate-filing-change-lifecycle.sh`.

PostgreSQL is the production structured system of record. Current Compose
initialization applies migrations to a new empty volume; all later schema changes
must be reviewed forward migrations and cannot rely on initialization hooks to
change an existing database.

## Rules

1. Every schema change is a versioned, reviewed migration committed with the code that uses it.
2. Migrations are deterministic and ordered from a single repository-controlled history. Production-style databases are never changed manually.
3. CI/local checks apply the full history to an empty PostgreSQL database and upgrade a fixture representing the previous supported version.
4. Stored instants use PostgreSQL `timestamptz` and application values normalized to UTC. Publication, availability, retrieval, and creation times remain separate columns.
5. Foreign keys, uniqueness, checks, and append-only protections enforce important invariants in the database as well as application contracts.
6. Destructive changes use an expand/migrate/contract sequence. Data removal, irreversible rewrites, and migration-history edits require explicit approval and a tested backup/restore path.
7. Data backfills record provenance and information availability. They must not make later knowledge appear available earlier.
8. Immutable predictions will be protected from update/delete operations when that schema is introduced; outcomes will append separately.
9. Rollback is normally a forward corrective migration. A down migration is supplied only when it can preserve data safely.

## Naming and review

Migration names should state intent, such as `add_source_availability_timestamp`, rather than use only ticket numbers. Reviews must include lock/runtime impact, data-volume assumptions, forward and recovery procedures, and tests for temporal and referential integrity.

Phase 9 introduces the first ordered SQL migration. Phase 12 adds the web-state
migration, Python PostgreSQL adapter, least-privileged role initialization, and
production backup/restore gate. Phases 14 and 15 add idempotent scoped live runners;
each checks health and the migration ledger, executes under the owner role, and has a
documented data-preserving recovery boundary.
