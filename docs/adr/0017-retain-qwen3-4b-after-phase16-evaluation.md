# ADR 0017: Retain Qwen3 4B after the permitted Phase 16 comparison

- Status: accepted
- Date: 2026-08-25

## Context

Phase 16 compared the deployed `qwen3:4b` model with
`qwen3:4b-instruct-2507-q4_K_M` on a production-shaped SEC corpus. Grounding,
schema reliability, issuer identity, numeric fidelity, catalyst/risk extraction,
uncertainty, repeatability, latency, and host impact were measured by deterministic
code. The requested Gemma 3 candidate could not be downloaded without accepting a
separate legal agreement. The account holder did not accept those terms and later
removed Gemma 3 from the Phase 16 comparison requirement.

## Decision

Retain `qwen3:4b` digest
`359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`.
Do not promote the Instruct candidate. Although it eliminated unsupported-claim
validator failures, it refused both repeats of the only genuine SEC catalyst case,
while the current model surfaced that filing and produced the successful live brief.
Neither Qwen candidate passed the complete workload gate.

Do not pull Gemma 3 or accept its terms. Do not attempt Qwen3 8B inside the 6 GiB
production limit; its 5.2 GB weights plus the
measured 4B runtime overhead make swapping or an OOM restart likely.

## Consequences

Production retains a tested rollback baseline and no model-driven publication behavior
changes in the design deployment. The current model's unsupported synthetic contract
attempt remains fail-closed under deterministic validation. Both tested models missed
the one-sided going-concern case, so later analyst-contract work must preserve and
address that finding rather than hide it behind a second model. A separately scoped
hierarchical-verifier phase may add an independent verifier without changing this
Phase 16 selection. The full measurements and legal screen are in
`docs/PHASE16_MODEL_EVALUATION.md`.
