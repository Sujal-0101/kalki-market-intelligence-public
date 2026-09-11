# Phase 16 local-model evaluation

> **Status:** Complete on 2026-08-25 UTC. The two legally permitted Qwen candidates
> completed and the current model remains in production. The account holder did not
> accept Gemma 3's separate terms, so Gemma 3 was not downloaded or run. On
> 2026-08-25 the account holder superseded that planned comparison and removed it
> from the Phase 16 completion requirements.

## Host and production envelope

- CPU: Intel Core i7-8550U, 4 physical cores / 8 threads, 1.8 GHz base and
  4.0 GHz reported maximum.
- Memory: 22 GiB RAM and 8 GiB swap; swap use was zero before evaluation.
- Storage: 228 GiB NVMe filesystem, 185 GiB available before candidate download.
- Acceleration: Intel UHD 620 plus NVIDIA GeForce 940MX with 4 GiB VRAM. The
  Phase 2 gate found CPU inference faster, so production keeps CUDA and Vulkan
  disabled.
- Ollama: 0.32.15, CPU-only, one request at a time, 4,096-token context, no cloud
  feature, no published port, and a 6 GiB memory limit. Phase 16 raises the CPU
  ceiling from 3.5 to 6 of 8 logical CPUs after the strict production gate below.
- Baseline model: `qwen3:4b`, digest
  `359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`,
  Q4_K_M, 2,497,293,931 bytes.
- Instruct candidate: `qwen3:4b-instruct-2507-q4_K_M`, digest
  `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`,
  Q4_K_M, 2,497,293,803 bytes.

Before the maintenance window, the concurrent services used about 9.5 GiB host
RAM in total, with about 13 GiB available and no swap in use. The warmed baseline
model used 4.39 GiB during a genuine two-role production analysis. The public and
admin services used about 60 MiB each, PostgreSQL about 36 MiB, the worker about
60–75 MiB, and cloudflared about 16 MiB.

## Corpus and metrics

`kalki-sec-analysis-v1` contains six bounded cases and runs each candidate twice at
temperature zero, seed 42, 4,096 context tokens, 768 maximum output tokens, thinking
disabled, and one concurrent request:

1. the genuine public Mayfair Gold 6-K excerpt retrieved in the activation gate;
2. a prominently labelled synthetic 8-K-style binding contract;
3. a labelled synthetic 10-Q-style going-concern and refinancing risk;
4. a labelled synthetic issuer/ticker identity collision;
5. a labelled synthetic missing-transaction case that should calibrate uncertainty;
6. two labelled synthetic correction excerpts that test numeric fidelity and temporal
   authority.

Synthetic cases are tests, not market evidence. The real excerpt retains its SEC URL,
retrieval cutoff, and deterministic content hash. Every response uses the production
prompt, production schema, and production validator, but the comparison records the
first attempt instead of hiding a weak response behind the allowed repair attempt.

Ordinary code measures schema validity, post-validation acceptance, exact quotation
fidelity, unsupported-claim detection, numeric fidelity, company/ticker identity,
catalyst extraction, risk extraction, uncertainty calibration, instruction following,
repeatability, latency, generation speed, timeout/failure rate, and resource use. A
model cannot win on eloquence or speed if evidence fidelity is worse.

Run one candidate inside the existing private analyst network with:

```bash
docker run --network kalki-production_analyst --read-only \
  kalki-market-intelligence:phase16-local \
  python -m kalki_market_intelligence.benchmarking.sec_models \
  --model MODEL_TAG --base-url http://ollama:11434 --repeats 2 \
  --output /out/MODEL_REPORT.json
```

Generated reports stay under ignored `data/evaluations/`; model weights stay in the
ignored user-local Ollama store.

Ollama must be restarted between candidate runs. Its normal ten-minute keep-alive is
useful in production, but otherwise the previous and next 4B artifacts can overlap in
memory and make the resource result invalid. The first Instruct attempt detected this
condition, was stopped immediately, and was excluded; the clean run began only after
`ollama ps` showed no resident model and host swap had returned to zero.

A second pre-result review found that the first corpus helper had assigned the real
case's retrieval time to all three evidence timestamps. Those preliminary reports
were also excluded. The final corpus preserves the 24 August filing date separately
from the 25 August 04:14 UTC availability/retrieval time and has a regression test for
that ordering.

The first clean Instruct inference pass then completed but could not replace its
root-owned report path. Its in-memory result was discarded rather than reconstructed.
The harness now checks report writability before inference, with a regression test,
and the candidate was rerun from an unloaded state. Only that persisted rerun appears
below.

## Compatibility and legal screens

- Qwen3 4B baseline and Qwen3 4B Instruct 2507 are Apache-2.0 open-weight models and
  fit the existing production limit. The artifact tag is recorded on the official
  [Ollama Qwen3 tags page](https://ollama.com/library/qwen3/tags), and the upstream
  [Qwen3 repository](https://github.com/QwenLM/Qwen3) identifies its open weights as
  Apache-2.0.
- `qwen3:8b-q4_K_M` is 5.2 GB before the context, runtime, and prompt-cache overhead.
  The observed 4B production overhead makes the 8B artifact exceed the existing 6 GiB
  Ollama limit. It is therefore screened out rather than risk an OOM restart or swap.
- `gemma3:4b-it-q4_K_M` is technically compatible at 3.3 GB according to the official
  [Ollama Gemma tags](https://ollama.com/library/gemma3/tags), but Gemma 3 is governed
  by separate [Google Gemma terms](https://ai.google.dev/gemma/terms) that state use
  constitutes acceptance. Repository policy requires the account holder to approve
  legal acceptance, so it has not been pulled or executed.

## Results

| Metric | `qwen3:4b` | `qwen3:4b-instruct-2507-q4_K_M` |
|---|---:|---:|
| Closed-schema validity | 100% | 100% |
| First-attempt deterministic validation | 83.3% | 100% |
| Exact quotation fidelity | 100% | 100% |
| Runs with unsupported claims | 16.7% | 0% |
| Numeric fidelity | 75% | 50% |
| Issuer/ticker identity correctness | 50% | 50% |
| Catalyst case quality | 50% | 50% |
| Risk case quality | 0% | 0% |
| Uncertainty calibration | 100% | 100% |
| Instruction following | 100% | 100% |
| Deterministic case repeatability | 66.7% | 66.7% |
| Median wall time | 99.05 s | 105.01 s |
| Median generated tokens/s | 3.51 | 3.48 |
| Timeout/failure rate | 0% | 0% |
| Peak Ollama cgroup memory | 5.31 GiB | 5.02 GiB |
| Host swap growth | 0 | 0 |
| Workload gate | **fail** | **fail** |

The baseline's Ollama cgroup exposed an 8 MiB swap counter throughout its run, but
the counter did not grow and host swap remained zero. The Instruct run's cgroup and
host counters both remained zero. Ollama consumed roughly 350% CPU during active
generation while the public/admin applications, PostgreSQL, and tunnel remained
healthy.

The aggregate grounding improvement does not make the Instruct candidate a safe
production winner. It accepted the synthetic binding-contract and identity cases,
but returned `insufficient_evidence` for both repeats of the genuine Mayfair Gold
filing. The current model surfaced that real catalyst in both repeats and produced the
genuine live publication. Its synthetic contract response was rejected by the exact
reported-fact validator, which is a safe failure. Both candidates refused the clear
synthetic going-concern case; this exposes ambiguity in the current balanced
bull/bear-risk role instruction and is a prompt-evaluation finding, not evidence that
the source lacks risk.

## Production decision and rollback

Keep `qwen3:4b` with digest
`359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`.
For an evidence-discovery system, missing the only genuine positive case is more
damaging than an unsupported synthetic first attempt that the deterministic validator
rejects. Neither candidate passes the declared workload gate, so changing production
would overstate the evidence.

The existing `KALKI_WORKER_MODEL=qwen3:4b` setting is the rollback path and remains
unchanged. A future prompt version should explicitly define how the risk role handles
one-sided but material risk evidence. Gemma 3 is not a deferred Phase 16 requirement:
the account holder declined to accept its separate terms and later replaced the model
strategy with a separately scoped hierarchical-verifier phase. That later phase does
not reopen or hold back the completed observatory deployment.

## Production inference and resource gate

The unchanged current model failed the historical Phase 7 gate twice while Ollama
was capped at 3.5 CPUs. Both runs accepted 2/3 analyzable cases, quarantined the
injection case, timed out on corrected revenue at 240 seconds, and missed the
120-second median gate (142.27 and 137.91 seconds). This was not hidden or relabelled
as success.

The original CPU-only decision did not require a 3.5-CPU quota, and the host has
eight logical threads. Raising only Ollama's ceiling to 6 CPUs let the runtime use
about 402–404% CPU while leaving practical headroom for the public origin and
PostgreSQL. The unchanged gate then passed:

| Production gate | Result |
|---|---:|
| Analyzable acceptance | 100% (3/3) |
| Injection quarantine | 100% (1/1) |
| Required quality checks | 100% (12/12) |
| Median analyzable wall time | 119.60 s |
| Errors | 0 |
| External radar probes during inference | 82/82 HTTP 200 |
| External latency during inference | 80 ms median / 110 ms p95 / 145 ms max |

During genuine post-deploy production work Ollama used about 4.76 GiB, approximately
403% CPU, zero swap, and a peak observed package temperature of 89°C against a
reported 100°C high/critical threshold. The public process remained around 62 MiB
and continued returning successful external responses. The queue remains one model
request at a time, asynchronous, private, and bounded by the 6 GiB memory cap.
