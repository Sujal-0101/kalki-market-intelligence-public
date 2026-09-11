# Roadmap

Each phase begins only after approval and ends only when its completion criteria are met. Plans may be refined as evidence is gathered; later phases must not be presented as implemented early.

## Phase 0 — Environment inspection and documentation

- **Objectives:** verify the local environment and establish the project scope, architecture, safety rules, and roadmap.
- **Deliverables:** `README.md`, `ARCHITECTURE.md`, `ROADMAP.md`, `AGENTS.md`, `docs/PROJECT_SPEC.md`, `docs/ENVIRONMENT.md`, and `.gitignore`.
- **Safety gates:** read-only host inspection; no installs, containers, external access, disk changes, service changes, secrets, or public exposure.
- **Completion criteria:** observations are documented, requested files are consistent, Git scope is reviewed, and no Phase 1 implementation has begun.

## Phase 1 — Repository foundations, schemas, tests, and local development structure

- **Objectives:** choose a minimal stack and establish maintainable project conventions.
- **Deliverables:** source/test layout, isolated dependency definitions, lint/test commands, configuration schema, initial domain and evidence schemas, migrations strategy, and local developer workflow.
- **Safety gates:** no production deployment, live secrets, paid services, or system-Python modification; dependencies are pinned and isolated.
- **Completion criteria:** a clean checkout can run documented checks locally, schema invariants have tests, and architecture decisions are recorded.

## Phase 2 — Ollama installation and representative model benchmark

- **Objectives:** install Ollama only with approval and assess realistic CPU/RAM/GPU behavior using representative structured-analysis tasks.
- **Deliverables:** installation notes, model-selection criteria, repeatable benchmark set, quality/resource results, and a recommended configuration.
- **Safety gates:** no unapproved model downloads or driver/CUDA changes; model licenses and storage impact are reviewed; no confidential inputs.
- **Completion criteria:** at least one model meets defined schema, quality, latency, and stability thresholds—or the limitations and fallback are documented.

## Phase 3 — SEC/US ingestion

- **Objectives:** ingest authoritative US issuer, filing, and company-fact data through compliant interfaces.
- **Deliverables:** SEC provider adapter, rate limiting and identification policy, raw metadata retention, normalized records, fixtures, and ingestion tests.
- **Safety gates:** comply with SEC guidance; no scraping around controls; timestamps and source hashes are preserved.
- **Completion criteria:** a representative issuer set ingests idempotently, failures recover safely, and facts trace to original SEC evidence.

## Phase 4 — Canadian/SEDAR+ ingestion architecture

- **Objectives:** design and validate a lawful, maintainable path for Canadian disclosure data.
- **Deliverables:** source-access assessment, SEDAR+ provider contract, identifier mapping design, representative fixtures where permitted, and documented gaps/fallbacks.
- **Safety gates:** do not bypass authentication, CAPTCHAs, robots restrictions, terms, or access controls; stop if compliant automation is unavailable.
- **Completion criteria:** an approved ingestion design exists with tested normalization boundaries and honest coverage limitations.

## Phase 5 — Market-data provider abstraction

- **Objectives:** define replaceable interfaces for price, volume, corporate-action, benchmark, and reference data.
- **Deliverables:** provider protocol, canonical schemas, quality/freshness metadata, caching and rate-limit behavior, fixtures, and at least one approved zero-cost implementation or offline test provider.
- **Safety gates:** confirm licenses and permitted use; never silently mix adjusted/unadjusted data or incompatible currencies.
- **Completion criteria:** providers can be swapped in contract tests and data gaps/staleness remain explicit.

## Phase 6 — Deterministic quantitative engine

- **Objectives:** implement reproducible technical, fundamental, valuation, and risk calculations.
- **Deliverables:** versioned calculations for agreed indicators and ratios, currency/unit handling, benchmark logic, fixtures, and reference-value tests.
- **Safety gates:** no LLM arithmetic; guard against missing values, split errors, stale inputs, and future data.
- **Completion criteria:** calculations match trusted reference cases within documented tolerances and record full input lineage.

## Phase 7 — Structured AI analyst pipeline

- **Objectives:** implement evidence-bound qualitative analysis using configurable local models and specialized analyst roles.
- **Deliverables:** provider interface, versioned prompts, output schemas, validation/retry policy, injection defenses, contradiction handling, and evaluation cases.
- **Safety gates:** untrusted model output cannot become fact automatically; unsupported claims fail validation; no fabricated citations or figures.
- **Completion criteria:** representative documents produce schema-valid, evidence-linked results at an agreed quality threshold with failure modes tested.

## Phase 8 — Signal engine

- **Objectives:** combine deterministic metrics and validated qualitative analysis into explainable research signals.
- **Deliverables:** versioned rules, separate opportunity/risk/research-confidence scores, label mapping, missing-evidence policy, and explanation traces.
- **Safety gates:** no return promises, trade execution, or premature probability claims; speculative and conservative profiles remain clearly distinct.
- **Completion criteria:** fixed fixtures yield reproducible signals and every material conclusion traces to available evidence.

## Phase 9 — Prediction and outcome tracking

- **Objectives:** preserve forecasts as made and evaluate them after their declared horizons.
- **Deliverables:** append-only prediction records, outcome jobs, benchmark and corporate-action handling, audit fields, and evaluation reports.
- **Safety gates:** predictions cannot be edited after publication; evaluation uses only information available at prediction time; delisted securities remain included.
- **Completion criteria:** mutation attempts fail, outcomes append correctly, and temporal-integrity tests demonstrate no look-ahead leakage.

## Phase 10 — Optional Discord integration

- **Objectives:** optionally notify an approved private Discord destination about published research.
- **Deliverables:** outbound adapter, templates, deduplication, rate limiting, secret configuration, and disable switch.
- **Safety gates:** proceed only if the user creates/approves Discord resources; never commit webhooks; messages remain research, not trade instructions.
- **Completion criteria:** opt-in test notifications are secure, rate-limited, auditable, and removable without affecting the core system.

## Phase 11 — Web dashboard and secure admin research interface

- **Objectives:** provide responsive public research views and a protected editorial/research workspace.
- **Deliverables:** typed API, frontend, accessibility/responsiveness checks, single-admin authentication, authorization boundaries, audit logging, and security tests.
- **Safety gates:** bind locally during development; use secure password/session practices; prevent public access to admin or operational data.
- **Completion criteria:** core user flows and access-control tests pass, disclosures are visible, and no service is publicly exposed.

## Phase 12 — Approved Cloudflare deployment

- **Objectives:** expose the reviewed application through an explicitly approved Cloudflare setup.
- **Deliverables:** deployment/runbook, tunnel configuration, domain/TLS setup, rate limits, monitoring, backup/recovery procedure, and rollback plan.
- **Safety gates:** explicit approval for exposure and any cost; secrets remain external to Git; threat model and recovery test complete first.
- **Completion criteria:** the smallest approved surface is reachable securely, admin protections are verified externally, and rollback is tested.

## Phase 13 — Backtesting and self-evaluation

- **Objectives:** measure historical behavior honestly and identify systematic errors.
- **Deliverables:** point-in-time datasets, universe membership history, walk-forward evaluation, cost/benchmark assumptions, calibration reports, and error taxonomy.
- **Safety gates:** prevent look-ahead and survivorship bias; separate tuning from held-out evaluation; label incomplete historical coverage.
- **Completion criteria:** reproducible reports pass temporal-leakage tests and disclose limitations, sample size, and uncertainty.

## Phase 14 — Optimization and optional additional providers

- **Objectives:** improve reliability, cost, speed, and coverage based on measured bottlenecks.
- **Deliverables:** performance profile, prioritized optimizations, provider evaluations, migration/rollback plans, and updated operating limits.
- **Safety gates:** no new provider, paid resource, or material privacy tradeoff without approval; preserve normalized contracts and provenance.
- **Completion criteria:** changes demonstrate measured benefit without weakening correctness, auditability, security, or zero-cost operation unless a new budget is approved.

## Phase 15 — Continuous filing radar and distinctive public experience

- **Objectives:** close the missing always-on orchestration gap and replace the generic empty dashboard with a useful evidence-led research desk.
- **Deliverables:** supervised SEC discovery worker, private local Ollama runtime, durable candidate/run/status/delivery state, immutable filing briefs, automatic Discord handoff, live status API, searchable/filterable radar pages, and a complete responsive visual redesign.
- **Safety gates:** no fabricated or unlicensed price data; no guessed SEC contact identity; no paid resource, new account, brokerage connection, remote admin surface, or additional public hostname; model output remains schema- and evidence-validated.
- **Completion criteria:** normal and integration checks pass, append-only enforcement and recovery are rehearsed, all services are supervised and private at the reviewed boundaries, the HTTPS radar is reachable, and any remaining operator configuration is visible rather than silently disabling work.

## Phase 16 — Evidence observatory and workload-specific model selection

- **Objectives:** turn the technically complete filing radar into a memorable editorial intelligence product and select the local model using Kalki's real evidence workload rather than generic benchmark reputation.
- **Deliverables:** original brand system and social preview, warm editorial observatory, truthfully encoded live radar, signal register, evidence dossiers, visual method story, responsive/reduced-motion/accessibility verification, and a reproducible SEC-analysis model comparison with resource measurements and rollback.
- **Safety gates:** every security blip and activity row maps to a real publication; decorative variables are labelled; synthetic benchmark cases never enter production; no paid/cloud inference, separate legal acceptance, brokerage path, private route, secret, tracker, public service, or weakened validator is introduced.
- **Completion criteria:** genuine SEC-to-Discord activity remains proven, the public hostname is visually inspected across target sizes, evidence and semantic status remain accurate, the retained compatible model passes the full constrained production gate, production resource use remains safe, and all application/security/recovery checks pass before merge. Gemma 3 is not a completion requirement: its separate terms were not accepted and the account holder superseded that comparison with a later, separately scoped verifier architecture.

## Phase 17 — Hierarchical independent verification

- **Objectives:** retain Qwen3 4B as the primary filing analyst while adding a selective local Gemma 4 12B semantic review stage under deterministic publication authority.
- **Deliverables:** bounded evidence-first verifier packages, a strict versioned verdict schema, deterministic challenge classification and publication arbitration, one neutral analyst reconsideration, append-only review/disposition lineage, fail-closed recovery, selective operational counters, focused verifier qualification, measured sequential-residency policy, and accurate public model lineage.
- **Safety gates:** no Gemma 3, paid/cloud inference, broad model tournament, hidden reasoning retention, model-to-publication bypass, irrelevant-filing verification, concurrent heavyweight inference without evidence of safety, duplicate Discord delivery, private-model exposure, or weakening of the existing source/quote/schema/provenance validators.
- **Completion criteria:** the official Apache-2.0 Gemma 4 12B artifact is digest-pinned and narrowly qualified, deterministic validation remains authoritative before and after semantic review, one challenge retry and persistent-disagreement quarantine work end to end, publications and Discord occur only after final approval, normal software/security/PostgreSQL/recovery gates pass, production remains responsive without OOM or sustained swap growth, and rollback is tested.

## Phase 18 — Deterministic forensics and evidence layer

- **Objectives:** strengthen primary-source evidence quality, deterministic numerical verification, filing comparison, and forensic qualification before any future model escalation.
- **Deliverables:** source-authority metadata, an evaluated EdgarTools adapter boundary with equivalence fixtures, numerical claim statuses, provenance-preserving filing diffs, deterministic forensic detectors with explicit unknown states, tier-0 escalation reasons, and a scoped outcome-science design.
- **Safety gates:** no paid/cloud dependency, no replacement of Kalki acquisition/provenance ownership, no fabricated market data, no LLM arithmetic authority, no lower-authority evidence silently outweighing primary evidence, and no public/private boundary expansion.
- **Completion criteria:** each slice has focused regression coverage, immutable lineage survives adapter use, deterministic conflicts fail closed, resource limits remain safe on the Dell host, and the full repository/security/recovery gates pass before merge.
