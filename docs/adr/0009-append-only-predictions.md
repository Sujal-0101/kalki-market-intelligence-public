# ADR 0009: Append-Only Predictions and Outcomes

- **Status:** Accepted
- **Date:** 2026-08-21 UTC

## Context

Honest evaluation requires preserving a forecast exactly as published, retaining
failed or delisted securities, and separating later outcome knowledge from the
original research cutoff.

## Decision

- Store the complete validated signal, evidence keys/times, input hashes,
  versions, declared horizon, benchmark, and evaluation rule in each immutable
  prediction snapshot.
- Append corrections and outcomes as separate records; expose no mutation path.
- Enforce application immutability and add PostgreSQL update/delete/truncate
  rejection triggers.
- Reject post-cutoff start observations, pre-horizon outcomes, changed benchmark
  rules, unrelated instruments/currencies, and late evaluation inputs.
- Retain delisted, acquired, bankrupt, renamed, and unavailable outcomes in
  reports.

## Consequences

The model supports auditable point-in-time outcome tracking without rewriting
history. Calendar-day horizons and initial return rules are deliberately simple.
The PostgreSQL migration and mutation test passed in the isolated integration
container before this decision was accepted.
