# ADR 0005: Offline Market-Data Baseline

- **Status:** Accepted for Phase 5
- **Date:** 2026-08-21 UTC

## Context

Free-tier APIs often require accounts/keys and do not automatically grant storage
or public redistribution rights. Canadian exchange data has explicit licensing
and pricing documents. The project needs stable contracts before choosing a live
vendor.

## Decision

- Use a synthetic CSV/JSON fixture provider as the approved zero-cost Phase 5
  implementation and keep live providers unconfigured.
- Define one swappable protocol for reference data, daily equity/benchmark bars,
  and corporate actions.
- Make currency, price adjustment, and volume adjustment mandatory and separate.
- Filter on both availability and actual retrieval at a UTC knowledge cutoff.
- Return explicit freshness, coverage, license, and issue metadata for every
  series, including empty data.
- Provide an immutable in-memory implementation and a bounded-TTL memory cache so
  provider contract and cache behavior are testable without network access.

## Consequences

Phase 6 can build deterministic calculations without depending on a vendor shape
or silently mixing incompatible inputs. The fixtures provide no real coverage and
cannot support research pages. A future live adapter requires a license, privacy,
secret, rate-limit, quality, correction, and redistribution review; provider
contracts and shared tests remain unchanged.
