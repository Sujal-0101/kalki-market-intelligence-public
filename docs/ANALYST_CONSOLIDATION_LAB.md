# One-Call Analyst Consolidation Shadow Lab

## Decision

Retain the accepted two-role Qwen3 4B worker path. The shadow one-call contract cut
measured calls and elapsed time in this three-filing replay, but the sample contained
no validated findings in either mode. It therefore cannot establish material evidence
or conclusion non-regression. No worker, prompt, model, context, timeout, validator,
publication or Discord setting changes.

The result is `insufficient_substantive_comparison`, not evidence that consolidation
is equivalent or better. The consolidated contract stays isolated and shadow-only.

## Fixed boundary

The replay used form-aware packages from ignored package set SHA-256
`395402cab54b543aec994d977660a7167f1cdf9836423be51fe6f9c22d633f10`.
Those packages bind the genuine McCormick 8-K, Target 10-Q and Koss 10-K source and
evidence hashes used by the accepted serving lab.

Both modes used private CPU-only Ollama 0.32.15 and Qwen3 4B digest
`359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`,
4,096 context tokens, 768 maximum output tokens, deterministic seed 42, one attempt
per call and a 300-second timeout. Calls were strictly serialized. Gemma, Qwen3 8B,
llama.cpp and concurrent inference were absent.

The current mode replayed the production role order—catalyst, then bull/bear/risk—
against the same evidence. The shadow mode required one response with explicit
material-fact, catalyst, positive-factor, negative-factor, risk, contradiction and
limitation fields. Every section reused the accepted exact evidence-ID, verbatim quote,
reported-fact, lexical grounding, numeric, URL, temporal and provenance validators.
No output repair, publication or delivery path exists.

## Results

| Genuine filing | Current calls accepted | Current seconds | Shadow calls accepted | Shadow seconds | Validated findings |
| --- | ---: | ---: | ---: | ---: | ---: |
| McCormick 8-K `0000063754-26-000305` | 2/2 | 142.675 | 1/1 | 78.825 | 0 / 0 |
| Target 10-Q `0000027419-26-000042` | 2/2 | 150.319 | 1/1 | 78.897 | 0 / 0 |
| Koss 10-K `0000056701-26-000034` | 1/2 | 267.803 | 1/1 | 65.843 | 0 / 0 |

The current path used six completed calls and 560.797 seconds; consolidated shadow
used three calls and 223.565 seconds. The shadow/current elapsed ratio was 0.3987,
and median case elapsed time was 78.825 versus 150.319 seconds. Current/shadow prompt
tokens were 2,694/1,356 for McCormick, 4,042/2,030 for Target and 3,680/1,849 for
Koss. These are small, order-sensitive engineering measurements and do not establish
a general speedup.

The current Koss bull/bear/risk response repeated the known fail-closed behavior:
non-verbatim reported content was rejected. The consolidated Koss response passed its
contract but contained no findings. All other accepted contracts also contained no
findings. Input fragment fidelity passed in both modes, and zero-count citation/numeric
checks did not regress, but zero compared conclusions are not substantive evidence of
semantic equivalence.

## Privacy and operating observations

The ignored report SHA-256 is
`560d14e9e51c3e449ab1592cf7cc453cb0c7b9550f9d99ada5342fe64a21ddc8`.
It retains only package/source/evidence hashes, bounded statuses, counts, token/timing
metrics and failure categories. It contains no prompt, source text, excerpt, response,
finding statement, hidden reasoning, human research, Discord identity or exception
detail.

The accepted research worker was paused only after direct database checks showed zero
processing candidates and zero unfinished analyst attempts. Public radar remained HTTP
200 during sampled checks, observed Ollama memory was about 3.1–3.7 GiB, model CPU was
about four cores and the hottest sampled package temperature was 86°C. The worker was
restored healthy with zero restarts/OOMs and completed its next production cycle. No
schema, migration, immutable record or production configuration changed.

## Reproduction boundary

The command is deliberately operator-controlled and report-exclusive:

```bash
kalki-consolidation-lab \
  --packages data/benchmarks/<ignored-package-set>.json \
  --output data/benchmarks/<new-ignored-report>.json \
  --base-url <private-ollama-url> \
  --model qwen3:4b \
  --expected-digest <pinned-digest> \
  --timeout 300
```

It does not start, stop, deploy or configure a service. The operator owns isolation,
serialization and safe worker pause/restore. A later adoption review needs a larger
identical-package set with substantive validated findings and must pass every quality
gate; lower call count alone is insufficient.
