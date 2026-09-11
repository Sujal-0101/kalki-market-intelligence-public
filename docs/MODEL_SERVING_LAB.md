# Isolated Model-Serving Benchmark Lab

## Decision

Production remains on private Ollama 0.32.15 with the existing digest-pinned
`qwen3:4b` Q4_K_M model, CPU-only placement, one inference at a time, and Gemma
disabled. The small genuine-filing replay did not justify a provider, model,
prompt, validator, concurrency, or production configuration change.

Qwen3 8B was not downloaded. This gate produced no paired 4B/8B quality evidence,
and introducing a larger artifact merely to search for a benefit would not satisfy
the plan's evidence-first escalation rule. A later bounded escalation experiment may
revisit it only for important ambiguous cases after the adaptive router has a closed,
testable eligibility contract; it is not a default replacement.

The lab is an engineering comparison, not evidence of investing performance or
general model accuracy. It uses three genuine SEC filings already reviewed for the
form-aware evidence checkpoint. All model inputs stay in ignored local files. The
committable reports and documentation retain only hashes, bounded counts, timing,
resource observations, and validation outcomes.

## Frozen inputs and deterministic gates

`kalki-model-serving-lab prepare` retrieves each complete submission once, verifies
its previously reviewed SHA-256, extracts the SEC-filed date, and freezes both the
accepted-baseline and form-aware packages. Package identity binds schema version,
accession, evidence strategy, analyst role, and evidence-text hash. The measured
runs replayed the exact three form-aware package identities from one package set;
they did not refetch or mutate evidence between runtimes.

Every runtime receives the same analyst prompt, JSON schema, 4,096-token context,
768-token output ceiling, deterministic seed, and one 300-second attempt. The normal
`AnalystPipeline` then applies the unchanged schema, evidence, verbatim quotation,
numeric, knowledge-cutoff, and provenance checks. A transport error, timeout,
malformed contract, unsupported claim, or non-verbatim output fails closed. The
llama.cpp adapter ignores and does not persist hidden reasoning; only final content
can enter validation. No failed output is repaired into a finding.

The ignored package set was prepared at `2026-08-31T01:14:12Z`. Its three genuine
complete-submission hashes are:

| Filing | Accession | Complete-source SHA-256 | Form-aware evidence chars |
| --- | --- | --- | ---: |
| McCormick 8-K | `0000063754-26-000305` | `290b019e...aeb5f` | 557 |
| Target 10-Q | `0000027419-26-000042` | `7033f9a6...98d8` | 3,081 |
| Koss 10-K | `0000056701-26-000034` | `34f4bdfc...6605` | 2,898 |

All nine manually inspected fragments, including both inspected numeric fragments,
were present in every measured form-aware package. This fidelity check measures the
deterministic input package, not whether a model produced a correct finding.

## Artifact and isolation provenance

The Ollama model manifest SHA-256 is
`359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`.
It references the 2,497,280,480-byte GGUF blob
`3e4cb14174460404e7a233e531675303b2fbf7749c02f91864fe311ab6344e4f`;
an independent whole-file hash matched that name. The manifest identifies Q4_K_M
quantization and the Apache-2.0 model license. The accepted Ollama executable is
version 0.32.15 with SHA-256
`eb99a47aad366636488ebd9c163a9180254dffcfdfe359939f9aabc36e2399c8`.

The alternative uses the official `ggml-org/llama.cpp` MIT-licensed project image,
version `b10689`, revision
`57291f2644af8c9df0dd8d44395881c5bdcf0ecd`. The CPU server image is pinned to
`sha256:760564cf330e7be1e3cf31ec3d3c729c672befbafdba8e3444555848ba00c306`;
the Vulkan server image is pinned to
`sha256:889cc04c53f7cbdb904ad6d3bb51767af952ee1da874e4ad833794aac4dce77b`.
Both mounted the exact Ollama GGUF blob read-only.

Alternative servers and clients ran on a temporary Docker-internal network with no
published port. Containers used a read-only root filesystem, dropped all Linux
capabilities, enabled `no-new-privileges`, had one inference slot, and had explicit
CPU and memory ceilings. The production research worker was stopped only after its
queue had zero active candidates and zero unfinished analyst attempts. Public web,
database, and supporting services remained running and were sampled throughout.

## Measured results

| Runtime | CPU/thread control | Runs | Accepted | Timeouts | Wall p50 / p90 / p95 | Result |
| --- | --- | ---: | ---: | ---: | --- | --- |
| Ollama 0.32.15, CPU | six-CPU container ceiling; runtime chooses worker threads | 3 | 2 | 0 | 109.474 / 211.112 / 223.817 s | Retain baseline |
| llama.cpp CPU | explicit 2 inference/batch threads | 3 | 0 | 3 | 300.111 / 300.140 / 300.143 s | Reject |
| llama.cpp Vulkan, 10 layers on Intel UHD 620 | explicit 2 inference/batch threads | 3 | 0 | 3 | 300.109 / 300.139 / 300.142 s | Reject |

Ollama's 8-K and 10-Q contracts were accepted as `insufficient_evidence` with zero
findings. The 10-K response was rejected for non-verbatim quotation and reported-fact
content, matching the earlier evidence-budget replay. Per-case measured prompt /
generated token rates were 21.89 / 5.10, 22.78 / 4.18, and 37.33 / 3.98 tokens per
second. Actual prompt/generated counts were 1,343/54, 2,027/85, and 1,846/744.

The two-thread llama.cpp server spent each full response window generating reasoning
without a usable final JSON contract. All three requests therefore recorded bounded
`TimeoutError` outcomes and no provider token receipt. Server timing logs showed
roughly 2.8--3.4 generated tokens per second before cancellation; prompt rate and
final response token counts remain truthfully unavailable rather than inferred.
A higher-thread CPU run was screened out after the two-thread resource observer
captured the hardware's 100°C package threshold.

The ten-layer Intel Vulkan replay likewise returned no usable final JSON. Its three
requests timed out at 300.056--300.146 seconds while server logs reported roughly
2.4--2.7 generated tokens per second. It therefore provided neither a contract-quality
benefit nor a throughput benefit over the already rejected two-thread CPU path.

## Resource and public-service observations

The automated two-thread llama.cpp trace contains 106 five-second samples. Runtime
CPU peaked at 205.83%, memory at 3,199,750,636 bytes, and CPU package temperature at
100°C. Minimum host-available memory was 14,798,487,552 bytes. Swap began and ended
at 1,613,725,696 bytes, so measured growth was zero. All 106 public `/radar` checks
returned HTTP 200; median latency was 0.0277 seconds and maximum was 0.0615 seconds.

During the Ollama replay, direct observations found about four CPUs, approximately
3.06--3.57 GiB runtime memory, a peak sampled package temperature of 86°C, and no
change from the same 1,613,725,696-byte swap baseline. Sampled `/radar` requests were
HTTP 200 in approximately 0.035--0.066 seconds. These were interactive bounded
observations rather than the later automated trace, so no unsupported sample count or
percentile is claimed.

The automated Intel Vulkan trace contains 146 five-second samples. Runtime CPU peaked
at 167.77%, memory at 4,236,985,238 bytes, and package temperature at 91°C. Swap grew
by 450,560 bytes. All 146 public `/radar` checks returned HTTP 200; median latency was
0.0306 seconds and maximum latency was 0.0646 seconds. This remains a small engineering
sample and does not justify an accelerator or runtime change.

## Accelerator screen

The official Vulkan image detected the Intel UHD Graphics 620 through
`/dev/dri/renderD128`. The NVIDIA GeForce 940MX render node exposed no Vulkan device
inside that image, and Docker has no NVIDIA container runtime configured. CUDA is
therefore not a genuinely supported llama.cpp container path on this host. No driver,
runtime, system package, or security boundary was changed. The older accepted Ollama
benchmark also found full 940MX offload materially slower than CPU-only inference,
so there is no evidence-based reason to add a CUDA dependency.

The measured Vulkan server had no published port and ran only on the temporary
Docker-internal lab network. Its permissive built-in CORS default was therefore not a
public origin, but it is another reason this unmodified upstream server configuration
is benchmark-only rather than a production deployment candidate.

## Reproduction boundary

The two entry points are:

```bash
kalki-model-serving-lab prepare --output data/benchmarks/<ignored-package-set>.json
kalki-model-serving-lab run --packages data/benchmarks/<ignored-package-set>.json \
  --output data/benchmarks/<ignored-report>.json <pinned-runtime-arguments>
kalki-observe-model-serving --runtime-container <private-server> \
  --client-container <private-client> --output data/benchmarks/<ignored-resource-report>.json
```

The operator must independently pin and verify the runtime image, model blob, server
fingerprint, network isolation, CPU/thread controls, placement, and resource ceilings.
When the client writes into a bind-mounted ignored directory, it must run with the
owning host UID/GID; the first Vulkan report write exposed and corrected this boundary
after all inference calls had completed. That failed write is not counted as a model
result, and the same frozen package set was replayed to create the final report.
Reports are created exclusively and never overwrite an earlier run. The harness does
not deploy a runtime, update production settings, publish model content, enable model
concurrency, download Qwen3 8B, or enable Gemma.
