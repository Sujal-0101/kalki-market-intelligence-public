# ADR 0006: Deterministic Quantitative Engine Baseline

- **Status:** Accepted for Phase 6
- **Date:** 2026-08-21 UTC

## Context

Technical and financial calculations must be reproducible, point-in-time safe,
and independent of an LLM or a data vendor's precomputed fields. Floating-point
defaults, implicit adjustments, and incomplete lineage would make historical
evaluation difficult to audit.

## Decision

- Use standard-library `Decimal` with a private 34-digit, round-half-even context.
- Version formula behavior independently from application releases.
- Require current, consistently adjusted market series and compatible financial
  periods, units, currencies, issuers, and knowledge cutoffs.
- Reject unavailable, unretrieved, stale, insufficient, zero-denominator, and
  incompatible inputs rather than return plausible-looking output.
- Return immutable schema-validated results containing parameters and every exact
  source-row input with temporal and content-hash lineage.
- Use dependency-free pure algorithms plus small synthetic reference fixtures and
  documented tolerances.

## Consequences

Later signal and evaluation phases can consume stable, auditable metrics without
asking a model to do arithmetic. The implementation is intentionally not a full
quant library: exchange calendars, FX, live data, fact-selection policy,
persistence, and total-return coverage remain explicit future work. Formula or
seeding changes require a new implementation version and reference cases.
