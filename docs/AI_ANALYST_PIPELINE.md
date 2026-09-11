# Structured AI Analyst Pipeline

> **Status:** Phase 7 completed on 2026-08-21 UTC with a synthetic local-model
> evaluation. Model output remains untrusted and cannot become a market fact or
> trigger an action merely because it is valid JSON.

## Trust boundary

`AnalystPipeline` accepts one narrow role, one to eight retrieved evidence
excerpts, and a UTC knowledge cutoff. It returns `ValidatedAnalysis` only after
deterministic validation. The output records provider/model identity, model
digest, prompt and validator versions, attempts, evidence IDs/hashes, cutoff,
completion time, and any code-proven normalization.

The configured provider is replaceable. `OllamaModelProvider` accepts only an
uncredentialed loopback HTTP origin, sends no tools or function definitions, caps
request time and response bytes, uses temperature zero/seed 42, and supplies a
closed JSON schema. `SequenceModelProvider` supports deterministic offline tests.

The implementation follows the official [Ollama structured-output guidance](https://docs.ollama.com/capabilities/structured-outputs)
and treats prompt injection as the untrusted-data/instruction-confusion problem
described by [NIST](https://csrc.nist.gov/glossary/term/prompt_injection) and
[OWASP LLM01](https://genai.owasp.org/llmrisk/llm01-prompt-injection/).

## Analyst roles

Prompt version `analyst-v1` defines six narrow roles:

- document interpreter;
- catalyst analyst;
- partnership analyst;
- management-commentary analyst;
- contradiction analyst; and
- balanced bull/bear/risk analyst.

Each role has allowed finding categories. The document interpreter can report
only neutral verbatim facts. Bull/bear/risk output remains labeled inference and
cannot score, rank, promise returns, or issue trade instructions.

## Validation and normalization

The source block is JSON-encoded and delimited as untrusted evidence. A
conservative scanner quarantines high-confidence instruction patterns before any
model call. This scanner is defense in depth, not proof that arbitrary text is
safe. The model has no tools, secrets, browser, network authority, or write access.

After generation, ordinary code applies these gates:

1. Parse the closed `AnalystReport` schema and enforce the requested role/prompt
   version and report-shape invariants.
2. Allow only evidence IDs from the request and require every citation quote to
   be an exact substring of that evidence.
3. Require every `reported_fact` statement to equal a cited quote; reported facts
   always become neutral.
4. Require every number and URL in a finding/topic to appear in its exact cited
   text.
5. Require inference language to have a minimum lexical overlap with cited text;
   this blocks plainly unrelated synthesis but is not semantic proof.
6. Enforce role/category boundaries and coherent contradiction assessment.
7. Use availability timestamps and explicit words such as `correction`, `revises`,
   or `supersedes` to deterministically resolve a later correction.

Three mechanically provable labels are normalized rather than trusted: fact
polarity becomes neutral, reports with contradictions become
`conflicting_evidence`, and explicit later corrections become
`resolved_by_later_correction`. Every applied normalization is written to the
audit record. No prose, figure, quote, citation, or qualitative inference is
silently created by normalization.

An invalid response receives only bounded error codes and one complete repair
attempt. After two failed attempts, `AnalysisRejected` is raised and no report
crosses the boundary. Unsafe evidence is quarantined with no model call.

Phase 33 adds a durable pre-call/completion receipt for every production provider
attempt. Receipts retain only identities, versions, timestamps, bounded sizes,
response hashes, validation states, failure category/path, and retry disposition;
they never retain prompts, evidence text, raw responses, human hypotheses, hidden
reasoning, or secrets. Receipt persistence is fail-closed. See
`PHASE33_QWEN_RELIABILITY.md`.

## Synthetic quality gate

The tracked fixture contains three analyzable cases—contract catalyst,
non-binding partnership, and corrected revenue—plus one prompt-injection case.
Every company, source, event, and figure is invented. The predeclared gate is:

- 100% post-validation acceptance for analyzable cases;
- 100% quarantine for the injection case;
- at least 80% required evidence/assessment/contradiction checks;
- median per-case wall time no greater than 120 seconds; and
- zero errors.

CPU-only `qwen3:4b` (digest
`359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`)
passed on 2026-08-21 UTC:

| Gate | Result |
|---|---:|
| Analyzable acceptance | 100% (3/3) |
| Injection quarantine | 100% (1/1) |
| Required quality checks | 100% (12/12) |
| Median analyzable wall time | 112.83 seconds |
| Errors | 0 |

One catalyst case used the permitted repair attempt; the other analyzable cases
completed in one attempt. The generated report is ignored local data under
`data/evaluations/`. Ollama was manually stopped after evaluation.

Phase 16 reran this unchanged gate from the production image. The 3.5-CPU container
ceiling timed out twice on corrected revenue; a measured 6-of-8-logical-CPU ceiling
let Ollama use about four cores and pass at 119.60 seconds median, with 3/3
acceptance, 1/1 quarantine, 12/12 checks, and zero errors. See
`PHASE16_MODEL_EVALUATION.md` for the failed runs, external latency measurements,
host envelope, and model comparison.

Run the gate after starting the loopback-only service:

```bash
scripts/ollama-serve-local.sh
```

In another terminal:

```bash
.venv/bin/python -m kalki_market_intelligence.analysis.evaluation \
  --model qwen3:4b \
  --output data/evaluations/phase7-qwen3-4b.json
```

## Limits

- Four short synthetic cases are not a real-world accuracy estimate or calibrated
  probability. The gate does not validate long filings or broad company coverage.
- Lexical grounding cannot prove that every qualitative inference is logically
  sound. Human editorial review remains necessary before public research.
- Conservative injection scanning can have false positives and pattern-based
  defenses can have false negatives. No future phase should grant source text or
  model output authority to invoke tools.
- No analyst output enters the immutable prediction ledger automatically. Phase 15
  persists validated analysis only as filing-radar briefs after additional
  deterministic scoring and publication gates.
- The current local model is slow. Analysis should remain queued/asynchronous;
  paid or remote inference is not implied or approved.
