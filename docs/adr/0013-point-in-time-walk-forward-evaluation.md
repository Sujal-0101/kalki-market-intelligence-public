# ADR 0013: Point-in-time walk-forward self-evaluation

- **Status:** Accepted
- **Date:** 2026-08-25

## Decision

Use immutable, closed dataset sections for historical universe membership,
predictions, and outcomes. Require exact case coverage, chronological tuning,
validation, and held-out partitions, and a policy lock before held-out publication.
Retain unavailable, delisted, and bankrupt cases. Apply a declared deterministic cost
sensitivity and report per-label observed rates with Wilson uncertainty.

## Consequences

The evaluator fails closed on future membership knowledge, pre-horizon endpoints,
missing universe rows, split overlap, or late policy changes. Reports are reproducible.
The current fixture is synthetic, so it validates implementation but provides no
evidence of real market performance. A real dataset requires a separately approved
source whose license and availability history support this model.
