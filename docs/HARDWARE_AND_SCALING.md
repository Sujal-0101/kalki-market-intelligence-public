# Hardware and scaling guide

Hardware can make Kalki faster; it cannot turn weak evidence into strong evidence.
The accepted Observation Baseline V2 uses one serialized Qwen3 4B request and keeps
Gemma/model concurrency disabled. Any scaling change needs workload measurements and
the same evidence/publication gates.

## Evidence labels

Every capacity statement uses one label:

- **Measured on reference hardware** — directly observed on the accepted machine.
- **Derived from implementation constraints** — follows from configured limits,
  artifact sizes, or architecture, but is not a benchmark of another machine.
- **Expected but unbenchmarked** — reasonable engineering expectation that still
  needs measurement.
- **Future experimental possibility** — not an implemented production capability.

## Reference hardware — the machine on which Kalki was developed and production-tested

Read-only commands were run on 2026-09-09. Serial numbers, MAC addresses, IP
addresses, filesystem UUIDs, and other unique device identifiers were deliberately
excluded.

| Component | Factual reference configuration | Evidence |
|---|---|---|
| System | Dell Inspiron 7570 laptop | Read-only DMI product name |
| OS | Ubuntu 26.04 LTS; Linux 7.0.0-30-generic | `/etc/os-release`, `uname -a` |
| Architecture | x86_64 | `uname`, `lscpu` |
| CPU | Intel Core i7-8550U @ 1.80 GHz; reported maximum 4.00 GHz | `lscpu` |
| CPU topology | 1 socket, 4 physical cores, 8 logical CPUs | `lscpu`, `nproc` |
| RAM | 24 GB installed class; 22 GiB usable reported by Linux | existing machine record, `free -h` |
| Integrated GPU | Intel UHD Graphics 620 | `lspci` |
| Discrete GPU | NVIDIA GeForce 940MX | `lspci`, `nvidia-smi` |
| Discrete VRAM | 4,096 MiB | `nvidia-smi` |
| Storage | 250 GB-class WD Blue SN570 NVMe; 232.9 GiB device, 228 GiB root filesystem | `lsblk`, `df -h /` |
| Free storage at audit | 156 GiB (29% root filesystem used) | `df -h /` point observation |

### Measured runtime envelope

- **Measured:** the accepted Ollama container is capped at 6 logical CPUs, 14 GiB
  RAM and no additional swap; application/PostgreSQL containers have independent
  smaller limits.
- **Measured:** `qwen3:4b` Q4_K_M is 2,497,293,931 bytes on disk, has 4.02 billion
  parameters, uses a 4,096-token context and 768-token output cap.
- **Measured:** a read-only busy snapshot during Qwen work showed Ollama using about
  four CPU cores and 10.67 GiB container memory. This is a single point, not a peak
  benchmark.
- **Measured:** Phase 33 recovery reduced one same-filing role from repeated
  300-second timeouts to 92.849 seconds with the bounded evidence budget; another
  completed in 97.283 seconds, while a different catalyst call took 198.611 seconds.
  Tail calls can still reach the 300-second timeout.
- **Measured:** the 940MX path was slower than CPU in the Phase 2 workload, so the
  accepted Compose configuration forces CPU (`CUDA_VISIBLE_DEVICES=-1`, Vulkan off).
- **Measured:** during the audit snapshot, active CPU inference coincided with
  package/core temperatures around 86–90°C and high fan speed. That is an operational
  observation, not a safe universal temperature threshold.
- **Measured:** inference is serialized (`OLLAMA_NUM_PARALLEL=1`). All 5,088 Phase 45
  baseline attempt receipts shared the same model/digest/prompt/schema lineage.

## Hardware classes

These are deployment-planning classes, not guarantees. Only the reference class is
production-tested for Kalki.

| Class | CPU | RAM | GPU | Storage | Confidence and use |
|---|---|---:|---|---:|---|
| Minimum practical | 4 modern x86-64 cores | 16 GiB | None | 100 GB SSD | **Derived**, untested floor for serialized 4B CPU inference with low contention; expect slow tails and little headroom |
| Reference/tested | i7-8550U, 4C/8T | 24 GB installed / 22 GiB usable | 940MX 4 GB, not used for accepted inference | 250 GB NVMe | **Measured** accepted system |
| Recommended home server | 8 modern performance cores / 16 threads | 32 GiB | Optional; CPU-only remains valid | 500 GB NVMe SSD | **Expected but unbenchmarked**: more OS/database/cache headroom and better sustained CPU throughput |
| Performance | 12–16 modern cores, strong memory bandwidth | 64 GiB | Optional supported NVIDIA GPU with 12–16 GB VRAM | 1 TB NVMe | **Expected but unbenchmarked** for faster 4B inference and controlled larger-model experiments |
| High-end workstation/server | 16+ cores | 128 GiB | Supported 24 GB+ VRAM accelerator | 2 TB+ NVMe with separate backup storage | **Future experimental possibility**; does not justify concurrency/model changes without gates |

Why the minimum is not 8 GiB: the accepted Ollama process alone was observed above
10 GiB during inference, while PostgreSQL, Docker, the OS, page cache, and workers
must remain responsive. Why it is not a guarantee: CPU generation, memory bandwidth,
thermals, filing mix, kernel, and model runtime matter more than a core count alone.

## How resources affect Kalki

### CPU

**Implemented work:** SEC HTML parsing, form-aware section extraction, hashing,
regex/structured forensic detectors, filing diffs, XBRL normalization/matching,
numeric `Decimal` validation, JSON schema validation, PostgreSQL work, web rendering,
and CPU Qwen inference.

- **Measured:** Qwen dominates CPU time on the reference machine and can use roughly
  four cores under a six-logical-CPU allowance.
- **Derived:** more modern cores and higher memory bandwidth can shorten CPU inference
  and let deterministic workers remain responsive, but Kalki still submits only one
  model request at a time.
- **Expected but unbenchmarked:** a modern desktop CPU should sustain clocks better
  than the reference 15 W-class laptop CPU and reduce backlog latency.
- **Future experimental:** CPU-only 8B/14B analysis may be possible with enough RAM,
  but latency could be operationally unacceptable. Qualification is mandatory.

### RAM

RAM holds model weights/runtime working memory, context/KV state, PostgreSQL shared
buffers and working sets, Docker processes, filesystem cache, and the OS.

- **Measured:** the reference host's 24 GB class is workable for serialized Qwen3 4B
  with a 14 GiB hard container limit and host headroom.
- **Derived:** 16 GiB leaves narrow headroom; stop unrelated workloads and monitor
  swap/pressure. Heavy swapping makes inference unpredictable.
- **Expected but unbenchmarked:** 32 GiB is the best general home-server balance;
  64 GiB gives room for controlled larger-model experiments and larger database
  cache.
- **Future experimental:** 128 GiB can host larger CPU models/embedding indexes, but
  capacity does not establish accuracy or a product need.

### GPU and VRAM

Ollama can use supported NVIDIA CUDA, supported AMD ROCm, and selected Vulkan paths;
support changes, so check [Ollama's current hardware list](https://docs.ollama.com/gpu).

- **Measured:** 940MX has 4 GB VRAM and is slower than the CPU for Kalki's accepted
  workload. It cannot comfortably hold the whole accepted runtime working set and is
  disabled.
- **Derived:** full model offload needs enough VRAM for quantized weights plus context
  and runtime overhead; model file size alone is not the requirement. Partial
  offload may help or hurt depending on PCIe bandwidth and CPU/GPU balance.
- **Expected but unbenchmarked:** a supported 12–16 GB GPU may substantially reduce
  4B latency and may fit some 8B/14B quantizations; measure exact model/context.
- **Future experimental:** a 24 GB GPU could support larger local verifier or vision
  experiments. It does not authorize multimodal evidence, concurrent analysts, or
  replacing deterministic validation.

Prefer a supported recent GPU with enough VRAM over an old low-end discrete GPU.
Before buying, verify driver support on the intended Linux release and test Ollama's
actual offload report, power, acoustics, and sustained thermals.

### Storage

Storage contains PostgreSQL ledgers, indexes/WAL, Docker layers/build cache, Ollama
models, controlled fixtures, logs, and backups.

- **Measured:** the current repository is small (roughly 24 MiB of reachable loose
  Git objects), but the Qwen artifact is roughly 2.5 GB and runtime images/model
  caches are much larger.
- **Derived:** 100 GB is a practical floor, not because the database currently needs
  it, but to retain OS updates, Docker layers, models, WAL/headroom, and multiple
  verified backups without approaching a full filesystem.
- **Expected but unbenchmarked:** NVMe improves image builds, model load, PostgreSQL
  checkpoints, backup/restore, and random index access. Model token generation on
  CPU is usually compute/memory-bandwidth bound after loading.
- HDD is acceptable for encrypted offline backups. It is a poor primary choice for a
  responsive mixed Docker/PostgreSQL/model workload.

Never store the only backup on the same physical device. PostgreSQL data checksums
help detect some corruption; they do not replace backups.

### Networking

- **Implemented:** outbound HTTPS to SEC for indexes, filings, submissions, and
  CompanyFacts.
- **Optional:** outbound Discord Gateway/webhook traffic and outbound Cloudflare
  Tunnel.
- **Disabled:** live optional market-provider calls.
- **Derived:** raw bandwidth is less important than reliable DNS/TLS and stable
  connectivity. A large SEC complete submission can be tens of megabytes.
- No inbound port is needed for a local deployment or Cloudflare Tunnel. Do not expose
  database/model/admin ports.

### Thermals and power

Laptop cooling is designed for bursts, whereas serialized inference can sustain load
for minutes.

- **Measured:** the reference laptop reached high-80s/90°C during a busy snapshot.
- **Derived:** thermal throttling increases timeout risk and backlog variability.
- Keep vents clear, clean dust with the machine powered off, use a hard surface, and
  monitor rather than overriding fan controls.
- A desktop heatsink, larger chassis, and conservative power limit can improve
  sustained throughput more than short boost-clock specifications suggest.
- Use a UPS if interruptions are common. PostgreSQL handles crashes, but clean
  shutdown and tested restore remain safer.

Kalki does not prescribe a universal temperature limit; follow the CPU/system vendor
specification. If temperature rises unexpectedly, pause workers, preserve the
database, and diagnose cooling.

## Scaling opportunities and non-guarantees

| Possible improvement | Status | What better hardware might change | What it cannot establish |
|---|---|---|---|
| Faster Qwen3 4B | Implemented workload | Lower per-role latency and backlog | Better factual accuracy by itself |
| Larger 8B/14B model | Future experiment | More capacity if RAM/VRAM and latency allow | Superiority without fixed evidence benchmarks |
| Larger context | Future experiment | More evidence can fit | Relevance; extra context can degrade contracts and speed |
| More capable verifier | Disabled/future | Faster independent review on selected cases | Authority over deterministic evidence |
| More worker throughput | Partly implemented | Deterministic backlogs may clear faster | Safe model concurrency without measurements |
| Vision/multimodal filing analysis | Not implemented | Suitable GPU could run local vision models | Trustworthy chart/table extraction without new provenance tests |
| Local embeddings/RAG | Not implemented | RAM/SSD can host an index | Point-in-time correctness, source rights, or product need |
| Faster benchmarks | Implemented harness | More repetitions/configurations in a fixed window | Transfer to production without representative cases |

The preferred scaling order is: reduce unnecessary work deterministically; bound
evidence; cache identical work; measure; improve single-request latency; only then
consider concurrency. Parallel model calls can increase throughput on a capable GPU,
but can also exhaust VRAM, extend tail latency, and reduce public responsiveness.

## Upgrade priorities by optional budget

Prices vary by country and time. These are priority frameworks, not current product
recommendations or spending requirements.

### If you have $0

**Derived from implementation constraints:**

1. Keep the accepted evidence budget and serialization.
2. Stop unrelated CPU/RAM-heavy services during backlog processing.
3. Improve cooling/airflow safely and keep adequate disk headroom.
4. Schedule backups and inference away from each other.
5. Measure `docker stats`, attempt latency, swap, filesystem use, and temperature.
6. Use existing SSD space efficiently; inspect before deleting anything.

### If you have about $200

**Expected but unbenchmarked:** prioritize reliability: a larger quality SSD if the
current disk is constrained, an external backup drive, additional compatible RAM to
32 GB, or a UPS. On the reference laptop, RAM/backup reliability is likely more
useful than buying another 4 GB-class legacy GPU. Confirm laptop upgrade compatibility
before purchase.

### If you have about $500

**Expected but unbenchmarked:** a used/recent desktop platform with 8+ modern cores,
32–64 GB RAM, and 500 GB–1 TB NVMe may improve sustained CPU inference and thermals.
Alternatively, retain the current host and fund a supported 12 GB-class GPU only
after confirming power supply, chassis, Linux driver, and Ollama compatibility.

### If you have $1000+

**Future experimental possibility:** a balanced workstation—modern 12–16 core CPU,
64–128 GB RAM, reliable NVMe plus independent backup, and supported 16–24 GB VRAM
GPU—can shorten inference and enable larger-model/verifier experiments. Preserve
budget for storage, cooling, power supply, and backup; the largest GPU is not the
whole system. Rerun fixed model, evidence, resource, and publication gates before
changing production.

## Benchmarking a candidate machine

Use an immutable Kalki commit and exact model digest. Record:

1. CPU, RAM, GPU/VRAM, storage, OS/kernel, Ollama/driver versions;
2. model name/digest/quantization/context/output cap;
3. prompt/schema/validator/evidence-budget versions;
4. cold and warm latency, accepted/rejected/timeout counts, token counts;
5. peak/steady RAM, swap, CPU, GPU offload/VRAM, temperature and power;
6. public-route latency while inference runs;
7. reproducibility over multiple representative roles/forms.

Do not use a synthetic benchmark to claim research accuracy or investment
performance. It measures a defined computing workload only.
