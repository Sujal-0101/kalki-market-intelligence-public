# ADR 0018: Deterministic arbitration with a selective independent verifier

- Status: accepted with production feature flag disabled pending risk-focused follow-up
- Date: 2026-08-25

## Context

The digest-pinned Qwen3 4B analyst has completed a genuine SEC-to-publication cycle,
but one-sided risk evaluation remains an identified weakness. Deterministic checks can
prove identity, exact quotations, evidence membership, many numeric claims, schemas,
provenance, and uniqueness. They cannot reliably decide whether a supported statement
is materially misleading in context or omits an obvious counterpoint.

## Decision

Retain Qwen3 4B as primary analyst. Add official local Gemma 4 12B as a selective,
evidence-first semantic verifier only for deterministically valid candidates that
would otherwise be published. Deterministic application code remains the final
authority. One neutral Qwen reconsideration is allowed after a legitimate verifier
challenge; persistent disagreement fails closed. Models run sequentially unless
measurements later prove joint residency safe.

## Consequences

Publication latency increases only for the small subset of qualifying candidates.
Model unavailability now fails closed for that subset, so queue state and bounded
recovery must be durable. Append-only verifier lineage is required for auditability.
Gemma cannot replace deterministic checks, directly publish, notify Discord, review
irrelevant filings, or expose reasoning. The focused qualification completed with
valid structured output and five of six invoked expected outcomes, but Gemma missed
the known one-sided going-concern omission. The feature therefore remains disabled
in production; production retains the existing Qwen-plus-deterministic architecture
until a risk-contract/forensics phase produces a justified, narrowly requalified
verifier. The artifact remains locally installed and digest-pinned; no public
publication or Discord message was made by the qualification.
