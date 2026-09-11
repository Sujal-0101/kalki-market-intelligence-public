# Phase 34 funnel telemetry and Mission Control

> **Status:** Deployed and live-validated on 2026-08-27. Historical lifecycle
> coverage before migration 0011 remains explicitly unavailable.

## Boundary

Mission Control remains available only through the loopback-only authenticated
admin application. The public application neither registers the route nor queries
the funnel repository. Queries return aggregate counts and bounded categories;
they never select filing text, human hypotheses, prompts, model responses,
Discord message content, credentials, or hidden reasoning.

Migration `0011_funnel_telemetry` adds three append-only structures:

- a singleton UTC telemetry epoch, used to label 24-hour, 48-hour, and 7-day
  lifecycle coverage as partial until the whole window is observed;
- content-free pipeline events correlated by run/accession where applicable; and
- one bounded detector receipt per accession and detector.

The worker records an SEC poll before provider I/O, then records retrieval,
parsing, CompanyFacts normalization, candidate transitions, deterministic tier
outcomes, stale recovery, and bounded failure categories. A terminal run reuses
the same UUID, so attempted polls equal terminal runs plus genuinely unterminated
attempts without double counting.

## Metrics

Each fixed window reports SEC attempted/completed/degraded/failed/unterminated
cycles, inserted discovery rows, unique candidates, lifecycle transitions,
retrieval/parse/normalization, stale recovery, Qwen invocations/attempts/contracts/
failures/retries/latency, verifier dispositions, quarantine/publication, Discord
delivery, private human lead/result/delivery/duplicate counts, and bounded failure
categories. Latency samples below 30 remain labelled `small_n`.

Current candidate state separately reports pending, processing, retry wait,
skipped, retained, escalated, quarantined, published, failed, backlog depth, and
oldest backlog age. Historical state transitions before migration 0011 are not
reconstructed. Current rows, immutable publications, terminal runs, analyst
receipts, verifier dispositions, and deliveries remain queryable for their real
timestamps; new lifecycle-only counts are visibly marked partial until coverage
is complete.

Detector tables report invocation and positive, negative, unknown, not assessed,
insufficient-evidence, and escalation-contribution counts for share growth,
liquidity, going concern, reverse split, filing diff, XBRL/numeric, source
authority, and convergence. Detectors not actually called remain `not_assessed`.
The current Tier-0 router does not use forensic detector status as a direct
escalation input, so its contribution count truthfully remains zero.

## Health semantics

Container age is not an application-health claim. Mission Control combines the
persisted worker state with the recent application window and host envelope.
Recent degraded/failed SEC cycles, Qwen timeouts, or a backlog older than 24 hours
degrade the application view. Unsupported temperature/GPU sensors and absent
funnel data display `UNAVAILABLE`; partial lifecycle coverage is explicitly noted.

## Migration and validation

Apply only after a fresh checksummed backup passes isolated restore:

```bash
./scripts/backup-postgres.sh
./scripts/restore-postgres-gate.sh backups/postgres/kalki-YYYYMMDDTHHMMSSZ.dump
./scripts/migrate-funnel-telemetry.sh
```

The migration is forward-only because removing append-only telemetry would erase
operational history. The pre-migration backup is the containment boundary.

`scripts/test-funnel-telemetry-postgres.sh` creates a disposable PostgreSQL 18
database, applies migrations 0001–0011, seeds a closed synthetic lifecycle, proves
append-only enforcement and least-privileged aggregate reads, and reconciles every
asserted Mission Control value to direct seed counts. The query completed under
the one-second safety ceiling in the disposable gate. This is engineering evidence,
not a production throughput or research-quality result.

## Production acceptance

The pre-migration backup `kalki-20260827T192935Z.dump` passed an isolated
restore before migration 0011 was applied at 2026-08-27 19:29:53 UTC. The
production image is `sha256:59b1972e8f2e5e676f461f3588c56d9f584d886aa1165eadecdc62da061bcdf6`;
it passed the non-root, read-only, capability-drop, and network-disabled import
checks. Admin, public, intake, and worker services were replaced without
interrupting an active Qwen request. The old worker was stopped only after its
terminal degraded run was persisted.

The private repository projection reconciled exactly to direct production
counts for pending, processing, retry-wait, backlog, terminal runs, analyst
attempts, valid contracts, timeouts, and human duplicates. Its aggregate query
completed in 7.83--52.45 ms across warm and cold observations. The local admin
route redirected to authentication, while the public container and external
origin returned 404 for `/admin/operations`; public `/radar` and `/research`
remained HTTP 200. No retained admin password was available for an interactive
browser login, so the private view model was validated inside the admin
container and its authentication/routing boundary was covered by the passing
route tests.

The first genuine post-deploy candidate, accession `0001289877-26-000027`,
persisted processing, retrieval, parse, Tier-0 escalation, CompanyFacts
normalization, and a terminal analyst failure. Its receipt records a bounded
300,140 ms runtime timeout; the candidate error identifies the local Ollama
timeout boundary. Eight detector receipts truthfully record the invoked
share-growth/liquidity/going-concern/reverse-split results and NOT_ASSESSED for
the four detectors not called. No publication or Discord delivery occurred.
Three genuine duplicate-intake events were also recorded when Discord history
was replayed after migration. A second candidate lifecycle was already
progressing when acceptance was recorded.

Observed resource use remained within the configured envelope: Ollama peaked
near 10.95 GiB of its 14 GiB limit during serialized inference, while the
worker used about 108 MiB of its 512 MiB limit. External radar remained
responsive. Qwen, its digest, the 300-second timeout, serialized execution,
Gemma-disabled state, evidence validation, publication thresholds, and public
boundary are unchanged. The post-migration backup
`kalki-20260827T194411Z.dump` retained 15 pipeline events and 16 detector
receipts and passed checksum and isolated-restore gates with exact row counts.
