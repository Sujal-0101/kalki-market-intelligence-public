# Production deployment and Cloudflare runbook

`YOUR_PUBLIC_HOSTNAME` is a public documentation placeholder. A new operator must
set `KALKI_WEB_PUBLIC_HOSTNAME` in the ignored `.env`; it is not a usable DNS name.
Historical production names are intentionally absent from this public runbook.

> **Current state:** production is live only at
> `https://YOUR_PUBLIC_HOSTNAME`. The initial activation,
> external security checks, rate-limit gate, backup/restore gate, and connector
> rollback drill passed on 2026-08-25. Do not use a Quick Tunnel.

## Architecture and cost boundary

Kalki's Python/FastAPI processes and PostgreSQL database run on this local Docker
host. Cloudflare will not host the Python application or database. The only
planned Cloudflare components are the existing Registrar/DNS zone, Cloudflare
Tunnel, proxied TLS, the Free Managed WAF ruleset, one free-plan rate-limiting
rule, and tunnel-health notifications. No Worker, Pages project, R2 bucket,
Cloudflare database, Load Balancer, paid Access seat, or paid WAF feature is
required.

The intended incremental Cloudflare cost is **$0/month** on the Free plan. The
domain's existing annual registrar renewal is the only known recurring charge.
No paid third-party runtime API is introduced: PostgreSQL, Python, Docker,
`cloudflared`, and the local Ollama path run locally. Electricity,
internet access, hardware/storage wear, and any separately chosen off-site backup
have operator-dependent costs. Confirm the dashboard still labels each selected
feature Free before activation.

The only public surface is
`https://YOUR_PUBLIC_HOSTNAME/`, its `/radar`, `/research`, and
`/screened` pages, static assets, and reviewed read-only APIs. `/research` is the
explicitly typed dossier/forecast library while
the API namespaces retain their existing dossier-versus-forecast contracts.
Admin/login, health,
OpenAPI/docs, PostgreSQL, host management, backups, logs, and Discord credentials
remain private.

Phase 15 adds two supervised private services: `ollama` and `worker`. Ollama reuses
the reviewed host-local binary, CPU runner libraries, and model store, disables cloud
features, and joins only
the internal analyst network. The worker joins that network plus PostgreSQL. Neither
publishes a port or joins the public connector network. The existing ignored `.env`
is mounted read-only only into the worker so SEC identity and Discord secrets never
appear in Compose environment metadata.
The worker additionally joins a dedicated outbound-NAT bridge for its origin-
restricted SEC and Discord clients; that bridge publishes no inbound service.
Ollama remains limited to one request. With Gemma disabled, its Qwen CPU ceiling
is six of the host's eight logical threads; measured runtime uses about four cores
and leaves the public origin responsive. Production Recovery II restored this
ceiling after the Gemma qualification envelope's two-CPU setting correlated with
repeated five-minute Qwen timeouts. If thermal or co-hosted-service pressure appears,
pause the worker before reducing the ceiling because the strict model gate did not
pass at lower limits. Re-enabling Gemma would require an explicit plan change and
restoration plus revalidation of its separate two-CPU resource envelope.

## Required local secrets

The ignored `secrets/` directory must be mode `0700`. Secret files need to be
readable by their non-root containers; with the protected parent directory, mode
`0644` is used for these root-owned bind-mounted files. Each file contains one
line and no label:

| File | Purpose | Who creates it |
|---|---|---|
| `secrets/postgres_owner_password` | migration, backup, and recovery owner | operator locally, unique random 32–128 URL-safe characters |
| `secrets/postgres_app_password` | least-privileged application role | operator locally, independently random 32–128 URL-safe characters |
| `secrets/admin_password_hash` | Argon2id encoded hash, never plaintext | `kalki-hash-admin-password` or reviewed equivalent |
| `secrets/cloudflare_tunnel_token` | run one remotely managed tunnel | operator copies only after creating that tunnel in the dashboard |

The optional `secrets/twelve_data_api_key` is **not** a current production secret.
It may be created only by the account holder after separately reviewing and accepting
the provider's current free-tier terms. It must be one line, remain ignored, and is
mounted only into the disabled `supporting-outcomes` profile.

Do not use an account Global API Key or general API token. A remotely managed
tunnel connector needs only its tunnel-scoped token. Treat that token as a secret:
anyone who has it can run a connector for the tunnel. Do not paste secrets into
shell history, chat, documentation, `.env`, Compose YAML, or Git.

## Local production start and gate

Before starting, verify Docker access with `id`, inspect
`/var/run/docker.sock`, and run `docker info`. Review secrets without printing
their values, then build and start:

```bash
test "$(stat -c '%a' secrets)" = 700
test "$(stat -c '%a' secrets/postgres_owner_password)" = 644
test "$(stat -c '%a' secrets/postgres_app_password)" = 644
test "$(stat -c '%a' secrets/admin_password_hash)" = 644
docker compose -f compose.production.yaml config --quiet
docker compose -f compose.production.yaml build --pull
docker compose -f compose.production.yaml up --detach
docker compose -f compose.production.yaml ps
```

The first PostgreSQL initialization applies both ordered migrations and creates
the least-privileged application role. Later changes require a separately
reviewed forward migration; replacing a mounted initialization file does not
modify an existing database.

Verify only loopback ports `8000` and `8001` are published and no database port
is published. Verify the exact public Host header locally:

```bash
curl --fail --header 'Host: YOUR_PUBLIC_HOSTNAME' \
  http://127.0.0.1:8001/research
curl --include --header 'Host: YOUR_PUBLIC_HOSTNAME' \
  http://127.0.0.1:8001/admin
curl --include http://127.0.0.1:8000/admin
```

The public `/admin` probe must return `404`; local admin redirects to login.

## Backup and restore

Create a consistent custom-format backup outside Git:

```bash
./scripts/backup-postgres.sh
```

It produces a dump, SHA-256 sidecar, and row-count manifest under ignored
`backups/postgres/`, then checks that PostgreSQL can list the archive. Copying a
backup off this host is a separate privacy/storage decision and is not automated.

Validate a selected backup in an isolated, network-disabled, temporary database:

```bash
./scripts/restore-postgres-gate.sh \
  backups/postgres/kalki-YYYYMMDDTHHMMSSZ.dump
```

The gate verifies the checksum, restores the database, compares durable table
counts, confirms migrations, clears transient sessions/rate rows in the restored
copy, and removes its temporary container. It never modifies the live volume.

Phase 14 migration 0003 adds only the bounded public-list ordering index. After a
fresh verified backup, apply or roll it back with:

```bash
./scripts/migrate-postgres.sh up
./scripts/migrate-postgres.sh down
```

The runner checks health and the migration ledger and is idempotent. Rollback removes
only the index and marker, never application data. See
[MIGRATIONS.md](MIGRATIONS.md) and [PHASE14_OPTIMIZATION.md](PHASE14_OPTIMIZATION.md).

Phase 15 migration 0004 adds the durable filing-radar queue, worker state,
immutable briefs, runs, and delivery audits. Apply it idempotently only after a
verified backup:

```bash
./scripts/migrate-live-radar.sh
```

Migration 0004 has no automatic destructive rollback because dropping its tables
could destroy research history. Recover a verified pre-migration backup into a new
database if that schema must be removed. See
[LIVE_RESEARCH_RADAR.md](LIVE_RESEARCH_RADAR.md).

Phase 33 migration 0010 adds durable, content-free analyst attempt receipts. After
a fresh backup and isolated restore gate, apply it idempotently with:

```bash
./scripts/migrate-analyst-attempt-receipts.sh
```

There is no destructive automatic rollback. The pre-migration backup is the
containment boundary; application deployment must not precede the schema.

Phase 34 migration 0011 adds append-only, content-free lifecycle and detector
telemetry used only by private Mission Control. After a fresh verified backup and
isolated restore gate, apply it idempotently with:

```bash
./scripts/migrate-funnel-telemetry.sh
```

Deploy the admin/worker image only after the schema exists. The telemetry epoch
causes new 24h/48h/7d transition metrics to display partial coverage until their
full observation windows have elapsed. There is no destructive automatic rollback.

Phase 36 migration 0012 adds nullable provenance columns and a future-insert guard
to the append-only private human-result table. It does not update old result JSON.
After a fresh backup and isolated restore gate, apply it with:

```bash
./scripts/migrate-human-result-provenance.sh
```

Production Recovery II migration 0013 adds prospective terminal screening
provenance and a truthful deterministic-only publication lineage for the accepted
Gemma-disabled path. It never rewrites legacy candidate history. After a fresh
backup and isolated restore gate, apply it with:

```bash
./scripts/migrate-autonomous-screening-decisions.sh
```

The isolated lifecycle check is
`./scripts/test-autonomous-screening-postgres.sh`.

Deploy the worker and Discord-intake image only after the schema exists. The
pre-migration backup is the containment boundary; there is no destructive rollback.

Phase 37 migration 0014 adds private supporting outcome plans/jobs/attempts/results.
It does not enroll a publication or make a provider request merely by being applied.
After a verified backup and disposable lifecycle gate, apply it with:

```bash
./scripts/test-prospective-outcomes-postgres.sh
./scripts/migrate-prospective-outcomes.sh
```

The `supporting-outcomes` profile remains off during ordinary `docker compose up`.
Do not start it unless the account holder has accepted the current $0 provider terms,
created the ignored API-key file, and explicitly approved activation. No public route
or connector network is added. See
[PHASE37_PROSPECTIVE_OUTCOMES.md](PHASE37_PROSPECTIVE_OUTCOMES.md).

Phase 39 migration 0015 adds append-only SEC ownership filing and conservative
routing receipts. It performs no backfill and does not feed the existing filing
candidate queue. After a fresh verified backup, run the disposable lifecycle gate
and then the guarded forward migration:

```bash
./scripts/test-ownership-postgres.sh
./scripts/migrate-ownership-intelligence.sh
./scripts/migrate-ownership-index-identity.sh
```

Both migrations must precede ownership worker activation. There is no destructive
down migration; the verified pre-migration backup remains the containment boundary.

Phase 40 migration 0017 adds private financing intelligence. The mandatory gate then
adds event novelty (0018), Focus history (0019), and validated SEC links (0020). They
must be applied in order only after the complete named-gate backup/restore and disposable
database gates pass:

```bash
./scripts/migrate-financing-intelligence.sh
./scripts/migrate-event-novelty-lineage.sh
./scripts/migrate-focus-universe.sh
./scripts/test-validated-sec-links-postgres.sh
./scripts/migrate-validated-sec-links.sh
```

Migration 0020 performs no historical backfill. Future dossier code must not deploy
before it is live; the verified pre-migration backup remains the containment boundary.

Phase 41 migration 0022 adds the separate private accounting queue and immutable
model-free receipt/routing pairs. SEC-link recovery migration 0023 then corrects only
the database validator for the exact flat daily-index and nested archive complete-
submission paths. Apply both only after their dedicated disposable gates and a fresh
verified backup:

```bash
./scripts/test-accounting-postgres.sh
./scripts/migrate-accounting-compliance.sh
./scripts/test-validated-sec-links-postgres.sh
./scripts/migrate-sec-complete-submission-paths.sh
```

Migration 0023 rewrites no candidate, receipt, brief or publication. Its guarded runner
requires the exact migration history through 0022 and is idempotent.

## Connector configuration

`compose.cloudflare.yaml` is pinned to `cloudflared` 2026.7.2 by image digest,
has no published port, is non-root/read-only/capability-free, checks the private
connector readiness endpoint, joins only `kalki_public_connector`, and is guarded
by the explicit `exposure` profile.
Configuration validation is safe and cannot start it:

```bash
docker compose -f compose.production.yaml -f compose.cloudflare.yaml config --quiet
```

Starting or changing the `exposure` profile requires the same reviewed public
boundary; never add another hostname or origin implicitly.

## Cloudflare activation procedure

The approved initial deployment used these exact dashboard actions. Reuse them
only for recovery of the same hostname and tunnel:

1. In Cloudflare, open **Networking → Tunnels** and create a remotely managed
   Cloudflare Tunnel named `kalki-production`. Do not use a Quick Tunnel and do
   not add any route yet.
2. From **Add a replica**, copy only the `eyJ...` tunnel token into
   `secrets/cloudflare_tunnel_token` as one line, then set the file mode to
   `0644`. Never provide the token to Codex or commit it.
3. Start the connector while the tunnel has no published route, then confirm its
   dashboard status is healthy:

   ```bash
   docker compose -f compose.production.yaml -f compose.cloudflare.yaml \
     --profile exposure up --detach cloudflared
   ```

4. Confirm Universal SSL is active for the zone, TLS mode is not set to an
   insecure downgrade, DNSSEC remains enabled, and the Free Managed WAF ruleset
   is enabled.
5. Create the single Free-plan rate-limiting rule for URI paths beginning with
   `/api/v1/research`: count by IP, 60 requests per 10 seconds, block for 10
   seconds. Leave application-side durable limits enabled. If the dashboard
   shows a charge or the fields are unavailable, stop instead of upgrading.
6. Enable free tunnel-health notifications if offered without a paid upgrade.
7. As the final exposure action, add exactly one **Published application** route:
   hostname `YOUR_PUBLIC_HOSTNAME`, service type `HTTP`, URL
   `public:8001`. The separate service-type selector supplies the `http://`
   scheme; the resulting tunnel origin is `http://public:8001`. Do not add an
   admin, wildcard, private-network,
   SSH, or root-domain route. Cloudflare will create the proxied tunnel DNS
   record when this route is saved; confirm no other record is replaced.
8. From a device not on the origin host, verify HTTPS, exact security headers,
   public pages/API, wrong-host rejection, and `404` for `/admin`, `/admin/login`,
   `/health`, `/docs`, and `/api/openapi.json`. Confirm the origin still has no
   non-loopback listener and no router port forward.

Cloudflare's current documentation describes Tunnel as an outbound connector,
recommends remotely managed tunnels for Docker, supports `--token-file` in
`cloudflared` 2025.4.0 and later, provides the Free Managed WAF subset, and lists
one Free-plan rate-limiting rule. Recheck those current product limits in the
dashboard immediately before activation.

## Rollback and recovery

If any external check fails, first remove/disable the Published application route
in Cloudflare so traffic stops at the edge, then stop only the connector:

```bash
docker compose -f compose.production.yaml -f compose.cloudflare.yaml \
  --profile exposure stop cloudflared
```

If the token may have leaked, rotate it in the tunnel dashboard before writing a
replacement local file. If the app release fails but data is healthy, keep the
tunnel stopped, deploy the last reviewed digest/tag, run local gates, and expose
only after approval. If data recovery is required, keep all application and
connector processes stopped, preserve the damaged volume for diagnosis, and
restore the latest verified backup into a new volume/database. Never restore over
the only copy or discard the damaged volume without explicit approval.

Removing the public route is the tested logical rollback boundary; deleting the
tunnel, DNS records, database volume, or backups is not part of routine rollback.
