# ADR 0002: Local Model Baseline

- **Status:** Accepted for Phase 2
- **Date:** 2026-08-21 UTC

## Context

The platform needs a zero-cost local qualitative-analysis baseline that fits the
existing laptop. The installed GeForce 940MX is supported by the current Ollama
runtime but has only 4 GB memory and is not assumed to improve performance.

## Decision

- Use user-local Ollama 0.32.15 without a system service, CUDA installation, or
  driver change.
- Bind the development API to `127.0.0.1:11434` and disable Ollama cloud features.
- Use the Apache-2.0-licensed `qwen3:4b` Q4_K_M artifact identified in
  `docs/MODEL_BENCHMARK.md` as the initial representative model.
- Default to CPU-only inference, one concurrent request, deterministic structured
  output settings, and asynchronous qualitative work.
- Keep models and raw benchmark output outside version control.

## Consequences

The baseline runs locally within current RAM, passes the small Phase 2 schema,
quality, latency, and stability gates, and requires no paid API. CPU execution is
about 3.7 times faster than full 940MX offload for the tested workload. Latency is
still high enough that local AI must not sit in a synchronous user-request path.
The benchmark is deliberately narrow; Phase 7 must validate evidence linking,
injection defenses, larger documents, and realistic failure modes before the
model participates in application analysis.
