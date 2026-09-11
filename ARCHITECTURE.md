# Proposed Architecture

> **Status:** Phases 1–16 implement the reviewed architecture through the supervised
> filing-radar operating layer. Phases 1–11 implement
> the foundation, initial contracts, local-model benchmark, SEC provider,
> disabled rights-aware SEDAR+ boundary, synthetic offline market-data
> abstraction, deterministic calculation engine, validated local analyst
> boundary, versioned ordinal signal engine, append-only prediction/outcome
> contracts, optional outbound Discord notifications, and the local web boundary.
> Phase 12 implements the production/persistence/recovery boundary and publishes
> only the reviewed research process through its healthy Cloudflare connector.
> Admin and operational surfaces remain private. Phase 13 implements deterministic
> point-in-time walk-forward self-evaluation over explicitly incomplete datasets.
> Phase 14 completes measured cache/query optimization and retains the approved
> offline provider boundary. Phase 15 connects official SEC daily-index discovery,
> deterministic excerpt selection, validated local analysts, durable job state,
> immutable research briefs, the public radar, and Discord delivery. Phase 16 retains
> that boundary while replacing the public presentation with the Evidence Observatory
> and retaining the digest-pinned Qwen3 4B analyst after a workload-specific comparison.
> Price-aware
> prediction generation remains inactive without a licensed live market-data source.

## Design goals

Kalki Market Intelligence is intended to be local-first, evidence-backed, replaceable at provider boundaries, and usable without paid AI or market-data APIs. Deterministic software owns numerical calculations. Local AI interprets documents and synthesizes qualitative findings under validated schemas.

The accepted foundation and provider decisions are recorded under [docs/adr/](docs/adr/), including [ADR 0004](docs/adr/0004-sedar-plus-access.md), which keeps SEDAR+ public-site automation disabled. The future database migration approach is documented in [docs/MIGRATIONS.md](docs/MIGRATIONS.md).

## High-level flow

```text
External sources
  -> provider adapters -> ingestion -> raw/normalized records
  -> entity resolution -> PostgreSQL + evidence graph
                                |              |
                  deterministic engine    local AI analysts
                                |              |
                                -> signal engine
                                      |
                    scores + immutable predictions
                                      |
                              outcome tracking
                                      |
                             API -> web interface
                                      -> optional Discord
```

Every downstream conclusion should retain links to its inputs and their publication, retrieval, and availability timestamps.

The deployed Phase 15 path is a deliberately narrower operational slice:

```text
SEC daily index -> durable candidate queue -> SEC complete submission
  -> deterministic relevant excerpt -> private local analysts -> validation
  -> deterministic radar priority -> append-only terminal screening decision
  -> qualified append-only brief -> web + Discord
```

Production Recovery II makes the final autonomous result explicit. Completed
non-qualifying filings are `SCREENED_OUT`; timeouts, invalid analyst contracts,
provider/evidence failures, and other unfinished evaluation are
`ANALYSIS_INCOMPLETE`; only a deterministically valid publication is `QUALIFIED`.
The optional Gemma verifier remains disabled. A qualifying Qwen result therefore
uses the same source, quote, numeric, provenance, schema, and deterministic
publication checks without falsely claiming independent review.

Phase 39 adds a second, deliberately separate SEC ownership path:

```text
SEC daily index -> capped ownership queue -> submissions metadata identity
  -> exact primary XML -> deterministic closed parser -> append-only receipt
  -> conservative model-free routing receipt -> private Mission Control
```

Forms 3/4/5, Form 144, and structured Schedules 13D/13G do not enter the Qwen filing
queue merely because they exist. The ownership queue has its own depth, lease, retry,
and attempt bounds, and successful closure is transactionally tied to primary-source
and routing history. It adds no public route, model concurrency, or trading action.
Duplicate index rows for issuers and reporting owners are retained as a closed CIK
set; the primary document, not row ordering or company-name heuristics, resolves the
issuer.

The mandatory post-Phase-40 gate begins an event-level pre-inference layer within the
same filing pipeline:

```text
bounded SEC evidence -> closed event facts -> append-only prior-lineage comparison
  -> exact recap/historical evidence suppression -> existing Tier-0/Qwen path
```

The filing date never substitutes for event novelty. Unsupported history remains
`UNKNOWN_NOVELTY`; only a complete prior search may establish `NEW_EVENT`. The first
extractor supports narrow strategic-partnership grammar and does not create a second
worker, publication, dossier, or Discord delivery. See
[docs/FRESHNESS_EFFICIENCY_FOCUS_GATE.md](docs/FRESHNESS_EFFICIENCY_FOCUS_GATE.md).

The gate's form-aware evidence budget is currently shadow-only. It deterministically
maps explicit 8-K items and periodic-report sections to exact bounded visible-text
windows with content-free receipt lineage, then benchmarks those packages against the
accepted keyword extractor. A measured fail-closed Koss citation rejection prevents a
runtime switch at this checkpoint; production still uses the accepted extractor and
all model, validation, publication and concurrency boundaries remain unchanged.

Focus membership is a private, availability-aware append-only history keyed by
canonical CIK. Its point-in-time projection feeds priority bands inside the one
existing filing queue. A 24-hour aged-work override ranks the oldest eligible filing
first so non-Focus issuers cannot starve. Focus status creates no second candidate,
model call, brief, publication, route, or notification; the initial migration seeds no
membership and migration/runtime activation remains part of the later integrated gate.

Canonical SEC links use a separate append-only receipt keyed by accession, complete-
submission hash and validation version. Future dossier insertion is transactionally
bound to that receipt; website and Discord rendering receive only its closed URL
projection. Existing dossiers are not rewritten and continue to show their retained
complete-submission URL when no prospective receipt exists.

The adaptive-compute checkpoint is also decision-only. A closed benchmark record binds
the identical-package and measured report hashes to the retained Ollama/Qwen3 4B digest.
A replay-stable content-free receipt then allocates either no LLM, the current bounded
Qwen3 4B path, or a richer-bounded Qwen3 4B shadow route. Receipt validation fixes one
inference slot, the 4,096/768 token envelope, Gemma disabled, and the accepted model
digest. It contains no prompt, source excerpt, response, human research or operations,
and it is not wired into production execution.

The consolidated analyst checkpoint is likewise shadow-only. One bounded response must
cover material facts, catalysts, positive and negative factors, risks, contradictions
and limitations, then pass the same exact evidence-ID, verbatim-quotation, numeric, URL,
lexical-grounding and provenance validators used by the role-specific path. Its lab
alternates execution order over the same frozen packages and retains only hashes,
statuses, counts, tokens and timing. The first three-case replay reduced calls and
latency but yielded zero validated findings in either mode, so it cannot establish
quality non-regression and does not change worker execution.

The fingerprint-cache checkpoint is also contract-only. An exact-reuse receipt binds one
accession to complete-source, bounded-evidence, evidence-manifest and event-fingerprint
hashes plus Tier-0, novelty, selection, extraction, prompt, schema, validator, provider,
model and resource versions. A later knowledge cutoff cannot consume a result that had
not yet validated. Cross-accession output reuse is prohibited. Separately, amendments
and explicitly related successive periodic filings compare closed section manifests;
only added or changed bounded sections can become delta evidence. Removed or missing
sections, changed rules and oversized deltas require full reanalysis. No cache storage or
worker behavior is active yet.

The resource-governor checkpoint is an undeployed pre-claim state machine. Content-free
observations cover CPU package temperature, normalized one-minute load, available RAM,
swap growth, recent inference p95/timeout rate, queue depth/age and the single active-call
slot. Unsafe or unavailable required sensors defer new inference immediately; recovery
uses lower temperature/load/latency limits, higher memory headroom and three consecutive
safe observations. The contract cannot disable SEC discovery or durable persistence and
never cancels an active call. Backlog pressure is advisory and cannot bypass resource
safety. Runtime probes and worker integration remain part of the later guarded gate.

Phase 41 begins with a separate deterministic accounting/compliance evidence boundary:

```text
exact SEC primary HTML -> bounded literal evidence and source offsets
  -> closed accounting event receipt -> point-in-time prior comparison
```

The deployed initial contract recognizes only explicit 8-K Items 3.01/4.01/4.02, NT 10-K/Q,
and bounded periodic-report going-concern/control/accounting language. It records
disclosure categories rather than fraud or market direction. A new-disclosure label
requires a complete prior search, and a record retrieved after the current knowledge
time cannot influence the comparison. The Phase 41 lifecycle adds append-only
receipt/routing pairs and a separate bounded SEC-only queue. Exact retained events
route only to model-free Tier 0; valid filings without exact events close separately,
and bounded acquisition failures retry at most three times. It is deployed privately
and remains disconnected from publication, Discord, Ollama, and every public route. See
[docs/PHASE41_ACCOUNTING_COMPLIANCE.md](docs/PHASE41_ACCOUNTING_COMPLIANCE.md).

Phase 42 adds a separate undeployed deterministic filing-change boundary:

```text
bounded official SEC HTML -> normalized visible corpus -> closed heading selectors
  -> source-offset/hash-bound snapshot -> time-safe section delta
  -> at most 6 exact changes / 3,600 before-and-after characters
```

The first checkpoint admits only explicit amendment, matching successive 10-K/Q, or
supported prospectus relationships for the same canonical CIK. Liquidity, risks, going
concern, debt, issuance, litigation, controls and outlook use closed selectors; added,
removed and modified sections remain visible even when omitted from the bounded evidence
package. Hidden HTML, table-of-contents entries, mismatched issuer/accession URLs and
future retrievals fail closed. No model consumes this receipt yet. See
[docs/PHASE42_FILING_CHANGE_INTELLIGENCE.md](docs/PHASE42_FILING_CHANGE_INTELLIGENCE.md).

The next checkpoint persists these snapshots and their recomputed selection atomically in
private append-only PostgreSQL tables. Exact replays are idempotent; relational columns and
closed JSON must agree on source, manifest, relationship and chronology, while prior lookup
requires both availability and retrieval by the requested knowledge cutoff. The tables have
no public repository projection, and persistence still does not authorize Qwen, cached
output, publication or Discord delivery.

A deterministic lifecycle service sits above that store. It validates a primary source
hash before extraction, applies the current retrieval time as the knowledge cutoff, and
chooses only the latest compatible same-issuer relationship. Explicit amendments prefer
their exact base filing. No prior, no compatible prior and unchanged selected sections stay
distinct from a changed selection; none of these outcomes invokes a model or publishes.

Phase 43 starts with a deterministic convergence boundary:

```text
bounded claim + independently validated numeric facts + point-in-time cutoff
  -> issuer/time/source reconciliation -> recomputable contradiction receipt
```

The initial predicates cover cash versus current liabilities, evidence of dilution,
and net executed insider acquisition. Outcomes are closed to supported, conflicted,
insufficient, or not applicable. Registration shares alone do not establish issuer
dilution, and Form 144 does not become an executed sale. Missing completeness,
incomparable periods, cross-issuer facts, future retrievals, or conflicting provenance
fail closed. A private append-only PostgreSQL receipt stores the complete recomputable
record and mirrors its closed identity, claim, cutoff, disposition, counts, hash and rule
version in indexed relational columns. Exact replay is idempotent, point-in-time reads
cannot see later receipts, and database triggers reject schema, lineage and mutation
violations. Migration 0026 is live. The producer layer feeds the same private service
from the existing research, financing, and
ownership workers without another queue or fetch. It admits only an unambiguous latest
same-filing USD XBRL cash/current-liabilities pair, explicit active potentially issuable
financing exposure, or one exact Section 16 date/derivative scope; Form 144 stays not
applicable and Schedule 13 records stay outside transaction convergence. The producer
claim binds a separately validated routing/selection manifest while facts retain their
primary receipt lineage. No model, signal, publication, notification, or public
projection uses the boundary. The first genuine prospective Form 4 receipt is retained
and recomputes exactly. Authenticated Mission Control reads only lifetime aggregate
family, disposition, and closed producer-source counts; receipt content and identities
remain outside that projection.

Phase 44 adds a deterministic reporting boundary over the separate Phase 37 supporting-
outcome ledger:

```text
immutable dossier version + append-only supporting outcome
  -> origin/version stratification -> exact counts + Wilson uncertainty
  -> INSUFFICIENT_SAMPLE or INCONCLUSIVE
```

Only post-protocol-lock `GENUINE_FORWARD` observations enter descriptive calibration or
power assessment. `RECONSTRUCTED` records remain separately counted, unavailable rows
remain in coverage, and non-positive relative outcomes remain adverse. Horizon, dossier/
rules/model/prompt versions, outcome methodology/calculation/schema, provider and terms
form closed cohort boundaries. Live migration 0027 replaces the Phase 37 insert validators
without backfill: PostgreSQL independently reconciles immutable publication enrollment,
complete plan and attempt lineage, closed bar identity and knowledge time, unavailable-
result limitations, and round-half-even 34-significant-digit asset, benchmark and relative
returns. There is no public route or provider activation, and the empty ledger yields no
empirical result. Authenticated Mission Control consumes the same point-in-time repository
through an aggregate-only adapter; cases, publications, bars, returns, provider responses
and private identities never enter its template context.
See [docs/PHASE44_OUTCOME_SCIENCE.md](docs/PHASE44_OUTCOME_SCIENCE.md).

## Components

### Provider abstractions

Source-specific adapters will expose normalized internal interfaces rather than leak vendor formats into the rest of the application. Initial priorities are SEC EDGAR/data.sec.gov, SEDAR+, company investor-relations pages, official releases, government and regulatory sources, and reputable sources that permit programmatic access. Lower-trust sources may support discovery but should not establish material facts by themselves.

Adapters must respect authentication, robots policies, terms, paywalls, access controls, and rate limits. A provider can be replaced without redesigning analysis or storage.

The Phase 4 assessment found no authorized zero-cost automated SEDAR+ path. Its
public-site adapter therefore fails closed. A future licensed or approved feed must
carry explicit rights and expiry metadata through the provider boundary before
normalization. See [docs/CANADIAN_INGESTION_ASSESSMENT.md](docs/CANADIAN_INGESTION_ASSESSMENT.md).

Phase 5 adds swappable market-data providers for reference records, equity and
benchmark bars, and corporate actions. Currency plus separate price/volume
adjustment bases are mandatory. Point-in-time filtering requires both availability
and retrieval before the knowledge cutoff. Only synthetic offline implementations
are approved; see [docs/MARKET_DATA.md](docs/MARKET_DATA.md) and [ADR 0005](docs/adr/0005-market-data-offline-baseline.md).

### Ingestion and normalization

Ingestion workers will fetch permitted documents and datasets, retain provenance, and make retries idempotent. Normalization will standardize identifiers, issuers, securities, exchanges, currencies, units, reporting periods, event types, and timestamps. Entity resolution will explicitly handle ticker changes, multiple listings, corporate actions, and ambiguous company names.

Raw source material and normalized facts should remain distinguishable. Corrections append or supersede records with an audit trail rather than silently rewriting historical knowledge.

Phase 3 implements the first adapter for SEC submissions and companyfacts. It uses
stable normalized IDs, exact content hashes, conservative retrieval-time
availability, and content-addressed local raw storage. The boundary and its current
coverage are documented in [docs/SEC_INGESTION.md](docs/SEC_INGESTION.md); database
persistence and scheduled orchestration remain future work.

### PostgreSQL

PostgreSQL is the proposed system of record for normalized entities, facts, evidence metadata, analysis records, scores, predictions, outcomes, job state, and access-control data. Large source documents may later live on local object-like storage while PostgreSQL retains content hashes, metadata, and references.

Schemas should enforce UTC timestamps, uniqueness, referential integrity, immutable prediction fields, and explicit data availability time. Migrations and backups will be designed and tested before operational use.

The mandatory post-Phase-40 measurement checkpoint adds a private append-only catalog
for 20 versioned engineering metrics, aggregate receipts, and content-free filing
lifecycle latency receipts. PostgreSQL reconciles each closed JSON record to relational
columns, rejects extra fields and mutation, and treats NULL lifecycle keys as equal for
uniqueness. Definitions are seeded, but no historical observation is backfilled.
Unavailable and partial telemetry remain explicit, and unknown authoritative first-known
time makes dependent latency unavailable. Migration 0021 and hourly private generation
are deployed; shadow routing, consolidation, caching and resource-governor decisions
remain non-authorizing.

### Deterministic quantitative engine

Ordinary tested code—not an LLM—will calculate prices, returns, moving averages, RSI, MACD, ATR, volatility, relative volume, financial ratios, growth rates, 52-week positioning, and other reproducible values. Calculations will record input versions, parameters, effective times, currencies, and adjustment rules.

Phase 6 implements the first dependency-free Decimal engine and immutable lineage
contracts for those baseline metrics. It rejects stale/future, insufficient,
unadjusted, unit/currency-incompatible, and zero-denominator inputs. Formula
semantics and current limitations are documented in
[docs/QUANTITATIVE_ENGINE.md](docs/QUANTITATIVE_ENGINE.md) and
[ADR 0006](docs/adr/0006-deterministic-quantitative-engine.md).

### Local-model analysis

A configurable model-provider boundary will initially target Ollama. Structured analyst roles may cover document interpretation, catalysts, partnerships, management commentary, source comparison, contradictions, bull/bear cases, and qualitative risks. All AI output must pass schema and evidence-reference validation before persistence. Unsupported fields are rejected or marked unknown.

Phase 2 established CPU-only `qwen3:4b` through loopback-only Ollama as a hardware baseline, not a production analyst implementation. The measured scope and limitations are documented in [docs/MODEL_BENCHMARK.md](docs/MODEL_BENCHMARK.md).

The mandatory post-Phase-40 serving lab adds a second provider only inside an
ephemeral Docker-internal benchmark boundary. It mounts the exact Qwen GGUF blob
read-only, accepts no tools or public origin, discards hidden reasoning, and returns
only final content to the unchanged analyst validators. Its CPU and partial-Vulkan
measurements did not authorize a production switch, so the deployed architecture
continues to serialize Qwen3 4B through private CPU-only Ollama. See
[docs/MODEL_SERVING_LAB.md](docs/MODEL_SERVING_LAB.md).

Phase 7 adds the no-tools provider boundary, six narrow roles, prompt versioning,
closed schemas, bounded repair, injection quarantine, exact citation/quote/figure
validation, lexical inference grounding, and auditable deterministic contradiction
normalization. See [docs/AI_ANALYST_PIPELINE.md](docs/AI_ANALYST_PIPELINE.md) and
[ADR 0007](docs/adr/0007-untrusted-local-analyst-boundary.md).

### Evidence and source tracking

An evidence graph will connect sources, documents, extracted claims, normalized facts, calculations, analyses, signals, and predictions. Trust metadata should include source class, retrieval method, content hash, publication time, retrieval time, and the earliest time the information was available to the system.

This lineage is central to public research pages, contradiction handling, auditability, and prevention of look-ahead bias.

### Signal generation and scoring

The signal engine will combine versioned deterministic metrics and validated qualitative findings. Opportunity, risk, and research-confidence scores must remain separate so a high-upside speculative idea cannot appear conservative. Initial confidence is ordinal research confidence, not a calibrated probability.

Rules, weights, thresholds, missing-data behavior, and model/prompt versions must be stored. Human-readable labels include Strong opportunity, Moderate opportunity, Speculative opportunity, Weak opportunity, and Insufficient evidence.

Phase 8 implements ruleset `1.0.0` with strict input time/subject/evidence gates,
separate heuristic point scales, critical missing-input behavior, conservative
versus aggressive/speculative profiles, result fingerprints, and complete
contribution traces. See [docs/SIGNAL_ENGINE.md](docs/SIGNAL_ENGINE.md) and
[ADR 0008](docs/adr/0008-versioned-ordinal-signals.md). The rules are not yet
historically calibrated and no result is persisted or published.

### Predictions and outcomes

A prediction becomes immutable once published. It records the thesis, horizon, benchmark, evaluation rule, available evidence, score versions, and creation time. Later processes append outcomes without altering the original prediction. Delisted, acquired, renamed, and failed companies remain represented to reduce survivorship bias.

Phase 9 implements closed immutable prediction snapshots, appended corrections
and outcomes, deterministic point-in-time return evaluation, descriptive reports,
and a SHA-256-chained application ledger. Its first PostgreSQL migration enforces
foreign keys and rejects update, delete, and truncate operations; the isolated
database gate passes. See
[docs/PREDICTIONS_AND_OUTCOMES.md](docs/PREDICTIONS_AND_OUTCOMES.md) and
[ADR 0009](docs/adr/0009-append-only-predictions.md).

Phase 12 adds the production adapter that revalidates stored Phase 9 JSON through
the closed Pydantic contract before presenting it. A least-privileged PostgreSQL
role can read publication tables, maintain durable web sessions/rate events, and
append—but not erase—closed security audits. PostgreSQL has a checksummed durable
volume, no host port, ordered initialization migrations, and an isolated
backup/restore rehearsal. See
[docs/PRODUCTION_DEPLOYMENT.md](docs/PRODUCTION_DEPLOYMENT.md).

Phase 13 separates historical universe membership, immutable prediction snapshots,
and later outcomes under closed contracts. Exact case coverage retains delisted,
bankrupt, and unavailable outcomes. Chronological tuning, validation, and held-out
partitions plus a pre-held-out policy lock prevent cross-period tuning. Reports use
deterministic cost sensitivity, error categories, sample counts, and Wilson intervals;
the current fixture is wholly synthetic. See [docs/BACKTESTING.md](docs/BACKTESTING.md)
and [ADR 0013](docs/adr/0013-point-in-time-walk-forward-evaluation.md).

Phase 14 bounds public list queries and backs their exact ordering with a reversible
PostgreSQL index. The market-data cache uses per-key single-flight loading so unrelated
provider calls can progress concurrently without duplicating identical misses. No
normalized contract or provenance boundary changed. See
[docs/PHASE14_OPTIMIZATION.md](docs/PHASE14_OPTIMIZATION.md) and
[ADR 0014](docs/adr/0014-measure-before-optimization.md).

Phase 37 adds a separate private outcome-observation path over immutable filing
dossiers. A real exchange calendar fixes the first close at or after publication and
the T+1/T+5/T+20 target closes before provider retrieval. A replaceable, disabled
Twelve Data adapter may supply split-adjusted daily asset and SPY bars only after an
account-holder approval. Deterministic Decimal code calculates price and benchmark-
relative returns; PostgreSQL preserves provider hashes/timestamps, attempts, explicit
`GENUINE_FORWARD` versus `RECONSTRUCTED` origin, unavailable results, and append-only
history. This supporting ledger neither turns dossiers into forecasts nor exposes
licensed market data publicly. See
[docs/PHASE37_PROSPECTIVE_OUTCOMES.md](docs/PHASE37_PROSPECTIVE_OUTCOMES.md).

### API and web layers

Phase 11 implements a FastAPI application factory over a read-only research
repository protocol. Pydantic response contracts expose only deliberate public
fields; server-rendered Jinja views share those projections and escape untrusted
text. The single-admin workspace can inspect complete immutable records and a
secret-free process-local audit trail, but it cannot rewrite publications.

Authentication uses a locally injected Argon2id password hash, generic credential
errors, throttled attempts, one-time login CSRF tokens, and random server-side
sessions stored only as token digests. Sessions have idle and absolute expiry,
bind to hashed client metadata, and use HttpOnly SameSite=Strict cookies. The app
also enforces trusted loopback hosts, general request throttling, bounded mutating
bodies, protected admin routes, no-store admin responses, a restrictive content
security policy, and no interactive API documentation. The command-line server
accepts only `127.0.0.1` or `::1`; public deployment remains absent. See
[docs/WEB_APPLICATION.md](docs/WEB_APPLICATION.md) and
[ADR 0011](docs/adr/0011-local-web-security-boundary.md).

For production preparation, Phase 12 physically separates the public and admin
route tables into different processes. The public process contains only research
pages, deliberate read-only API projections, and static assets. The admin process
remains bound to host loopback. Sessions, throttling state, and security audits
survive application restarts in PostgreSQL.

Phase 35 defines one public-library read model over the two immutable public tables.
The `/research` page merges filing dossiers and explicit forecasts in deterministic
UTC publication order, gives each row a closed type-specific projection, and links
to the existing `/radar/{brief_id}` or `/research/{prediction_id}` detail. Existing
API contracts stay namespaced by record type. Private human-result tables are not
part of the query.

Phase 36 versions future private human results as self-contained provenance records.
The worker binds resolved SEC source/hash identity, bounded XBRL and deterministic
receipts, Tier-0 routing, and completed content-free Qwen attempt receipts before an
append-only result plus private delivery head can be inserted. Legacy rows stay
unchanged with unavailable lineage represented as UNKNOWN.

### Optional integrations and deployment

Phase 10 adds an optional outbound-only Discord webhook adapter. It is disabled by
default, requires an origin-validated secret from local configuration, suppresses
mentions, rate-limits and deduplicates sends, and records secret-free delivery
audits. Ambiguous failures are not automatically retried because Discord webhooks
do not provide an application idempotency key. A synthetic message was confirmed
in the approved private destination; see
[docs/DISCORD_INTEGRATION.md](docs/DISCORD_INTEGRATION.md) and
[ADR 0010](docs/adr/0010-safe-discord-notifications.md).

The Phase 12 connector is active on its remotely managed tunnel and joins only
the public-process network. Its Published Application routes only
the operator-configured hostname (shown publicly as `YOUR_PUBLIC_HOSTNAME`) to that
process. Admin is never a
tunnel target. See the
[threat model](docs/PHASE12_THREAT_MODEL.md).

## Security and trust boundaries

- **Internet to ingestion:** all remote content is untrusted. Validate types and sizes, sanitize parsing, limit requests, and never execute retrieved content.
- **Raw to normalized data:** preserve provenance; normalization must not turn an inference into a sourced fact.
- **Database to model:** minimize supplied data and resist prompt injection embedded in filings or pages. Model output is untrusted until validated.
- **Model to signal engine:** require schemas, evidence references, bounded fields, and deterministic policy checks. AI must not supply authoritative financial calculations.
- **Public to API:** expose only intended read-only research; enforce rate limits and prevent access to admin, operational, and secret data.
- **Admin boundary:** use strong authentication, least privilege, protected sessions, audit logs, and secure recovery. Never commit credentials.
- **Host and storage:** use isolated dependencies and least-privileged services. Raw data, models, exports, and backups stay out of Git.
- **Notifications:** treat webhook credentials as secrets and prevent alerts from becoming trade instructions or promises of returns.

No component will connect to a brokerage or execute trades.
