# Live filing radar

> **Status:** Phase 15 is deployed and live. The first genuine end-to-end SEC,
> local-model, validation, PostgreSQL, website, and Discord gate completed at
> 2026-08-25 04:32:05 UTC.

## What it does

The worker polls the SEC's official daily EDGAR master index. It retains listed
companies with 8-K, 10-Q, 10-K, 6-K, 20-F, or 40-F filings and deduplicates them by
accession number. It fetches the authoritative complete-submission file, removes
non-visible markup, and uses deterministic keyword-centred windows to find bounded
catalyst and risk passages. Production Recovery II limits model evidence to six
560-character windows and 3,600 total characters. When both opportunity and risk
terms exist, one window for each side is reserved before filling the remaining
windows in filing order; only terms retained in the excerpt contribute downstream.

Only those passages reach the private `qwen3:4b` model. Two narrow analyst roles
review them. Existing Phase 7 controls require closed JSON, exact quotations,
supported figures and URLs, matching evidence IDs, allowed categories, model
digests, and UTC cutoffs. Rejected or prompt-injection-like content is not
published.

Ordinary code derives research attention, risk pressure, and evidence strength.
They are heuristic priority points, not probabilities, valuations, price targets,
or expected returns. A brief is a filing-driven candidate for further research,
not a prediction and never a trade instruction. The immutable prediction ledger
remains separate and still requires licensed point-in-time market data.

## Continuous operation

Compose supervises `postgres`, `ollama`, `worker`, `admin`, and `public` with
`restart: unless-stopped`. `cloudflared` remains separately guarded by the existing
approved exposure profile. Ollama and the worker have no published ports. Their
`analyst` network is internal; only the worker also joins the database network.
The public process joins neither network. A worker-only `research_egress` bridge
provides outbound NAT for SEC retrieval and Discord delivery without publishing a
port; code-level URL validation still restricts those clients to their approved
HTTPS origins.

The Compose model service mounts the complete reviewed user-local Ollama runtime:
the server binary, its CPU runner libraries, and the ignored model store. Override
`KALKI_OLLAMA_BIN`, `KALKI_OLLAMA_LIB`, and `KALKI_OLLAMA_HOME` only when that
installation lives elsewhere.

The worker polls every 15 minutes when caught up and continues after one minute
while work is queued. Each run claims at most two filings, retries a recoverable
failure twice with increasing delay, and persists bounded error codes rather than
raw external text. Durable status exposes heartbeat, last success, next run, queue
counts, publication counts, model identity, and Discord state at
`/api/v1/radar/status`.

Each actual Qwen role/repair request is also started durably before provider I/O
and completed with content-free attempt metadata. Candidate and private-human
origins cannot be conflated. A timeout or schema/evidence rejection is therefore
measurable without retaining the response. Local analyst failures stop after three
work attempts because repeated deterministic five-minute calls dominated attempts
four through six; terminal exhaustion is `ANALYSIS_INCOMPLETE`, never screened out.
See `PHASE33_QWEN_RELIABILITY.md`.

## One-time activation

SEC asks automated clients to identify the application and a contact address. Do
not invent one. Add a monitored address locally without placing it in chat or Git:

```dotenv
KALKI_SEC_USER_AGENT="Kalki Market Intelligence monitored-address@example.com"
```

Then reload only the worker so the read-only secret mount is refreshed:

```bash
docker compose -f compose.production.yaml up --detach --force-recreate worker
```

Watch public-safe state rather than printing configuration:

Replace `YOUR_PUBLIC_HOSTNAME` with the hostname configured in your ignored `.env`.

```bash
curl --fail https://YOUR_PUBLIC_HOSTNAME/api/v1/radar/status
docker compose -f compose.production.yaml logs --tail 100 worker
```

The worker will move through `running` to `idle` or `degraded`. A degraded provider
run stays supervised and retries; it does not fabricate a brief.

## Discord behavior

When the ignored local Discord settings are enabled, the worker finds published
briefs with no terminal delivery, sends a bounded research-only message, and saves
the secret-free result. Sent and delivery-uncertain keys suppress automatic resend.
Disabled, rejected, and rate-limited attempts do not erase the publication.

## First production gate

The activation run used the latest official daily master index and discovered 227
listed-company filings. The worker processed two: Mayfair Gold Corp. (`MINE`) was
accepted as a filing-driven `watch` brief with one validated normalized excerpt;
Expion360 Inc. (`XPON`) was deterministically skipped. The immutable brief became
public at 2026-08-25 04:24:12 UTC and its Discord delivery audit reached `sent`
with one attempt and a returned message identifier. The completed run recorded 227
discovered, two analyzed, one published, one skipped, no error, and 17 minutes 24
seconds elapsed. No synthetic record was inserted into production.

## Recovery and limits

Migration `0004_live_research_radar` creates mutable candidate/worker state and
separately trigger-protected append-only briefs, run records, and notification
delivery records. It has no automatic destructive rollback. Restore the verified
pre-migration backup into a new database if release rollback requires removing the
schema; never drop live research tables automatically.

Migration `0010_analyst_attempt_receipts` adds completion-once analyst telemetry.
It is included in checksummed backup/restore manifests and has no destructive down
migration.

This feed is US-filing-led. Canadian SEDAR+ automation remains prohibited at the
current access boundary. SEC daily indexes are filing-date discovery rather than a
real-time price feed. The local model is CPU-bound, source excerpt selection is
conservative, and every public page discloses the absence of licensed live
price/volume data.
