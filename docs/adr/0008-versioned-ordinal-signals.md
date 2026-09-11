# ADR 0008: Versioned Ordinal Research Signals

- **Status:** Accepted for Phase 8
- **Date:** 2026-08-21 UTC

## Context

The project must combine deterministic metrics and validated qualitative
findings without obscuring risk, implying statistical calibration, or losing the
evidence path behind a conclusion.

## Decision

- Use deterministic ruleset `1.0.0` with separate opportunity, risk, and
  research-confidence integer point scales.
- Explicitly describe points as heuristic and non-probabilistic.
- Force insufficient evidence when momentum, risk metrics, validated analysis,
  cited evidence, or minimum confidence is absent.
- Map labels independently from risk profiles so high-opportunity/high-risk
  inputs are visibly aggressive and speculative.
- Attach rule IDs, versions, explanations, metric names, analyst roles,
  evidence IDs, and immutable input hashes to every contribution.
- Validate trace totals and reject recommendation language at the output
  boundary.

## Consequences

The first signal contract is reproducible, auditable, and safe to feed into
immutable prediction records. Its weights and thresholds remain initial
engineering policy, not evidence of predictive skill. Historical calibration,
universe ranking, persistence, publication, and outcome evaluation remain later
work.
