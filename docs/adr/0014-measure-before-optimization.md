# ADR 0014: Measure before optimization and retain provider boundaries

- **Status:** Accepted
- **Date:** 2026-08-25

## Decision

Optimize only paths with repeatable evidence. Replace the market-data cache's global
I/O lock with per-key single-flight loading, bound public publication pages, and add a
reversible PostgreSQL index matching their ordering. Preserve all normalized provider,
provenance, calculation, prediction, temporal, security, and recovery contracts.

Do not activate Massive, Twelve Data, Alpha Vantage, Stooq, or another provider until
its account, licensing, retention, derived-work, and public redistribution rights pass
the existing acceptance gate. A nominally free individual tier is not sufficient.

## Consequences

Independent provider calls and bounded publication queries are materially faster in
controlled tests. Same-key provider calls remain deduplicated. Database upgrade and
rollback are explicit and tested. Real market-data coverage remains absent because no
reviewed candidate permits this public use under the autonomous zero-cost conditions.
