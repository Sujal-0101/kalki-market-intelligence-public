# Kalki Market Intelligence — Initial Project Specification

> **Status:** Living specification established in Phase 0. It describes intended behavior and constraints, not completed features.

## 1. Purpose and scope

Kalki Market Intelligence will be a continuously running, local-first stock research platform for United States and Canadian equities. It should cover large-, mid-, small-, micro-, and speculative-cap companies, with a primary research horizon of one to six months.

Research may consider momentum, fundamentals, valuation, technical analysis, earnings, partnerships, contracts, regulatory events, catalysts, sector conditions, market regime, and risk. Conservative and aggressive opportunities must be clearly distinguished.

The eventual product should offer evidence-backed public research pages and a secure authenticated admin research interface. It may later support trusted additional users and optional Discord notifications.

The accepted public filing model has three disjoint views: `/radar` contains only
qualified immutable filing dossiers, `/research` combines qualified dossiers and
explicit forecast records, and `/screened` contains only autonomous SEC filings
whose required evaluation completed without qualifying. Analysis-incomplete work
is summarized separately and private human research is never queried by these
public projections.

## 2. Non-goals and required disclosures

The application is research-only. It must never:

- execute trades or connect to a brokerage;
- automatically buy or sell securities;
- promise returns; or
- present research confidence as a calibrated probability before sufficient historical evidence supports calibration.

Initial labels should use terms such as:

- Strong opportunity
- Moderate opportunity
- Speculative opportunity
- Weak opportunity
- Insufficient evidence

Opportunity, risk, and research confidence are distinct concepts and must not be collapsed into a misleading single claim.

## 3. Operating constraints

- Initial paid API budget is $0/month.
- Existing ChatGPT and Gemini subscriptions do not imply API access and must not be treated as unlimited APIs.
- Local AI is the default.
- Development remains private; no service is publicly exposed without explicit approval.
- A public site may be deployed later with a small, explicitly approved domain budget.
- One secure admin account is required initially; the design may later permit additional trusted users.
- Optional private Discord integration was approved on 2026-08-24. Its outbound
  adapter remains disabled by default. The approved private destination and
  webhook are configured only in ignored local settings; no secret is committed.
- No paid cloud resource, account, API key, token, webhook, or tunnel may be created without approval.
- Secrets must not be committed to Git.
- Python dependencies must use containers, `uv`, or another isolated environment; Ubuntu's system Python must not be modified.

## 4. Data-source policy

Preferred source order is:

1. SEC EDGAR and data.sec.gov
2. SEDAR+
3. Company investor-relations pages
4. Official press releases
5. Government and regulatory sources
6. Reputable news sources with permitted programmatic access
7. Lower-trust public sources for discovery only

The system must not bypass authentication, CAPTCHAs, robots restrictions, paywalls, rate limits, terms, or access controls. External sources and market-data services must sit behind normalized internal provider interfaces so one vendor cannot become a permanent architectural dependency.

Licensing, redistribution, retention, attribution, and programmatic-access terms must be reviewed for each provider before implementation.

The Phase 4 review determined that current SEDAR+ public-site terms prohibit the
automated access and database construction required by this platform. Live SEDAR+
ingestion remains disabled unless a separately reviewed licensed distribution or
approved source is obtained. Other Canadian sources must be labeled as incomplete
fallback coverage rather than SEDAR+ equivalents.

## 5. Data provenance and evidence

Every important conclusion must trace to retrieved evidence. At minimum, source records should preserve:

- source identity and class;
- canonical locator where permitted;
- publication timestamp;
- retrieval timestamp;
- availability timestamp: when the system could first have known the information;
- content hash/version and retrieval status; and
- relationships among documents, extracted claims, normalized facts, calculations, analyses, signals, and predictions.

Timestamps are stored internally in UTC. Display-time conversion is a presentation concern. Raw evidence, normalized facts, inferences, and model-generated synthesis must remain distinguishable.

The system must never invent financial figures, sources, filings, quotations, URLs, announcements, or undisclosed partnership terms. Unknown and conflicting information must be represented honestly.

## 6. Deterministic computation

Ordinary software, with versioned and tested formulas, must calculate prices, returns, moving averages, RSI, MACD, ATR, volatility, relative volume, financial ratios, growth rates, 52-week positioning, and other deterministic values.

Calculations must record relevant inputs, effective dates, parameters, units, currencies, adjustment choices, and implementation versions. Missing, stale, incompatible, or future inputs must fail safely rather than produce plausible-looking values.

## 7. AI responsibilities and controls

AI may assist with document interpretation, catalyst analysis, partnership significance, management commentary, source comparison, contradiction detection, bull/bear analysis, risk analysis, and qualitative synthesis.

The default model provider will be configurable and local, initially through Ollama after a separate approved installation and benchmark phase. AI roles should have narrow responsibilities. Outputs must use validated structured schemas, cite retrieved evidence identifiers, and be treated as untrusted until deterministic validation succeeds.

Prompt injection within source documents is an expected threat. Retrieved text must not grant tools, change system policy, or authorize actions. AI must not become the authoritative calculator or silently convert inference into fact.

## 8. Planned system capabilities

The proposed system includes:

- compliant provider adapters and ingestion jobs;
- normalization and entity resolution;
- PostgreSQL as the structured system of record;
- a deterministic quantitative engine;
- a configurable local-model provider and structured analyst roles;
- an evidence graph and contradiction tracking;
- separate opportunity, risk, and research-confidence scoring;
- explainable signal generation;
- immutable predictions and appended outcome tracking;
- a typed API, responsive public research pages, and a secure admin interface;
- optional Discord notifications;
- an outbound Cloudflare Tunnel connector with its Published Application limited
  to the explicitly approved public research hostname; and
- backtesting and self-evaluation designed against look-ahead and survivorship bias.

Phase 15 implements the first continuously operating research slice: official SEC
daily-index discovery, bounded filing-excerpt selection, validated private local-model
analysis, durable work state, immutable filing-radar briefs, automatic Discord
handoff, and a searchable public radar. Filing briefs remain separate from predictions
because no approved live market-price provider exists. The live worker must expose a
configuration or provider failure honestly rather than create placeholder research.

Phase 16 gives that slice an editorial-observatory public language. Its radar may use
decorative sweep, ring, angle, and distance only when the legend says those variables
are non-quantitative. Every labelled security blip must map to a real immutable brief;
empty mode renders none. Model interpretation, deterministic measures, normalized
source excerpts, and limitations remain visibly separate. The public experience stays
server-rendered and script-free.

Phase 35 defines the public publication read model. `/research` chronologically
lists both immutable filing dossiers and explicit forecast records with distinct
type labels and canonical detail URLs. Dossiers remain searchable under `/radar`
and are never represented as price-aware forecasts. The existing forecast-only
`/api/v1/research` contract remains compatible, dossier APIs remain under
`/api/v1/radar`, and private human research results are excluded by construction.

Production Recovery II adds a third, disjoint public read model. `/screened` is a
read-only “Screened filings” or “Research screening activity” page for autonomous
SEC filings whose required research evaluation completed but did not qualify for a
dossier. `/radar` remains qualified filing dossiers and `/research` remains the
combined qualified public library. Analysis failures, timeouts and unfinished
required processing are `ANALYSIS_INCOMPLETE`, not screened out.

The `/screened` projection may contain only ticker, company, SEC form, filing time,
screening/decision time, bounded terminal result/reason, and an existing validated
canonical SEC link. It must never query or expose human Discord research, hypotheses,
private channel/user IDs, prompts, raw model output, hidden reasoning, unapproved
source excerpts, internal exceptions or provider/timeout details, stack traces,
host paths, secrets or admin telemetry. Historical rows without a provable reason
remain `LEGACY_REASON_UNAVAILABLE` or `UNKNOWN`; immutable history is not guessed or
rewritten. Rolling public activity counts must label partial telemetry windows and
separate completed screening from analysis-incomplete work.

Phase 39 ownership intelligence must consume Forms 3/4/5, Form 144, and structured
Schedules 13D/13G through a queue that is physically separate from the filing/Qwen
candidate backlog. Admission depth, per-cycle work, claim leases, retries, and
attempts are bounded. Each successful result must reconcile daily-index identity,
submissions metadata, the exact SEC primary document, its hash and UTC retrieval
time, a closed deterministic receipt, and conservative routing in one immutable
history. An insider sale is not automatically bearish, Form 144 is a planned-sale
notice rather than a completed sale, and Schedule Item 4 text is not automatically
activist intent. Ordinary context stays model-free; a bounded-review route neither
publishes nor bypasses existing evidence and publication gates. Ownership operations
remain private and add no public route, brokerage path, model concurrency, paid
dependency, or private human-research exposure.

### Mandatory post-Phase-40 freshness, efficiency and focus requirements

The filing timestamp and the underlying event's novelty are independent. After
Phase 40 and before Phase 41, Kalki must add a first-class, versioned event-novelty
disposition: `NEW_EVENT`, `MATERIAL_UPDATE`, `RECAP_EXISTING_EVENT`,
`DUPLICATE_DISCLOSURE`, `HISTORICAL_CONTEXT`, or `UNKNOWN_NOVELTY`. No fixed-age
rule may substitute for evidence. Append-only event lineage should retain, when
supported, canonical issuer/CIK, event category, normalized entities and
counterparties, deterministic event/fact fingerprint, supported dates and numeric
terms, authoritative first-known disclosure, current disclosure, prior related
event, disposition, evidence/provenance and schema/rule version. Unknown historical
dates remain unknown; old events remain stored.

The required novelty regression separates a later disclosure from an already-known
strategic infrastructure-financing partnership using clearly synthetic entities,
reserved identifiers and invented fixture prose. Repeated partnership content is
`RECAP_EXISTING_EVENT` and cannot produce a fresh partnership catalyst. A later
source with genuinely new supported terms is `MATERIAL_UPDATE`. The original
disclosure date must not be guessed. SEC remains authoritative; official issuer
IR or press-release sources require bounded, terms/licensing-safe adapters. Random
news scraping, paid feeds and social-media dependencies are excluded.

Before local-model inference, a form-aware deterministic budgeter must select 8-K
items, relevant 10-Q/10-K sections and reliable amendment/diff evidence while
preserving exact citations and material dates, amounts, percentages, share counts,
counterparties, financing terms, going-concern and auditor/accounting language,
management changes and listing/regulatory matters. Repeated boilerplate may be
deprioritized by explicit rules, not blindly deleted. Measurement must compare
evidence characters/tokens, analyst latency, timeout rate and evidence/numeric
fidelity. Context stays at the accepted 4,096 baseline globally; any richer bounded
package requires benchmark evidence and does not imply a global 8,192 change.

A versioned curated Focus Universe may prioritize widely followed or user-interest
issuers, but all SEC filings still use one pipeline and one immutable decision or
dossier. `/focus` and a future private Discord `#focus-signals` view may project the
same dossier only; membership cannot duplicate inference, publication or delivery.
The system continues monitoring penny stocks, small caps, mid caps and obscure
issuers, with aging/fairness that prevents non-Focus starvation. No external
Discord channel is created by this specification.

Website and Discord SEC links must validate the authoritative filing archive/index
and primary-document URL. Inline-XBRL links are allowed only when actually valid;
an invalid SEC URL must never be manufactured.

Prospective validation is retained in an append-only receipt keyed by accession,
complete-submission hash and validation version. A future dossier must reference that
receipt before publication. Public website and Discord rendering receive only the
closed URL fields; validation hashes and operational data remain outside the rendering
contract. Historical immutable dossiers are not backfilled or rewritten.

Production remains on private Ollama plus pinned Qwen3 4B after an isolated,
licensing-safe benchmark replayed identical genuine evidence packages. The same
Q4_K_M blob under digest-pinned llama.cpp timed out on all three CPU cases and reached
the CPU's thermal threshold; the optional Intel Vulkan partial-offload path did not
establish a replacement, while NVIDIA/CUDA was not a supported container path. The
lab records token rates when a runtime returns them, total and p50/p90/p95 latency,
timeout/schema rates, evidence/numeric fidelity, RAM, swap, CPU temperature and
public-service impact without retaining model content in its reports. Qwen3 8B
Q4_K_M remains only a future escalation candidate and was not downloaded. System
RAM/CPU is primary capacity; the GeForce 940MX is optional and must not limit loadable
quantization. Cloud/paid inference, new model concurrency and Gemma remain prohibited.

Only measured results may authorize an adaptive router: deterministic rejection
uses no LLM; normal events use Qwen3 4B with bounded evidence; complex events may
use richer bounded Qwen3 4B evidence; and an important ambiguous case may escalate
to Qwen3 8B only after demonstrated benefit. The current multi-role Qwen contract
also remains unchanged until a shadow one-call response covering facts, catalysts,
positive/negative factors, risks and limitations proves material throughput benefit
with no evidence, numeric, provenance or schema regression.

The current engineering checkpoint authorizes only the first three decision classes,
with the richer Qwen3 4B class remaining shadow-only. A closed benchmark decision binds
the measured package/report hashes and accepted model digest; a deterministic routing
receipt binds accession, source/evidence hashes and size, Tier-0 decision hash,
complexity/importance reasons, exact resource envelope and single-inference limit. It
contains no source or model content and cannot itself execute work. Qwen3 8B, llama.cpp,
Gemma, concurrent inference and any production routing switch remain unavailable.

The first one-call consolidation replay is also non-authorizing. It reduced six
role-specific calls to three consolidated calls and measured a 0.3987 total-latency
ratio on three frozen packages, but both modes produced zero validated findings. That
is insufficient substantive evidence for the required evidence/numeric/provenance
comparison. The accepted multi-role production contract therefore remains unchanged;
future comparison needs a frozen set with validator-accepted substantive findings and
must continue to use the same deterministic validators and one-attempt boundary.

Versioned event/evidence fingerprints may cache identical work, but amendments and
new filings must isolate changed material evidence and model output cannot be reused
across differing evidence, rules, prompts/schemas or models. A later conservative
resource governor observes CPU temperature/load, RAM, swap, inference latency and
queue depth; when constrained it preserves SEC discovery/persistence and defers
expensive inference. It is not deployed before benchmark and recovery tests.

Phase 42 filing-change selection uses a separate versioned deterministic receipt before
any optional interpretation. It binds same-issuer SEC accession/source/hash and filing,
availability and retrieval times; admits only explicit amendment, successive 10-K/Q or
supported prospectus relationships; and retains every added, removed or modified section
identity. Selection is limited to liquidity, risks, going concern, debt, issuance,
litigation, controls and outlook, with no more than six changed sections and 3,600 exact
before/after characters. Omitted changes remain explicit and a text change alone is not
a materiality claim. See
[docs/PHASE42_FILING_CHANGE_INTELLIGENCE.md](PHASE42_FILING_CHANGE_INTELLIGENCE.md).

A functional event-map radar is deferred until its semantics are defensible: event
direction/impact class, evidence strength, materiality/attention and event category
are candidate axes/encodings, not arbitrary pseudo-scientific scores. Deterministic
section/event diff and XBRL/CompanyFacts remain preferred over adding vector RAG or
multimodal vision. Vectors or vision require a later measured problem that
structured SEC evidence cannot solve.

Required engineering metrics are false-new publication rate, recap-suppression
accuracy, material-update recall, fresh-event precision, Qwen calls per filing,
evidence characters/tokens, p50/p90/p95 analyst latency, timeout rate, queue
depth/age, thermal/resource state, publication and Discord exact-once, first-known
authoritative-disclosure-to-discovery latency, discovery-to-publication latency and
authoritative-disclosure-to-alert latency. Unknown first-disclosure time makes those
latencies unavailable. These metrics make no market-alpha or investment-performance
claim.

The item-12 engineering checkpoint represents these definitions as closed versioned
ratio, distribution and instantaneous-gauge receipts. Ratios retain raw counts;
distributions use deterministic nearest-rank minimum/p50/p90/p95/maximum values; and
partial windows retain their later telemetry epoch. A separate content-free filing
latency receipt reconciles durable discovery, immutable publication and exact sent-alert
times to optional authoritative event lineage. Unknown first-known time, missing labels,
missing provider token counts and unavailable sensors never become a synthetic zero.
Migration 0021 is private, append-only and live. It seeded definitions only and did not
backfill observations. Prospective worker generation is limited to one complete receipt
set per hour, and authenticated Mission Control exposes only the latest closed aggregates;
the public process receives no measurement projection.

All additions preserve $0 recurring cost, private PostgreSQL and model services,
public/admin separation, human Discord privacy, append-only provenance, immutable
publication, deterministic evidence/numeric gates, exact-once delivery, and the
accepted `/radar`, `/research` and `/screened` meanings. They add no trading path,
do not loosen publication thresholds, and are an extension rather than a rewrite.

Phase 41 accounting/auditor/compliance intelligence starts with a closed, deterministic,
model-free primary-document contract. It may classify literal listing-compliance,
auditor-change, non-reliance/restatement, late-filing, going-concern, internal-control,
and material accounting-error disclosures only when exact bounded SEC evidence supports
them. New/repeated/changed status must be point-in-time and explicit; missing prior
coverage remains unavailable. A filing, late notice, auditor change, restatement, or
control weakness is not by itself evidence of fraud or investment direction. Migration
0022 and its separate private SEC-only worker implement the local append-only lifecycle:
exact events retain a model-free Tier-0 route, valid no-event filings close separately,
and unavailable history cannot become a synthetic new-disclosure claim. Production use
still requires the normal backup, restore, guarded deployment, and genuine-observation
gates.

Phase 43 convergence begins with recomputable deterministic receipts over narrowly
defined liquidity, dilution, and executed-insider predicates. Each input must retain
issuer, as-of, availability, retrieval, source-hash, source-record, and evidence-ID
lineage. Results are closed to `SUPPORTED`, `CONFLICTED`, `INSUFFICIENT`, and
`NOT_APPLICABLE`. Missing or period-incompatible facts remain insufficient; Form 144
alone is not an executed transaction; and registered shares alone do not prove issuer
dilution. The contract is not a market-direction signal and has no publication authority.
Private append-only persistence is live. Prospective production may consume only
source-specific eligible records: one unambiguous same-filing USD XBRL liquidity pair,
explicit active financing exposure with reported issuable shares, exact Section 16
transaction scopes, or Form 144 as not-applicable context. Missing, ambiguous, resale-
only and Schedule 13 inputs create no evaluable claim. Claim-policy lineage and numeric-
fact lineage remain distinct and revalidated before persistence.

## 9. Predictions, outcomes, and evaluation

Published predictions are immutable. Each should capture its creation time, horizon, thesis, benchmark, evaluation rule, evidence available at creation, and versions of calculations, data, prompts, models, rules, and scores. Corrections must be appended visibly rather than rewrite history.

Outcome tracking happens after the specified horizon and accounts for corporate actions and benchmark choice. Delisted, acquired, bankrupt, renamed, and otherwise inconvenient securities must remain in historical universes. Backtests must use point-in-time data and availability timestamps, use walk-forward or equivalent temporal separation, and keep tuning data separate from held-out evaluation.

Phase 13 implements that boundary as exact universe/prediction/outcome coverage with
chronological tuning, validation, and held-out partitions. Policy is locked before
held-out publication. Unavailable outcomes remain in coverage denominators; per-label
observed rates carry sample counts and Wilson uncertainty. The current reference
dataset is wholly synthetic and establishes no real-world performance.

Confidence may become probabilistic only after sufficient out-of-sample history demonstrates and documents calibration. Until then it remains an ordinal assessment of research support.

Phase 37 defines a separate prospective observation ledger for immutable filing
dossiers. It pre-registers real exchange-session T+1/T+5/T+20 reference and target
dates, stores split-adjusted asset and benchmark bars privately, calculates Decimal
price and benchmark-relative returns deterministically, and labels every plan
`GENUINE_FORWARD` or `RECONSTRUCTED` from enrollment time. Provider data is
`SUPPORTING`, never evidence, and missing rows append unavailable outcomes rather than
being invented. Public display/redistribution is excluded unless separate rights are
approved. The reviewed $0 provider requires an account and terms acceptance, so its
live profile remains disabled pending an account-holder decision.

Phase 44 pre-registers the first deterministic science policy over that ledger before
any supporting outcome exists. T+1/T+5/T+20, the first close at or after publication,
SPY benchmark-relative split-adjusted price return, positive-versus-non-positive result,
95% Wilson uncertainty, a 30-completed-case descriptive threshold and a fixed 194-case
power target are versioned and locked. Genuine-forward and reconstructed origins never
share calibration; cohorts with different publication, signal/rules, model/prompt,
outcome, provider, or terms versions never pool. Unavailable and adverse records remain
visible. Even a sufficiently large cohort remains `INCONCLUSIVE` unless a future,
separately approved protocol defines a justified inference; no result becomes market
alpha, a probability, or a trading instruction.

## 10. Security and administration

Initial administration supports one securely authenticated account. The design should permit later role-based access for trusted users without weakening the single-user configuration.

Security requirements include least privilege, strong password storage, protected sessions, authorization checks, audit logging, rate limits, input and output validation, safe document parsing, secret injection outside Git, dependency isolation, backup/recovery testing, and explicit trust boundaries between external content, models, storage, admin functions, and public views.

Phase 11's approved local boundary uses an Argon2id hash generated outside Git,
one single-admin identity, server-side expiring sessions, CSRF protection,
loopback/trusted-host enforcement, read-only public projections, request/body
limits, security headers, and secret-free process-local audit events. The local
workspace is inspection-only because published predictions are immutable. Phase
12 moves sessions, request/login limits, and append-only security audits into
PostgreSQL and physically separates public and admin processes. Multi-user roles
remain future work.

Production origin ports bind only to loopback, PostgreSQL publishes no host port,
and only the read-only research process joins the Cloudflare connector network.
The healthy connector does not create exposure without its separately controlled
Published Application. Discord webhook credentials are secrets. Notifications and
web research remain informational rather than executable trade instructions.

Private Mission Control may expose aggregate application funnel, failure, latency,
backlog, delivery, and deterministic detector counts. It must never select or
render human hypotheses, source content, prompts, raw model responses, credentials,
or hidden reasoning. Incomplete measurement windows are labelled partial and
unavailable sensors or metrics remain `UNAVAILABLE`; container uptime alone is not
an application-health claim.

Phase 36 requires every future private human result to retain explicit SEC identity
and hashes, XBRL/diff/forensic/Tier-0 receipts, durable content-free analyst attempt
receipts, deterministic verification, final disposition, and linked private Discord
delivery. Missing inputs remain explicit UNKNOWN/NOT_ASSESSED states. Existing
append-only v1 results are not backfilled or rewritten.

## 11. Local storage and operations

The system drive hosts the current repository. A secondary SATA disk may eventually hold raw filings, historical data, documents, models, exports, logs, and backups, but its use requires a later storage design and explicit approval. No current milestone authorizes formatting, repartitioning, remounting, erasing, or otherwise changing it.

Optimization must begin from a repeatable measurement and preserve correctness,
provenance, temporal integrity, security, auditability, and recovery. Phase 14 bounds
public list queries, adds a reversible matching index, and permits unrelated cache
misses to run concurrently while retaining same-key single-flight behavior. Optional
providers remain disabled unless their terms explicitly permit the intended storage,
derived analysis, and public display.

Phase 12 introduces a checksummed PostgreSQL volume, SHA-256-protected
custom-format dumps, count manifests, and isolated network-disabled restore
rehearsals. Same-host backups are not disaster recovery; separate encrypted
backup storage still requires an approved privacy/cost decision. Generated data,
downloaded models, local databases, logs, secrets, backups, and exports remain
outside Git.

Phase 15 adds a private CPU-only Ollama service and supervised research worker. They
publish no host ports and share only an internal analyst network; only the worker can
also reach PostgreSQL. The worker reuses the reviewed local model store, has cloud
features disabled, and reads SEC identity plus Discord configuration from one
read-only ignored local-settings mount. Public status contains bounded state and error
codes, never configuration values.

## 12. Development process

Development follows the controlled milestones in `ROADMAP.md`. A phase begins only when requested and is complete only when its tests, documentation, safety gates, and completion criteria pass. Decisions affecting cost, privacy, security, destructive operations, or public exposure require the user's explicit approval. The monitored SEC identity is operator-supplied only through ignored local configuration; the application never infers, displays, or commits it.

The user is new to autonomous-agent development. Important commands, tradeoffs, failures, and decisions should be explained in plain language without hiding technical risk.
