# Phase 45 — integrated validation and Observation Baseline V2

> **Status:** Complete. Observation Baseline V2 was frozen on 2026-09-08 UTC after
> the repeatable engineering/database gate, fresh schema-0027 restore, private
> Discord-intake hardening, and integrated genuine-production reconciliation passed.

## Purpose

Phase 45 validates the complete accepted evidence-first system as one operating baseline.
It does not add an intelligence feature, change a publication threshold, activate a data
provider, enable Gemma, add model concurrency, publish private research, or make an
investment-performance claim.

Observation Baseline V2 can be established only after the application, migrations,
restore path, security boundaries, lifecycle/idempotency behavior and genuine production
state reconcile at exact commits and runtime identities. Missing prospective evidence is
recorded as a limitation rather than manufactured.

## Repeatable engineering gate

`scripts/test-observation-baseline-v2.sh` is the single entry point for the deterministic
engineering gate. It runs:

- the complete normal pytest suite;
- Ruff formatting and lint, strict mypy, dependency consistency and shell syntax;
- production, disabled supporting-outcome and Cloudflare Compose validation; and
- all 15 dedicated PostgreSQL gates for analyst receipts, optional verifier history,
  funnel telemetry, autonomous screening, SEC links, novelty, Focus history,
  engineering measurements, ownership, financing, accounting, interrupted-attempt
  recovery, filing-change history, contradiction receipts and prospective outcomes.

The accepted final run passed 696 normal tests with 30 intentional opt-in PostgreSQL
skips, all static checks across 250 source files, and all dedicated database gates.

That run found two classes of internal harness defect. Four older disposable gates used
`pg_isready`, which can report that the server accepts sockets before the requested
`POSTGRES_DB` exists. They now probe the actual database with `SELECT 1`. The Phase 42 and
Phase 43 upgrade fixtures used an open-ended migration glob, so the later 0026/0027 files
contaminated the required schema-0024/schema-0025 starting points. Their migration ranges
are now closed at the exact predecessor. Regression tests bind both behaviors.

## Initial production evidence

Production schema and the repository migration directory contain the same exact 27-version
history through `0027_outcome_science_invariants`. Fresh backup
`kalki-20260908T114657Z.dump` passed checksum, archive structure, exact row counts,
transient-state validation and network-disabled isolated restore. It is sensitive, ignored
local data and was not uploaded or deleted.

The backup manifest records 147 immutable research briefs and 147 notification deliveries,
2,689 research candidates, 2,007 terminal screening decisions, 5,088 completed analyst
attempt receipts, six event disclosures/lineage decisions, 93 validated SEC-link receipts,
139 filing-change snapshots, 123 selections and 74 contradiction receipts. All four
supporting-outcome tables and the prediction/outcome tables remain empty. Focus membership
history is also empty. These are operating counts, not investment results.

All healthchecked services were healthy with zero restarts/OOM. Public research routes were
200 locally and externally; public admin, health, docs, OpenAPI and operations were 404.
PostgreSQL and Ollama have no published port. Qwen remains digest-pinned and serialized with
`OLLAMA_NUM_PARALLEL=1`; the optional verifier is disabled and no model was loaded at the
inventory instant.

The security inventory found that the long-running private Discord intake was explicitly
configured as root, retained default Linux capabilities and had no healthcheck. Its secret
files are owned by the local deployment UID 1000, so the closed correction runs the intake
as `1000:1000`, drops all capabilities and adds the same PID-1 liveness check used by the
private workers. A networkless/read-only/capability-dropped smoke proved that UID 1000 can
read the mounted bot-token file without exposing it. No port, network or public route was
added.

The corrected intake is deployed from commit `c6312f2` in exact image
`sha256:e5c7e24e9aa630e91478cebae1a21794deb0e29b7b16c49d47bc49af417990a1`
(107,641,719 bytes). Only Discord intake was recreated. It connected to the approved
private gateway, is healthy with zero restarts/OOM, runs as `1000:1000` read-only with all
capabilities dropped and no port, and uses only database/research-egress networks. Twelve
completed human leads still reconcile to 12 immutable results and 12 delivered private
results, with zero duplicate source messages or result-delivery heads. No work was active
at recreation.

## Frozen runtime identity

The Phase 45 implementation checkpoint is commit `c6312f2`; its private-intake deployment
result is recorded by commit `a07b64b`, and the baseline freeze is checkpointed by `358d8fd`.
The integrated observation window began with backup `kalki-20260908T114657Z.dump` and closed
at 2026-09-08 12:44:57 UTC. Production schema is
the exact 27-migration history through `0027_outcome_science_invariants`.

The live component identities at the close were:

| Component | Exact image identity |
| --- | --- |
| Admin | `sha256:3c77f64e3932fd57dc228672ad7d8cec1aa69b158c69cf3aed0596d35db7b381` |
| Public web | `sha256:3c2a538007b9870b474603e8d9348fd9cadea1a0f7c03e46e7624acd7caab816` |
| Research, ownership and financing workers | `sha256:41c1c542e0efda53363c86ad55d01a40d2765936fe81955a6cfb48a03ab5692d` |
| Accounting worker | `sha256:e0cc7b68fad9b8915d6d91f1f3d5315fc48f366dafdf4122187652ccf982caaa` |
| Discord intake | `sha256:e5c7e24e9aa630e91478cebae1a21794deb0e29b7b16c49d47bc49af417990a1` |
| PostgreSQL 18 | `sha256:48c8ad3a7284b82be4482a52076d47d879fd6fb084a1cbfccbd551f9331b0e40` |
| Ollama host | `sha256:fc74d22ffd0d5ac395a4b7bdda75a4539758862c49ebf3005647084631e63789` |
| Cloudflare tunnel | `sha256:4f6655284ab3d252b7f28fedb19fe6c8fc82ee5b1295c20ac74d475e5398a52d` |

Every healthchecked service was healthy with zero restarts and no OOM. Admin and public web
remain loopback-bound; PostgreSQL and Ollama publish no host port. Application services are
non-root/read-only/capability-dropped. The official PostgreSQL container retains its required
writable database boundary. The public `/`, `/radar`, `/research` and `/screened` routes were
200, while public admin, health, docs, OpenAPI and operations routes were 404. The authenticated
Mission Control repository returned all nine closed aggregate projections; representative
query times were 3.79--52.14 ms.

Qwen remains `qwen3:4b` at digest
`359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`,
prompt `analyst-v2`, output/validation schema `1.0.0`, context 4096 and maximum output 768.
All 5,088 retained analyst receipts use that same lineage. The eight deterministic detector
channels use receipt schema `1.0.0`; screening uses schema `1.0.0`, event lineage uses
`event-novelty-v1`, and contradiction evaluation uses `deterministic-contradiction-v2`.
The verifier remains disabled. `OLLAMA_NUM_PARALLEL=1`; Gemma is disabled and was not loaded.
The supporting-outcome protocol remains `outcome-science-v1`, and its optional provider
profile is stopped with no accepted account terms, key or request.

## Integrated production reconciliation

At the close, the research ledger contained 2,689 terminal candidates: 147 published, 1,878
skipped and 664 failed. Its 3,232 runs comprised 1,761 completed, 1,422 degraded and 49
failed runs. The last five genuine scheduled cycles all completed, including cycles at
12:05, 12:20 and 12:35 UTC after the Phase 45 checkpoint. Screening contained 140 qualified,
1,671 screened-out and 196 analysis-incomplete decisions. All 5,088 analyst attempts were
complete, and no research or supporting worker held a processing claim at the snapshot.

The immutable publication boundary reconciled 147 briefs to 147 sent delivery heads, with no
duplicate candidate accession, brief accession or notification key. Twelve completed human
leads reconciled to 12 private results and 12 delivered result heads with no duplicate source
message ID or delivery head. Five results use complete `human-research-v2` provenance; the
seven earlier records remain visibly legacy with unknown lineage and were not rewritten.

Wave-B/private deterministic state included 1,509 ownership jobs (1,007 completed, 254
failed, 243 pending, five retry-wait), 1,625 financing jobs (six completed, 1,202 no-terms,
168 failed, 242 pending, seven retry-wait), and 1,047 accounting jobs (95 completed, 905
no-events, 47 failed). Receipt-to-routing reconciliation was exact. There were 93 validated
SEC-link receipts, 139 filing-change snapshots, 123 filing-change selections, six event
lineages, and 77 contradiction receipts (`INSIDER`: 25 supported and 52 conflicted). All six
event-lineage cases remain honestly `UNKNOWN_NOVELTY`; Focus membership history is empty.

The private science projection and direct database counts both returned zero plans, jobs,
attempts and outcomes. Predictions and prediction outcomes are also empty. This is a verified
absence of a sample, not a positive or negative investment result. The report therefore stays
`INSUFFICIENT_SAMPLE`, has no cohort strata and makes no calibration, probability, alpha or
trading claim.

The resource snapshot showed bounded use: intake 117.7 MiB/256 MiB; admin 104.5 MiB/384 MiB;
public 67.8 MiB/384 MiB; research worker 102.1 MiB/512 MiB; ownership 64.4 MiB/256 MiB;
financing 92.5 MiB/256 MiB; accounting 80.4 MiB/256 MiB; PostgreSQL 130.9 MiB/768 MiB;
idle Ollama 69.3 MiB/14 GiB; and Cloudflare 34.8 MiB/256 MiB. The host retained about 156 GiB
of disk free.

## Known limitations and freeze policy

- Ownership and financing retain bounded pending/retry backlogs. They were progressing under
  their accepted retry policies, but the baseline does not describe them as caught up.
- Historical run failures/degradation, all-unknown novelty, empty Focus history, disabled
  verifier, and the lack of a recent eligible Qwen claim remain visible rather than inferred
  away.
- The optional zero-cost market-data provider still requires user-controlled account creation
  and terms acceptance. Until that external decision and genuine forward observations exist,
  no outcome calibration can be performed.
- The local Gemma artifact is not enabled, loaded or concurrent with Qwen. No paid service,
  external account, brokerage connection or automatic-trading path was added.

Observation Baseline V2 is established with these limitations. Major feature work is frozen;
future changes must begin from this documented state and demonstrate measured benefit without
weakening evidence, point-in-time, idempotency, security or public/private boundaries.
