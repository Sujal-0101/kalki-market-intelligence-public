# Local Model Benchmark

> **Status:** Phase 2 baseline completed on 2026-08-21 UTC. This is a small
> hardware/configuration benchmark, not evidence that the model is accurate for
> real investment research.

## Installation

Ollama 0.32.15 was installed for the current user at
`~/.local/opt/ollama-0.32.15`, with `~/.local/bin/ollama` pointing to its binary.
The official Linux amd64 archive was verified before extraction with SHA-256:

```text
50539c5fe9bf85887733355098dcdb266b433cb8c73fa180713417e9ed6e42bb
```

The installation used no `sudo`, system service, driver change, or CUDA
installation. Ollama is started manually, binds only to loopback, and has cloud
features disabled. The sources reviewed were the official [Linux installation
guide](https://docs.ollama.com/linux), [hardware support guide](https://docs.ollama.com/gpu),
[structured-output guide](https://docs.ollama.com/capabilities/structured-outputs), and
[Ollama releases](https://github.com/ollama/ollama/releases).

## Model selection

The baseline needed to be free to download, locally runnable within approximately
22 GiB RAM, permissively licensed, capable of schema-constrained JSON, and small
enough for repeated evaluation on this laptop. The selected model is official
[`qwen3:4b`](https://ollama.com/library/qwen3:4b):

- Qwen 3, 4.02 billion parameters, Q4_K_M quantization;
- Apache-2.0 license;
- 2,497,293,931 bytes on disk (about 2.5 GB); and
- installed model digest
  `359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`.

Models are local generated data under `~/.ollama/models` and are not committed.
The digest is recorded so a later result can identify the exact artifact used.

## Method

The repeatable harness in `kalki_market_intelligence.benchmarking` sends three
entirely synthetic cases to Ollama: contract-event extraction, correction and
contradiction handling, and risk classification. Each response is constrained by
a closed Pydantic-generated JSON Schema and then validated and scored by ordinary
code. No confidential or live market data is used.

Each case ran three times with temperature 0, seed 42, a 2,048-token context, a
256-token output cap, thinking disabled, and one server request at a time. The
predeclared gates were:

- 100% schema-valid responses;
- at least 90% exact field assertions;
- identical structured output across repeats for every case;
- no request errors; and
- median Ollama execution time excluding model load no greater than 60 seconds.

## Results

| Placement | Runs | Schema valid | Exact assertions | Deterministic cases | Median time excluding load | Median generation rate | Errors | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| GeForce 940MX (full offload) | 9 | 100% | 100% | 100% | 46.41 s | 1.53 tokens/s | 0 | Pass |
| CPU only | 9 | 100% | 100% | 100% | 12.26 s | 5.70 tokens/s | 0 | Pass |

CPU-only inference was approximately 3.7 times faster by median execution time.
The 940MX can technically load the model, but its age, 4 GB memory, and low
throughput make GPU offload counterproductive for this workload.

Ollama reported a 2.9 GB loaded model at a 2,048-token context in CPU mode. During
GPU testing, Ollama reported full GPU placement and `nvidia-smi` observed about
3.0 GB used by the model process. These are runtime observations rather than
guaranteed capacity limits; memory use can change with context length, model
version, and concurrency.

## Recommended configuration

Use CPU-only `qwen3:4b` as the initial local baseline, keep concurrency at one,
and treat qualitative jobs as asynchronous work. Start the local server with:

```bash
scripts/ollama-serve-local.sh
```

In another terminal, confirm or download the reviewed model and run the benchmark:

```bash
ollama pull qwen3:4b
.venv/bin/kalki-benchmark-ollama \
  --model qwen3:4b \
  --repeats 3 \
  --output data/benchmarks/qwen3-4b-cpu.json
```

The output directory is ignored by Git because benchmark reports are local
generated data. A downloaded model must be checked against the recorded digest
before comparing results with this baseline.

## Limits and fallback

This benchmark has only three synthetic, short-context tasks and one small model.
It does not evaluate long filings, factual recall, citation fidelity, prompt
injection resistance, broad financial reasoning, or real-world research quality.
Its 100% result must not be described as a calibrated probability or a production
accuracy estimate. Phase 7 must add representative evidence-linked evaluations
and failure tests before model output can enter the research pipeline.

If CPU latency becomes unacceptable, the safe fallback is queued or scheduled
analysis with fewer model calls. A larger model, remote service, paid API, or
hardware/driver change is not implicitly approved by this benchmark.
