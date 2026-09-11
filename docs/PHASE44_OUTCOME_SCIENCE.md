# Phase 44 — outcome science and calibration

> **Status:** The deterministic contract, private point-in-time repository, and
> forward PostgreSQL invariant migration are deployed and validated. The authenticated,
> aggregate-only Mission Control projection is deployed and Phase 44 is accepted.
> The provider-backed supporting-outcome tables still contain zero plans, attempts,
> and outcomes, so Kalki reports no empirical calibration or predictive performance.

## Purpose

Phase 44 evaluates the private Phase 37 supporting observations without turning a
filing dossier into a forecast, market-data evidence, or a trading instruction. The
implementation is ordinary deterministic Decimal code. It does not ask a model to do
arithmetic or statistical classification.

`outcome-science-v1` was locked at `2026-09-08 00:17:00 UTC`, while the production
supporting-outcome ledger contained no rows. A later policy change must use a new
protocol version and cannot rewrite this lock.

## Pre-registered definitions

- Horizons are T+1, T+5, and T+20 complete exchange sessions after the reference
  close.
- The reference is the first exchange close at or after the immutable dossier's
  publication time.
- SPY on ARCX is the benchmark.
- Results are split-adjusted price returns and asset return minus benchmark return;
  they are not total returns.
- A benchmark-relative return greater than zero is favorable. Zero and negative
  values are adverse and remain visible.
- Unavailable outcomes stay in sample and coverage counts but cannot enter a rate
  denominator.
- `RECONSTRUCTED` history is reported separately and never enters calibration or
  power assessment. Only `GENUINE_FORWARD` observations enrolled after the protocol
  lock are eligible.

Every row is isolated by horizon, origin, dossier schema, filing-radar ruleset and
classification, model name/digest, prompt version, outcome methodology/calculation/
schema, provider, and provider-terms version. Small cohorts are never pooled across a
changed boundary to claim sufficiency.

For each eligible homogeneous cohort, Kalki reports the raw sample, completed,
unavailable, favorable, and adverse counts, the observed favorable fraction, and a
two-sided 95% Wilson interval. Fewer than 30 completed forward outcomes is
`INSUFFICIENT_SAMPLE`; 30 or more is still only `INCONCLUSIVE`. Neither status means a
calibrated probability or evidence of economic value.

The separately declared normal-approximation power design compares a 0.50 favorable
rate with a 0.60 alternative using a two-sided 0.05 type-I error rate and 0.80 target
power. Its deterministic requirement is 194 completed forward outcomes **within one
version-homogeneous cohort**. Reaching that count only says the preregistered sample
target was met; it does not establish statistical significance, market alpha,
tradability, or investment value.

## Contract hardening found by the audit

The Phase 37 evaluator already calculated returns correctly, but its reusable contract
did not independently recompute those values. Phase 44 closes that boundary:

- enrollment cannot precede immutable publication;
- every retained provider attempt must complete by evaluation time;
- each bar must match the plan's symbol, MIC, session, currency, provider, and
  knowledge time;
- completed asset, benchmark, and relative returns must exactly recompute under the
  shared 34-digit Decimal context; and
- unavailable outcomes contain no returns and require an explicit limitation.

The science contract also binds the publication ID/time, ticker, accession, source
hash, schema, classification, rules, model, and prompt lineage. It recomputes every
ratio, Wilson interval, sufficiency status, and report total from raw counts. A stable
case-set hash makes input-order-independent replay auditable.

## Current evidence and limitations

At the 2026-09-08 production observation, schema 0027 was live with 147 immutable
dossiers and zero supporting-outcome plans, provider attempts, or outcomes. The
optional Twelve Data profile remains stopped because account creation and terms
acceptance are user-controlled. No account, key, request, price, return, outcome, or
public market-data display was created for this checkpoint.

Synthetic regression cases prove temporal, arithmetic, version-stratification,
small-sample, adverse-result, unavailable-result, reconstructed-history, and contract-
tampering behavior. They are implementation tests only and provide no market evidence.
No report is public, and no ordinal research label is converted to a probability.

The private repository reads plans enrolled by an explicit UTC knowledge cutoff and
joins them to the immutable dossier plus only outcomes appended by that cutoff. It
revalidates all three closed records and rejects missing publications, duplicate plan
keys, conflicting plan/outcome content, future enrollment, and future outcomes. Every
enrolled plan is classified as a terminal outcome, not yet due, or due without an
outcome; the last category cannot silently disappear from the science population. Reads
are bounded to 100,000 plans. No public repository or route imports this boundary.

The private Mission Control adapter removes all cases and publications from the template
context. It exposes only protocol/cutoff, population coverage, origin/availability/result
counts, the closed disposition and limitations, and aggregate strata. Each stratum uses a
content-free cohort hash plus horizon, origin and classification so differing version
cohorts remain visibly separate without revealing model digests or provider records. It
contains no publication/accession/source/response/case-set identity, bar, return row, raw
provider response, prompt, or human content.

## PostgreSQL invariant boundary

Forward migration 0027 replaces the original Phase 37 insert validators without
rewriting a plan, attempt, outcome, publication, or job. PostgreSQL now independently
checks that enrollment follows immutable publication; plan JSON exactly matches all
relational session and identity fields; attempt scope and times match the retained plan;
and no attempt can be appended after a terminal outcome.

Outcome inserts must carry the exact stored plan and ordered, unique retained attempts.
Every present bar has a closed schema and must match the plan's symbol, MIC, session,
currency, provider, supporting authority, source hash, and evaluation-time knowledge
boundary. Observation hashes must exactly equal the sorted retained bar hashes.
Unavailable outcomes require a limitation and contain no return. Completed outcomes
require all four bars and no limitation, and PostgreSQL recomputes asset, benchmark and
relative returns using 34-significant-digit round-half-even Decimal semantics. JSON and
relational values must agree exactly.

The guarded runner refuses a non-empty legacy supporting-outcome ledger. This is valid
for the current production state and prevents applying stricter validation over any
future pre-existing history without a separate explicit review.

Migration 0027 applied once and its guarded rerun was an idempotent no-op. Direct
inspection found all six helper/validator functions, all three insert triggers, the
validated enrollment constraint, the unchanged least-privilege application grants, and
zero rows in all four supporting-outcome tables. A production Decimal probe matched the
application's repeating 34-digit results. Pre- and post-migration backups passed checksum,
exact-count and network-disabled isolated restore. No service was recreated because no
runtime process consumes the private science repository yet.

The reporting image was later deployed only to loopback admin. The deployed private
repository path returned the closed empty snapshot with `INSUFFICIENT_SAMPLE` and every
population/result count at zero, exactly matching direct table counts. Public research
remained available, public operations remained 404, and the public page contained no
outcome-science content. The provider and every worker remained untouched.

## Verification

The focused outcome/science, migration and web suite passes 34 tests. The fresh-schema
PostgreSQL 18 gate passes 37 tests, including an honest empty private projection and valid
persistence plus adversarial enrollment, bar identity/time, arithmetic, limitation, and
attempt-lifecycle cases. The complete repository suite passes 691 tests with 30
intentional opt-in skips; Ruff formatting and lint pass, and strict mypy passes across
249 source files.
