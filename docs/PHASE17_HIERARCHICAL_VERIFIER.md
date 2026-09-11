# Phase 17 hierarchical verifier

> **Status:** Complete as a qualified, fail-closed implementation; Gemma remains
> disabled in production pending a future risk-focused improvement. The Phase 16
> observatory was finalized independently.

## Model artifact and license screen

The screen was completed on 2026-08-25 UTC before downloading any Gemma 4 weights.

- Upstream identity: Google DeepMind **Gemma 4 12B**, not Gemma 3. Google's official
  [Gemma 4 12B model card](https://huggingface.co/google/gemma-4-12B) identifies the
  family and lists the license as Apache License 2.0. Google's official
  [Gemma repository license](https://github.com/google-deepmind/gemma/blob/main/LICENSE)
  contains Apache License 2.0.
- Local distributor: Ollama's official
  [Gemma 4 tag registry](https://ollama.com/library/gemma4/tags).
- Exact local tag selected: `gemma4:12b-it-q4_K_M`. The convenient
  `gemma4:12b` alias resolves to the same artifact at the time of screening, but
  production configuration will use the explicit quantized tag.
- Ollama manifest digest:
  `sha256:4eb23ef187e2c5462566d6a1d3bbbc2f1346d0b4327cbb66d58fffbcc9b2b05c`.
- Quantization: `Q4_K_M`; instruction-tuned; text/image input; 256K advertised
  maximum context. Kalki will continue to use a much smaller bounded text context.
- Model layer: 7,381,382,048 bytes. Multimodal projector layer: 175,115,584 bytes.
  Ollama reports the complete artifact as 7.6 GB. The unused image capability does
  not broaden Kalki's verifier input.
- The exact Ollama license layer is
  `sha256:0d542e0c8804e39aa7f37eb00da5a762149dc682d7829451287e11b938e94594`
  and contains Apache License 2.0. It did not present separate Gemma terms, payment,
  sign-in, or account-side acceptance.

Gemma 3 was not accepted, downloaded, or run. No Gemma 3 artifact is part of this
phase. No paid or cloud inference is permitted.

## Authority and data flow

```text
SEC evidence -> deterministic extraction -> Qwen3 4B primary analyst
  -> deterministic candidate validation -> Gemma 4 12B independent verifier
  -> deterministic arbiter -> publish / one neutral Qwen retry / quarantine
```

Qwen retains its existing bounded analyst contract and pinned production digest.
Gemma receives evidence before the candidate and answers only whether the proposed
interpretation is supportable. Neither model receives hidden reasoning from the other.
Neither model can write a publication or bypass deterministic validation.

Only candidates that would otherwise qualify for publication reach Gemma. Irrelevant,
empty, injection-quarantined, schema-invalid, quote-invalid, identity-invalid, and
otherwise rejected filings do not consume verifier inference.

## Planned deterministic arbitration

1. Run every existing deterministic Qwen output and brief validator.
2. Validate Gemma output against a closed versioned schema, allowed evidence IDs,
   bounded categories, model identity/digest, and output-size limits.
3. Check purported quote, identity, and numeric concerns deterministically where the
   supplied package makes that possible. A model concern cannot overrule a provable
   deterministic result.
4. Approve only when the verifier approves and all publication invariants still hold.
5. On one legitimate semantic challenge, ask Qwen to reconsider the named category and
   evidence IDs neutrally. Do not state that the verifier is correct.
6. Re-run all deterministic validation, then one final verifier review.
7. A second material challenge, malformed/timeout-exhausted verifier response, or
   failed deterministic retry becomes a non-public terminal disposition. The worker
   continues to the next filing.

Audit records retain bounded final JSON, evidence IDs, model tags/digests, schema and
prompt versions, retry count, timestamps, challenge categories, and final disposition.
Prompts, raw traces, and hidden reasoning are not persisted or exposed.

## Resource policy before qualification

The host has about 22 GiB usable RAM and 8 GiB swap. Production initially runs one
model request at a time and must use sequential residency: finish and unload Qwen,
then load Gemma, then unload Gemma. Both models may remain warm together only if later
measurements demonstrate zero swap growth, sufficient database/OS headroom, stable
public latency, and safe temperatures. The default expectation is sequential loading.

Qualification uses a small isolated corpus, no production publications, no real
Discord notifications, no production queue mutation, and no broad model tournament.

## Qualification result and production decision

The completed isolated run is retained locally at
`data/evaluations/gemma4-12b-verifier-qualification.json` (ignored data; not a
production record). It covered eight cases: six invoked cases and two deterministic
non-invocations. All six responses were schema-valid and digest-pinned. MINE,
unsupported-profit, numeric-correction, ambiguous-identity, and prompt-injection
cases met their expected safety outcomes; XPON and HWKE correctly did not invoke
Gemma. The one-sided going-concern omission remained an approval, rather than the
expected challenge. This preserves the known primary risk-contract weakness instead
of hiding it behind the verifier.

Measured invoked latency was approximately 11--12.5 minutes per case on the
CPU-only four-core host (about 0.9 generated tokens/second). Peak package residency
was about 8.8 GiB in Ollama; the host stayed below 82°C during this run, with no
OOM and no material public-endpoint outage. Models therefore remain sequential and
the production verifier flag remains off. Gemma is installed and fully pinned for a
future, risk-focused qualification after the primary contract/forensics layer is
strengthened. Production remains the proven Qwen3 4B plus deterministic validator
path; no publication or Discord notification can bypass that path.

Because the verifier remains off, Production Recovery II restores Ollama's measured
six-logical-CPU Qwen ceiling. The two-CPU setting belonged to Gemma's qualification
envelope and caused excessive Qwen timeouts when left active for the primary-only
runtime. Any future explicit verifier enablement must first restore and revalidate
that separate two-CPU envelope; model requests remain serialized in either mode.
