# ADR 0007: Untrusted Local Analyst Boundary

- **Status:** Accepted for Phase 7
- **Date:** 2026-08-21 UTC

## Context

The project needs qualitative document interpretation without allowing a local
model to invent facts, obey source-borne instructions, perform calculations, or
gain operational authority. Schema-constrained JSON alone does not establish
grounding or safety.

## Decision

- Put local models behind a replaceable no-tools provider protocol; the Ollama
  adapter is loopback-only and bounded.
- Version prompts and use narrow analyst roles with closed output contracts.
- JSON-encode and delimit evidence as untrusted data; quarantine high-confidence
  injection patterns before inference.
- Validate exact evidence IDs/quotes, reported facts, figures, URLs, role
  categories, lexical inference grounding, temporal cutoffs, and contradictions
  with ordinary code.
- Deterministically normalize only structurally or textually provable labels and
  record those changes in an immutable audit wrapper.
- Permit at most one repair attempt; reject output after the second failure.

## Consequences

Only `ValidatedAnalysis` can be consumed later, and even it remains qualitative
research input rather than authoritative fact. The small synthetic evaluation
passes the Phase 7 gate, but its scope does not justify autonomous publication,
probability language, or removal of human review. Prompt injection and semantic
grounding remain open security problems requiring layered controls and ongoing
evaluation.
