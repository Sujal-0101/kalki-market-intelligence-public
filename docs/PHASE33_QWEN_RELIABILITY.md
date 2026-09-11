# Phase 33 Qwen analyst reliability

> **Status:** Implemented, deployed, recovery-tested, and live-validated on
> 2026-08-27 UTC. The observation sample is deliberately labelled small-N.

## Scope

Phase 33 preserves the existing `qwen3:4b` model, digest, `analyst-v2` prompt,
closed report schema, deterministic evidence checks, two-attempt ceiling, and
300-second provider timeout. It adds measurement; it does not relax any
publication or evidence threshold.

Every actual autonomous-candidate or private-human provider request now creates a
durable `research_analyst_attempts` row before Ollama is called. The row is
completed exactly once after success or failure. A worker exit during inference
leaves an honest `started` row rather than erasing the attempt; after the same
30-minute lease used for work-item recovery expires, the next worker cycle closes
it as a response-free runtime/provider failure with every validation check marked
`not_checked`. Retryability is granted only while the parent is still active and
the stored start context allowed a runtime retry. The database prevents
identity/input changes, a second completion, deletion, and truncation.

## Retained metadata

Each receipt contains only bounded operational and provenance metadata:

- candidate accession or private human lead ID, plus ticker, CIK, form, and
  accession;
- configured provider, model, digest, prompt/output-schema/validator versions,
  analyst role, work-item attempt, model-attempt number, and semantic-retry flag;
- UTC start/completion, latency, evidence count/characters, prompt character
  counts, context/output limits, returned token counts, response character/byte
  counts, and a SHA-256 response hash;
- parse, schema, and evidence-gate statuses; format, content/evidence, or runtime
  failure layer; a bounded category/path; retry scope; outcome; and terminal
  disposition.

It never stores a system or user prompt, evidence text, a human hypothesis, model
response content, unrestricted error text, hidden reasoning, a secret, or a public
raw transcript. If receipt persistence fails, the model result is not used.

The bounded failure vocabulary is: `malformed_json`, `extra_prose`,
`missing_required_field`, `invalid_type`, `invalid_enum`, `invalid_evidence_id`,
`unsupported_claim`, `numeric_conflict`, `provenance_failure`, `timeout`,
`refusal`, `provider_error`, and `other`. Surrounding prose is classified but is
not stripped or accepted. The existing one model repair request remains the only
format retry; no substantive failure is mechanically repaired.

## Migration and recovery

Migration `0010_analyst_attempt_receipts` is forward-only because removing the
table could destroy diagnostic history. Apply it only after a verified backup:

```bash
./scripts/backup-postgres.sh
./scripts/restore-postgres-gate.sh backups/postgres/kalki-YYYYMMDDTHHMMSSZ.dump
./scripts/migrate-analyst-attempt-receipts.sh
```

The backup manifest and isolated restore gate include the receipt table when it
exists. `scripts/test-analyst-attempt-postgres.sh` applies the complete migration
history to a network-disabled disposable PostgreSQL instance and proves candidate
and human lifecycle, grants, single completion, and mutation/deletion rejection.

Migration `0024_stale_analyst_attempt_recovery` permits the durable receipt lifetime
to exceed the original two-hour synchronous-call limit while retaining PostgreSQL's
nonnegative bigint bound. It does not rewrite an attempt. Validate the recovery
lifecycle with `scripts/test-analyst-attempt-recovery-postgres.sh` and apply it only
after a verified backup with `scripts/migrate-stale-analyst-attempt-recovery.sh`.
Recovery lifetimes are excluded from provider-latency distributions because the
provider's exact stop time is unknowable after a process interruption.

## Aggregate report

The private operator report contains aggregates only:

```bash
./scripts/report-analyst-attempts.sh 168
```

It reports started/incomplete/completed attempts, valid contracts, failure layers
and categories, timeouts/provider failures, pipeline and work-item retries/retry
successes, origin counts, and latency minimum/p50/p95/maximum. Fewer than 30
completed attempts is explicitly labelled `small_n`. This report is descriptive
operational evidence, not a quality probability.

## Current limits

- Historical MSFT, TEM, and autonomous attempts predate migration 0010; their exact
  categories and response hashes cannot be reconstructed and remain unknown.
- A recovered receipt proves invocation began and that no completion was durable by
  lease expiry; it does not claim that Ollama returned or identify the exact provider
  stop time. No response, validation result, or earlier completion time is inferred.
- CPU and RAM remain host/container observations rather than model-supplied facts.
  Qwen remains serialized and Gemma remains disabled.

## Initial production observation

Migration 0010 was applied at 2026-08-27 07:14:12 UTC only after backup
`kalki-20260827T071353Z.dump` passed an isolated network-disabled restore. The
new non-root image (`sha256:17dd406a...0d321`, about 64.2 MB) replaced only the
worker at 07:28:40 UTC after the old batch completed. Public/admin/database/model
services were not recreated.

The first new worker cycle processed genuine SEC candidates BBCQ accession
`0001213900-26-094046` and FLZH accession `0001213900-26-094039`. Each invoked
the catalyst and balanced bull/bear/risk roles. All four first attempts passed
JSON parsing, the closed schema, evidence-ID/quote/support validation, and numeric
token checks. Latencies were 182,201; 208,175; 209,978; and 242,570 ms (small-N
median 209,076.5 ms, p95 237,681.2 ms). Prompt-token counts were 2,290–2,421,
generated-token counts were 54–113, and response sizes were 170–433 bytes. There
were zero format, content/evidence, provider, or timeout failures and therefore
zero repair attempts/retry successes in this four-attempt window.

Both candidates were deterministically skipped after valid analysis. The cycle
completed at 07:42:48 UTC with two analyzed, zero published, two skipped, and no
error. No dossier or Discord delivery was created. During inference Ollama was
observed at about 5.37 GiB and roughly two CPU cores; the worker was about 50 MiB.
The external radar remained HTTP 200 (86 ms in the final probe), external admin
remained 404, and the worker returned to a successful idle state.

Post-migration backup `kalki-20260827T074319Z.dump` retained exactly four receipt
rows and passed the isolated restore gate. Historical MSFT/TEM failure details
remain unknown; the live success window does not retroactively reconstruct them
or justify a model/prompt/timeout change.

## Production Recovery II reliability correction

The larger subsequent production sample showed that the initial small-N success
did not generalize to long excerpts. Before recovery deployment, 114/314 candidate
calls timed out; timeout inputs had 7,631 median evidence characters versus 2,544
for accepted calls. Attempts four through six timed out 78.6--81.0% of the time.
After migration 0013, the first 50 completed calls at the inherited two-CPU Gemma
qualification limit contained 32 accepted contracts, one bounded rejection and 17
timeouts. The timeout evidence median/p90 was 5,920/9,500 characters, and timeout
latency remained 300,101 ms.

Gemma remains disabled. Qwen's prior fixed-fixture and public-latency gate had
already proven a six-logical-CPU ceiling, while lower limits failed. Restoring that
ceiling preserved one-request serialization and improved the fixed production gate
to 100% analyzable acceptance, 100% injection quarantine, 100% required quality
checks, zero errors and an 89.42-second median. It did not solve two representative
5,076- and 7,592-character genuine calls, which still timed out at 300 seconds.

The measured workload correction therefore retains the model, digest, prompt,
schema, 4,096-token context, 768-token output cap, temperature, seed and 300-second
timeout while reducing only deterministic evidence selection. At most six diverse
560-character keyword windows and 3,600 characters reach Qwen. Opportunity and risk
coverage are each reserved when present, and a keyword can affect routing/scoring
only when it remains in the evidence actually supplied. This reduces irrelevant
repeated context without weakening exact quote, evidence-ID, schema, numeric, XBRL,
provenance or publication validation.

Deterministic local-model work now stops after three work attempts. Exhaustion is
recorded prospectively as `ANALYSIS_INCOMPLETE`; it is never converted into a
screened-out filing. This matches the existing non-provider ceiling and prevents
the measured low-yield fourth-through-sixth timeout cohort from monopolizing the
serialized queue. The separately disabled verifier recovery ceiling remains six.
