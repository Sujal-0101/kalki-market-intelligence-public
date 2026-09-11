# Operations and troubleshooting guide

This runbook operates an already approved local installation. It does not authorize
public exposure, migration, model changes, or production-data mutation. Commands run
from the repository root unless stated otherwise.

> [!IMPORTANT]
> Observation Baseline V2 freezes model, digest, prompt/schema, evidence budgets,
> concurrency, verifier state, provider state, and evaluation rules. Normal operations
> may let existing queues advance, but must not change those contracts.

## Service map

| Service | Role | Dependencies | Normal exposure |
|---|---|---|---|
| `postgres` | durable ledgers, queue heads, sessions | secret files, volume | Docker internal only |
| `ollama` | accepted local Qwen inference | host binary/library/models | analyst network only |
| `worker` | SEC discovery and autonomous research | PostgreSQL, Ollama, Internet | none |
| `ownership-worker` | deterministic ownership processing | PostgreSQL, SEC | none |
| `financing-worker` | deterministic financing processing | PostgreSQL, SEC | none |
| `accounting-worker` | deterministic accounting processing | PostgreSQL, SEC | none |
| `admin` | authenticated Mission Control | PostgreSQL | `127.0.0.1:8000` |
| `public` | public-safe research projections | PostgreSQL | `127.0.0.1:8001` |
| `discord-intake` | optional private Gateway intake/results | PostgreSQL, Discord | outbound only |
| `prospective-outcomes` | optional market-data outcomes | PostgreSQL, provider | disabled profile |
| `cloudflared` | optional public connector | public service only | outbound tunnel |

## Normal startup

Validate files without starting anything:

```bash
docker compose -f compose.production.yaml config --quiet
```

No output means Compose parsed successfully. This does not verify credentials or
service health.

Start the accepted base services:

```bash
docker compose -f compose.production.yaml up -d \
  postgres ollama admin public worker ownership-worker financing-worker accounting-worker
docker compose -f compose.production.yaml ps
```

Explicit service names prevent accidentally starting disabled profiles or private
Discord on a new host. Production operators with an already approved intake/tunnel
use their recorded service set; do not infer approval from this document.

Startup order is dependency-aware. PostgreSQL and Ollama health may delay workers.
Wait for health checks rather than repeatedly recreating containers.

## Normal shutdown

Stop workers first so they can terminate cleanly, then the stack:

```bash
docker compose -f compose.production.yaml stop \
  worker ownership-worker financing-worker accounting-worker
docker compose -f compose.production.yaml stop admin public ollama postgres
```

`stop` preserves containers, networks, named volumes, images, secrets, models, and
backups. A planned database shutdown should not use `kill -9`.

`docker compose down` removes containers and project networks but normally preserves
named volumes. Never add `--volumes` during routine operations.

## Reboot recovery

Services use `restart: unless-stopped`. After a host reboot:

```bash
systemctl is-active docker
docker compose -f compose.production.yaml ps
```

If Docker is inactive, inspect `systemctl status docker --no-pager` before starting
it. If containers are absent, confirm you are in the correct immutable checkout and
that the Compose project name is correct. Do not initialize a second database by
accident.

Check that stale claims are recovering:

```bash
docker compose -f compose.production.yaml logs --since=30m --tail=200 worker
```

The main path records attempts and queue state transactionally; a pre-commit claim
can be reclaimed. Do not edit candidate rows manually.

## Health checks

### All services

```bash
docker compose -f compose.production.yaml ps
docker stats --no-stream
```

`ps` reports running/health; `stats` is a point sample. A worker process health check
only proves PID 1 exists. Combine it with database heartbeats and queue movement.

### PostgreSQL

```bash
docker compose -f compose.production.yaml exec -T postgres \
  pg_isready -U kalki_owner -d kalki
docker compose -f compose.production.yaml exec -T postgres \
  psql -X -U kalki_owner -d kalki -c \
  "SELECT version, applied_at FROM schema_migrations ORDER BY version DESC LIMIT 3;"
```

These are read-only readiness/schema checks. Expected Phase 45 ceiling is migration
0027. A higher or missing ceiling means this is not the accepted baseline.

### Worker activity and terminal outcomes

Use private Mission Control first. For a bounded SQL fallback, start an explicitly
read-only transaction:

```bash
docker compose -f compose.production.yaml exec -T postgres \
  psql -X -U kalki_owner -d kalki -c \
  "BEGIN TRANSACTION READ ONLY;
   SELECT status, count(*) FROM research_candidates GROUP BY status ORDER BY status;
   SELECT disposition, count(*) FROM research_autonomous_screening_decisions
     GROUP BY disposition ORDER BY disposition;
   COMMIT;"
```

Interpretation:

- `pending`: discovered and waiting;
- `processing`: currently claimed; one long Qwen request can keep it here;
- `retry_wait`: bounded recoverable failure awaiting eligible time;
- published/qualified: immutable dossier exists;
- skipped/screened out: completed without a publishable finding;
- failed/analysis incomplete: safe completion was impossible after policy/retries.

Candidate queue state and terminal screening decision are related but not synonyms;
historical candidates predate the prospective decision ledger.

### Qwen

```bash
docker compose -f compose.production.yaml exec -T ollama ollama list
docker compose -f compose.production.yaml logs --since=30m --tail=100 ollama
./scripts/report-analyst-attempts.sh
```

Confirm `qwen3:4b`, serialized service behavior, and accepted digest/lineage through
attempt reports. Logs can contain operational details; keep them private. Do not use
an ad-hoc chat prompt as a health benchmark.

### Public routes

```bash
curl -fsS http://127.0.0.1:8001/radar >/dev/null
curl -fsS http://127.0.0.1:8001/research >/dev/null
curl -fsS http://127.0.0.1:8001/screened >/dev/null
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8001/admin
curl -fsS http://127.0.0.1:8000/health >/dev/null
```

Expected: public pages succeed, public admin prints 404, private loopback health
succeeds. A public process that is healthy while a worker is busy demonstrates the
resource boundary, not research correctness.

### Discord (optional/private)

```bash
docker compose -f compose.production.yaml ps discord-intake
docker compose -f compose.production.yaml logs --since=30m --tail=100 discord-intake
```

Look for a connected Gateway, bounded authorization rejections, and idempotent
delivery state. Never paste logs, channel/user/message IDs, tokens, hypotheses, or
results into a public issue. Do not send a “test” message into production unless the
operator explicitly authorizes it.

## Safe service recreation

Recreate only after a reviewed image/config change and an immutable image record:

```bash
docker compose -f compose.production.yaml up -d --no-deps --force-recreate public
docker compose -f compose.production.yaml ps public
```

This example affects only `public`. Replace the service only when that exact action is
approved. Do not recreate PostgreSQL during ordinary application deployment. For a
worker, first inspect whether it has an active long-running claim; stopping it is
recoverable, but adds latency and should be deliberate.

Avoid the mutable-tag rollback failure class: a tag is only a label. Record and
verify the image ID/digest built from the approved Git commit. Do not rebuild an old
tag and assume its bytes are old.

## Why no alert can be healthy

Notification count is an output, not a heartbeat. Healthy quiet periods include:

1. SEC polling discovers no supported new candidate.
2. Tier 0 determines model work is not justified.
3. Qwen completes valid analysis but no finding survives evidence validation
   (`SCREENED_OUT/NO_VALIDATED_FINDINGS`).
4. A supported filing contains no ownership, financing, or accounting event.
5. Work is waiting in bounded backpressure/retry state.

Unhealthy quiet periods include a stale worker heartbeat, unmoving eligible queue,
repeated SEC/provider failures, model timeouts, schema mismatch, disk exhaustion, or
delivery reconciliation failures. Use multiple ledgers and health signals.

## Backlog interpretation

Specialized workers cap intake/backlog and process small batches. A backlog is not
automatically data loss. Track:

- age of oldest eligible pending job;
- jobs completed per observation window;
- retry/failed reason distribution;
- whether source failures recover;
- host/model contention and database health.

Do not increase batch size or concurrency while Qwen is CPU-bound. Ownership,
financing, and accounting workers are deterministic and separately capped, but still
share SEC/network/PostgreSQL/host resources.

At Observation Baseline V2, bounded backlogs and failures existed, all six event
lineages were `UNKNOWN_NOVELTY`, Focus had no membership history, and outcome tables
were empty. Those facts are limitations, not permissions to backfill or tune them.

## Resource and temperature monitoring

```bash
docker stats --no-stream
free -h
df -h /
docker system df
```

These report container usage, host memory/swap, root filesystem space, and Docker
disk inventory. `docker system df` does not delete anything. Do not respond with a
blanket prune; identify images/build cache versus database/model/backups first.

If `lm-sensors` is installed:

```bash
sensors
```

Compare against the hardware vendor limits and the host's established baseline.
The reference laptop can reach high temperatures during sustained inference. If
temperatures are unexpectedly high, stop workers cleanly, leave PostgreSQL/public
read-only service as needed, and inspect cooling. Never paste hardware serials or
network identifiers into public reports.

## Logs

Container logs are accessed through Compose:

```bash
docker compose -f compose.production.yaml logs --since=1h --tail=200 SERVICE_NAME
```

Host Docker logs are typically in journald:

```bash
journalctl -u docker --since '1 hour ago' --no-pager
```

Local supervisor logs, backups, `.env`, secrets, and model files are ignored by Git.
Logs may still contain filing identities, local paths, provider errors, public IPs,
Discord metadata, or private research. Treat them as sensitive and retain only as
long as operationally necessary.

## Backup and restore

Create a backup:

```bash
./scripts/backup-postgres.sh
```

Validate the chosen archive without network access:

```bash
./scripts/restore-postgres-gate.sh backups/postgres/kalki-YYYYMMDDTHHMMSSZ.dump
```

The gate restores into a disposable PostgreSQL instance and compares durable counts
and migrations. It does not prove the archive is safely stored off-host.

> [!DANGER]
> Never restore over the only production volume. A real recovery restores into a new
> volume/database, validates it, records a cutover plan, and preserves both the old
> volume and verified archive until acceptance.

Backups contain private research, security events, delivery IDs, operational
history, and possibly licensed source metadata. Encrypt them and control access.

## Troubleshooting playbooks

### Model timeout or contract rejection

1. Confirm the receipt is a timeout versus format/schema/evidence rejection.
2. Check Ollama container health, memory/swap, CPU, and temperature.
3. Confirm exact Qwen digest, context/output cap, prompt/schema, evidence budget, and
   `OLLAMA_NUM_PARALLEL=1` match the baseline.
4. Allow bounded retry policy to act. A retry is not permission to parse invalid text.
5. If failures repeat, preserve attempts and mark analysis incomplete. Do not raise
   timeout/concurrency or enable Gemma as an emergency workaround.

### SEC errors

For 403/429 or timeouts:

- verify the configured descriptive User-Agent and real contact without printing it;
- verify configured rate remains conservative;
- inspect SEC status and DNS/TLS connectivity;
- let a temporary rate block clear;
- confirm URLs use only validated SEC hosts/archive shapes;
- retain `retrieved_at`/availability semantics and never fabricate a response.

Malformed optional CompanyFacts entries are isolated, while missing required issuer
identity fails closed. A new SEC shape requires fixtures and a reviewed parser change,
not manual database edits.

### Migration problem

1. Stop affected writers.
2. Read the latest `schema_migrations` rows and exact error.
3. Verify backup and isolated restore gate.
4. Compare release commit, mounted migration files, and expected ceiling.
5. Use only the named guarded migration script in numeric order.

Do not rerun arbitrary SQL, update the ledger by hand, delete tables, or use a down
migration unless a separately reviewed recovery plan proves it safe.

### Cloudflare problem

First test local public routes. If local works, inspect only the connector:

```bash
docker compose -f compose.production.yaml -f compose.cloudflare.yaml ps cloudflared
docker compose -f compose.production.yaml -f compose.cloudflare.yaml \
  logs --since=30m --tail=100 cloudflared
```

Check that the connector shares only `public_connector` and uses a tunnel-scoped
token. Do not change DNS, public routes, or expose port 8001 as a shortcut. Never
paste the token or full connector logs publicly.

### Discord Gateway problem

Check service health, outbound DNS/TLS, token-file readability, one configured
channel, and stable allowlist. A reconnect must not replay research; dedupe and
delivery receipts should absorb duplicate events. Do not broaden intents/permissions
or accept display names in place of stable user IDs.

### Disk full

1. Stop workers to reduce writes.
2. Keep PostgreSQL running if safe so it can checkpoint; do not repeatedly restart it.
3. Use `df -h`, `docker system df`, and size listings to identify the consumer.
4. Preserve database volume and the newest verified backups.
5. Move an approved old backup/image/cache to verified storage or expand the disk.

Never run `docker system prune -a --volumes`, delete PostgreSQL/WAL files, or remove
unknown archives under pressure.

### Suspected database corruption

Stop application writers, record errors, preserve the volume, and make a storage-
level snapshot only if the method is understood. Do not run destructive repair or
copy individual PostgreSQL data files. Restore the latest verified logical backup to
a separate database and compare. Escalate filesystem/hardware errors.

### Recovery after interrupted work

- Re-read the accepted Git commit, release-candidate manifest, Phase 45 baseline,
  image digest, schema ceiling, model lineage, and your private operator change log.
- Check Git status without discarding changes.
- Inspect containers and production read-only before assuming what ran.
- Treat started-without-completed attempts and stale claims according to the durable
  recovery contract.
- Never repeat a delivery manually; reconcile its exact-once ledger first.
- Do not resume Phase 46 or feature work while Observation Baseline V2 is frozen.

## Incident evidence to collect privately

Record UTC time, host/release identifier, Git commit, image digest, schema ceiling,
affected service, health state, bounded error category, relevant receipt IDs, disk/
memory/temperature snapshot, and actions taken. Redact secrets, Discord IDs, human
content, local paths, IPs, and raw model text before sharing externally.
