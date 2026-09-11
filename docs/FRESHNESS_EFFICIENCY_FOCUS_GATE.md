# Mandatory Freshness, Efficiency and Focus Gate

## Event novelty checkpoint

The first gate slice adds a closed event-level distinction that is independent of a
filing's date. The allowed outcomes are `NEW_EVENT`, `MATERIAL_UPDATE`,
`RECAP_EXISTING_EVENT`, `DUPLICATE_DISCLOSURE`, `HISTORICAL_CONTEXT`, and
`UNKNOWN_NOVELTY`. A complete prior search is required before absence can prove
`NEW_EVENT`; the current prospective design has no reviewed issuer-IR history
adapter, so an absent prior remains `UNKNOWN_NOVELTY`.

The initial deterministic extractor is deliberately narrow. It supports explicit
strategic-partnership grammar with at least two source-stated entities and optional
source-stated amounts. It normalizes comparison keys without guessing corporate
identity, keeps event and fact fingerprints separate, and retains exact bounded
evidence tied to the complete source hash. Unsupported or ambiguous text produces no
disclosure rather than a plausible event.

For supported events, the filing worker performs the comparison before Tier-0 and
Qwen. Evidence classified as a recap, duplicate, or explicit historical context is
removed by exact quote from the bounded model package. Other filing evidence remains
eligible for the normal single pipeline. `UNKNOWN_NOVELTY` is never relabelled new.
No model, prompt, context, concurrency, score, evidence validator, publication rule,
public route, Discord path, or human-research boundary changes in this slice.

## NVIDIA regression provenance

> [!NOTE]
> This section records the private engineering evidence used at the original gate.
> For the public-source candidate, the copied issuer-release sentence and its SEC
> recap fixture were replaced with fully synthetic, structurally equivalent text.
> The current test still proves identical event/fact fingerprints, recap
> classification, unknown first-known time, and pre-Qwen evidence removal without
> redistributing issuer prose or implying that its reserved URLs are live sources.

The required regression uses two genuine primary-source disclosures inspected on
2026-08-30 UTC:

- NVIDIA's official investor-relations disclosure for the strategic compute-financing
  partnerships with Apollo, BlackRock, Blackstone, Brookfield, Goldman Sachs, and KKR;
  the complete retrieved page hash is
  `741890daa0036c343288b44725813ef9e047abbe9f0ebed8f78dc00587cddeaa`.
- NVIDIA's later SEC-filed Q2 fiscal 2027 earnings exhibit under accession
  `0001045810-26-000073`; the complete exhibit hash is
  `1809cb206590dcfeb959f3a1a64157f4e5ee42788ec51289b74f3ea299931eb7`.

Both bounded fixtures retain the same six counterparties and the source-stated
greater-than USD 500 billion third-party-capital term. The later SEC filing is a new
source record but the partnership content is `RECAP_EXISTING_EVENT`, and its exact
sentence is absent from the pre-Qwen evidence after filtering. The issuer page
supplied a calendar date but not a precise publication timestamp, so the fixture does
not manufacture midnight UTC: authoritative first-known time remains unavailable.
No live issuer-IR adapter, random scraping, news source, social source, or historical
backfill is introduced.

## Persistence and deployment boundary

Migration 0018 adds append-only `research_event_disclosures` and
`research_event_lineage` tables plus a schema-state row. Relational columns reconcile
to the closed JSON records. SEC disclosures require a matching discovered accession
and issuer. First-known time must exactly match its source timestamp or remain null.
Stable replays are idempotent; differing content under an immutable identity fails.
The application role may select and insert but cannot update, delete, or truncate.
Backup/restore manifests and fresh-database Compose initialization include all three
tables.

This checkpoint is code-only. Migration 0018 has passed a disposable PostgreSQL 18
gate but is not applied to production, and the worker change is not deployed. The
remaining named-gate work includes the form-aware evidence budgeter, Focus Universe,
SEC deep-link validation, benchmark lab, measured adaptive routing/consolidation,
fingerprint cache, resource governor, metrics, and guarded integrated production
validation.

## Form-aware evidence-budget shadow checkpoint

The second gate slice adds receipt version `1.0.0` without switching the accepted
worker path. Each receipt binds the complete source hash, selected SEC document type,
normalized-visible-text hash, accepted-baseline hash and size, final selected hash and
size, exact ordered source offsets/window hashes, section kind, 8-K item where
available, selection reason, changed-section inputs, retained baseline terms, and any
later exact novelty-filter hashes. Estimated tokens are explicitly the four-characters-
per-token heuristic; actual prompt tokens remain unavailable until Ollama returns a
model receipt.

Selection is limited to the existing six-window/3,600-character envelope. Current
reports use closed supported 8-K items and only the exact primary form plus bounded
EX-99/EX-10 evidence from a complete submission. Periodic reports use explicit item
boundaries for MD&A, risk factors, controls, financial statements, legal proceedings,
defaults and unregistered equity sales. Table-of-contents hits, explicit no-change or
not-applicable sections, repeated forward-looking language, cover-page restatement
questions, certifications and generic EPS dilution definitions are handled by closed
rules. Non-target forms retain the accepted keyword baseline. Amendment/diff callers
may supply bounded deterministic changed-section names; no model chooses its evidence.

Three genuine production accessions were replayed against immutable SEC source hashes:

| Filing | Package | Evidence chars | Prompt tokens | Model seconds | Contract | Inspected facts |
| --- | --- | ---: | ---: | ---: | --- | ---: |
| McCormick 8-K `0000063754-26-000305` | accepted baseline | 545 | 1,392 | 79.03 | accepted / zero findings | 0/2 |
| McCormick 8-K | form-aware | 557 | 1,343 | 33.95 | accepted / zero findings | 2/2 |
| Target 10-Q `0000027419-26-000042` | accepted baseline | 3,253 | 2,055 | 114.73 | accepted / zero findings | 0/3 |
| Target 10-Q | form-aware | 3,081 | 2,027 | 79.35 | accepted / zero findings | 3/3 |
| Koss 10-K `0000056701-26-000034` | accepted baseline | 3,297 | 1,994 | 78.94 | accepted / zero findings | 0/3 |
| Koss 10-K | form-aware | 2,898 | 1,847 | 243.67 | rejected fail-closed | 3/3 |

The form-aware packages retained all nine manually inspected management, financial,
impairment, controls, acquisition and risk fragments and both inspected numeric
fragments. Total evidence characters fell from 7,095 to 6,536 and actual prompt tokens
from 5,441 to 5,217. This is a three-case engineering sample, the inspected fragments
are not an unbiased quality set, and the baseline ran first in each pair. It therefore
does not establish a causal latency improvement. All six calls were serialized on the
pinned Qwen digest with the unchanged prompt, schema, 4,096 context, 768 output cap and
300-second timeout; there were no timeouts and no findings in any accepted contract.

The Koss form-aware call produced non-verbatim citation/statement output after one
attempt. Deterministic validation rejected it; no repair, finding, brief or publication
was accepted. That result prevents a runtime switch from being inferred from the two
faster calls. The reproducible harness stores only bounded metrics under ignored local
data and explicitly marks all-connection-failure runs `INVALID_INFRASTRUCTURE`.
Production remains on `extract_research_excerpt()` until a later guarded gate reviews
broader shadow evidence; model, prompt, validator, Gemma-disabled state and concurrency
are unchanged.

## Focus Universe engineering checkpoint

The third gate slice adds private membership-event schema version `1.0.0` and queue
priority ruleset `1.0.0`. Each append-only transition retains canonical CIK, bounded
ticker/company identity, an `ADDED` or `REMOVED` action, a closed widely-followed,
user-interest or curated-review reason, effective and recorded UTC times, universe
version and an exact superseded-event link. Projection requires both effective and
recorded time to be available by the requested cutoff. Histories must begin with one
add, alternate actions, preserve issuer identity and form one non-branching chain;
ambiguous histories fail closed.

The existing `research_candidates` queue remains the only autonomous filing queue.
Its closed order is aged work at or beyond 24 hours, Focus plus an already-established
deterministic escalation, deterministic escalation, Focus, then ordinary work. Each
band is oldest-first with accession as the stable tie-breaker. The aged override is
global and oldest-first, so sustained Focus arrivals cannot starve an older non-Focus
issuer. Initial pending candidates usually have no deterministic Tier-0 result yet;
the material bands therefore apply only when that result already exists, such as a
bounded retry. No separate discovery, inference, publication, dossier, public route,
Discord channel or delivery path exists.

Migration 0019 adds the append-only membership history and a content-free telemetry
epoch. It seeds no company and rewrites no candidate or publication history. Exact
replay is idempotent; conflicting replay, branching, mutation and truncate fail. The
application role can only select and insert private history. Backup/restore and fresh
Compose coverage include both tables. A disposable PostgreSQL 18 gate proves
point-in-time add/removal projection, mutation denial and the exact one-queue priority
order. This remains an undeployed engineering checkpoint alongside migration 0018.

## Canonical SEC link validation checkpoint

Gate item 4 has a first fail-closed validation slice. An exact complete-submission URL
must reconcile to canonical CIK and accession and its bytes must reconcile to the
retained SHA-256. The primary HTML filename is selected only from the same filing
form's `<DOCUMENT>` block; paths, non-ASCII names, unsafe extensions and missing form
matches fail. The validator then retrieves the deterministic SEC archive-index and
primary-document URLs, rejects redirects, verifies that the index names the primary
document, retains both response hashes and emits one closed projection contract.

An inline-XBRL viewer URL is generated only when the validated primary HTML contains
the SEC-supported inline-XBRL namespace and the exact restricted viewer URL itself
returns a non-empty approved HTML response. Missing, blocked, redirected or provider-
unavailable viewers are omitted without erasing independently proven archive and
primary links. The general SEC transport still rejects arbitrary queries; its sole
query exception is the exact `/ixviewer/doc/action?doc=/Archives/edgar/data/...`
shape with validated numeric identity and a direct HTML filename.

The genuine NVIDIA accession `0001045810-26-000073` validated archive index hash
`62590b...1e99` and primary 8-K `nvda-20260826.htm` hash `84335b...d0ea` from complete-
submission hash `f35fe9...ff5fc`. The primary is inline-XBRL-marked, but the generated
viewer returned HTTP 404, so the truthful viewer result is `UNAVAILABLE`.

Migration 0020 persists the closed validation receipt under a deterministic identity
derived from accession, complete-submission hash and validation version. Exact replay
is idempotent; conflicting replay, mutation, identity/hash mismatch and cross-filing
URLs fail closed. Every future dossier insertion must reference the matching receipt,
and receipt validation must precede publication. Existing immutable dossiers are not
rewritten.

Website and Discord consumers receive a separate URL-only contract. It contains the
complete submission, archive index, primary document and optional validated inline-XBRL
viewer, but no hashes, prompt/model data, source text, exceptions, private human fields
or operations. Historical dossiers without a prospective receipt retain their existing
complete-submission link. The implementation and migration gates are locally complete;
item 4 remains undeployed until the named gate's guarded integrated production sequence.

## Isolated model-serving benchmark checkpoint

Gate item 5 freezes one ignored package set from the same hash-anchored McCormick 8-K,
Target 10-Q and Koss 10-K used by the form-aware evidence checkpoint. Every runtime
replayed the exact form-aware evidence hashes with the same analyst prompt, schema,
4,096-token context, 768-token output bound, deterministic seed, one attempt and
300-second timeout. The existing `AnalystPipeline` supplied all schema, verbatim-
evidence, numeric, cutoff and provenance gates; the lab adapter could neither repair
substance nor publish a result. Reports contain hashes and metrics but no prompt,
source text, response content or hidden reasoning.

The accepted Ollama 0.32.15/Qwen3 4B CPU path completed all three calls with two
accepted `insufficient_evidence`/zero-finding contracts and one fail-closed Koss
non-verbatim rejection. Wall latency was 76.104, 109.474 and 236.522 seconds; p50,
p90 and p95 were 109.474, 211.112 and 223.817 seconds. Prompt/generation rates were
21.89/5.10, 22.78/4.18 and 37.33/3.98 tokens per second. There were no timeouts, all
nine inspected input fragments remained present, swap did not grow, sampled public
routes stayed HTTP 200, and the observed CPU-package peak was 86°C.

The official digest-pinned llama.cpp `b10689` CPU server mounted the same Q4_K_M GGUF
blob and used exactly two inference/batch threads. All three calls spent the complete
window in reasoning without usable final JSON and recorded bounded `TimeoutError`
outcomes. The automated 106-sample trace observed 205.83% peak runtime CPU,
3,199,750,636 bytes peak runtime memory, no swap growth, and the CPU package reaching
its 100°C hardware threshold. All 106 concurrent public checks were HTTP 200 with
0.0277-second median and 0.0615-second maximum latency. That thermal result screened
out a higher-thread CPU run; safety is not traded for a faster timeout.

The official Vulkan image exposed only the Intel UHD 620 render device. The GeForce
940MX node exposed no Vulkan device inside the image and Docker has no NVIDIA runtime,
so CUDA/NVIDIA llama.cpp is not a genuinely supported container path. The three-case
ten-layer Intel Vulkan replay also timed out three times; its 146-sample trace peaked
at 167.77% CPU, 4,236,985,238 bytes runtime memory and 91°C, with 450,560 bytes of
swap growth. All 146 public checks stayed HTTP 200 at 0.0306-second median and
0.0646-second maximum latency. No host driver, system package or runtime was changed.
The previously measured Ollama 940MX path was also materially slower than CPU.
Production therefore remains on serialized,
CPU-only Ollama with the exact existing Qwen3 4B digest. Qwen3 8B was not downloaded,
Gemma remains disabled, and no provider, prompt, model, validator, concurrency,
deployment or publication setting changed. Detailed artifact provenance, limitations
and reproducible commands are in `docs/MODEL_SERVING_LAB.md`.

## Adaptive-compute decision checkpoint

Gate item 6 converts the accepted lab evidence into a closed decision rather than a
runtime switch. The decision is pinned to the ignored identical-package set hash, the
three measured Ollama/llama.cpp report hashes and the accepted Qwen3 4B digest. It
retains Ollama CPU, rejects the measured llama.cpp CPU/Vulkan paths, records Qwen3 8B
as not assessed, prohibits Gemma, and fixes one inference slot plus the existing
3,600-character, 4,096-context-token and 768-output-token ceilings.

The deterministic routing receipt is content-free and replay-stable. Its identity
binds accession, complete-source hash, bounded-evidence hash/size, the canonical
Tier-0 decision hash, closed complexity and importance reasons, policy version and
benchmark decision. A non-model Tier-0 result allocates no provider, model, evidence
profile or tokens. Normal model work retains the current bounded Ollama/Qwen3 4B path.
Complex or important work may produce only a richer-bounded Qwen3 4B *shadow* receipt;
it cannot execute that route or select an unmeasured larger model.

Contract validation rejects mixed provider/model/resource envelopes, mutated receipt
identity, unbound evidence size, duplicate complexity reasons and unsupported
importance lineage. Prompts, excerpts, hypotheses, model responses, hidden reasoning,
exceptions, Discord fields, human research and operations are absent. This checkpoint
adds no persistence, migration, worker wiring, model call, publication or production
configuration change. Item 7 must now compare the existing multi-role path with one
bounded consolidated response in shadow before any adoption decision.

## One-call analyst consolidation shadow checkpoint

Item 7 adds a closed shadow-only consolidated report over material facts, catalysts,
positive factors, negative factors, risks, contradictions and limitations. Each
section is projected through the accepted analyst-report validator, so evidence IDs,
verbatim quotations, reported facts and numbers, URLs, cutoff times, lexical grounding
and provenance are not relaxed. The contract permits one attempt, the accepted
4,096/768 token envelope and only the pinned Qwen3 4B model. It has no worker,
persistence, publication, Discord or routing integration.

The isolated lab replayed the three hash-anchored McCormick, Target and Koss packages
against both the current catalyst-plus-bull/bear/risk sequence and the consolidated
contract, alternating which mode ran first. Current/consolidated calls were 6/3 and
total elapsed time was 560.797/223.565 seconds (ratio 0.3987). The consolidated calls
all passed, while one current Koss role failed closed on non-verbatim quotation and
reported-fact output. Neither mode produced any validator-accepted findings, however,
so the substantive quality reference is absent and the quality non-regression gate is
false. The truthful decision is `insufficient_substantive_comparison`: retain the
accepted worker path and seek a later frozen set with validated substantive findings.
See `docs/ANALYST_CONSOLIDATION_LAB.md` for hashes and reproducible boundaries.

No source excerpt, prompt, response, hidden reasoning or private human research is in
the report. Production remained on schema 0017; the research worker was stopped only
for the serialized replay, restored healthy with zero restarts/OOM, and completed its
next cycle with zero unfinished analyst attempts. Item 8 may now implement a closed,
versioned event/evidence fingerprint-cache contract without activating gate runtime.

## Event/evidence fingerprint-cache checkpoint

Item 8 adds a content-free exact-reuse contract without enabling runtime caching. The
analysis fingerprint binds accession, complete-source hash, bounded evidence hash and
size, evidence-manifest hash, event-fingerprint manifest, Tier-0 decision, novelty,
evidence-budget and extraction rules, the accepted two-role prompt/output/validator
versions, pinned Ollama/Qwen3 4B digest, 4,096/768 token limits and one inference slot.
Only an already accepted two-report receipt with the exact same fingerprint can be a
reuse candidate, and a receipt validated after the current knowledge cutoff is rejected.
Because accession and source are part of the boundary, output is never reused across a
new filing even if selected text happens to match.

The companion filing-delta contract supports an explicit amendment relationship and an
explicit same-form successive 10-Q or 10-K relationship. Each source-bound manifest
hashes canonical section selectors, evidence hashes and sizes, source and accession
identity, UTC availability/retrieval times, and all novelty/budget/extraction versions.
Only added or modified current sections within 3,600 characters produce `DELTA_READY`.
Missing section manifests, removed relevant sections, changed rules or an oversized delta
produce `FULL_REANALYSIS`; unchanged selected evidence produces no delta and cannot reuse
the prior output because the filing/source cache boundary changed. New 8-Ks cannot claim
successive-periodic delta semantics; their event relationship remains governed by the
novelty lineage.

Focused validation is 18 passed. The full offline gate is 550 passed with 19 intentional
opt-in PostgreSQL skips; Ruff formatting/linting, strict mypy across 206 source files,
dependency, shell, production Compose and diff checks pass. Production remained healthy
and unchanged on schema 0017 during the checkpoint. This slice adds no migration,
persistence, worker integration, model call, publication, Discord delivery or public
route. Item 9 must now design and benchmark the conservative thermal/resource governor
before any runtime deferral policy is authorized.

## Thermal/resource governor shadow checkpoint

Item 9 adds an undeployed version `1.0.0` resource policy and replay-stable decision
receipt. Required observations are one-minute CPU load, CPU package temperature,
available RAM and swap use; recent inference p95/timeout samples and queue depth/age are
also bound. The initial observation establishes no swap-growth baseline and therefore
defers new inference. Missing required sensors likewise fail closed. A receipt UUID binds
the full observation, prior receipt and resulting action/reasons, so a decision cannot be
mutated while retaining its identity.

The declared defer thresholds are 90°C CPU package temperature, 0.90 one-minute load per
logical CPU, less than 4 GiB available RAM, at least 64 MiB swap growth, 270-second p95
latency or a 25% timeout rate with at least five samples. Recovery is deliberately more
conservative: below 82°C, below 0.70 load per CPU, at least 6 GiB available RAM, no new
swap-growth breach, below 240-second p95 and below the timeout threshold for three
consecutive observations. These values sit below the lab's rejected 91--100°C paths and
above the retained Ollama path's measured memory need; they are a shadow policy, not a
claim of production qualification.

Every decision keeps SEC discovery and durable persistence true, permits an already-active
single inference to finish, and admits at most one new call. Queue depth of 250 and age of
24 hours create advisories but never override a safety block. Fourteen focused tests cover
all sensor thresholds, initial/stale baselines, hysteresis recovery, active-call handling,
queue pressure, chronology and identity mutation. A 100,000-decision pure-policy benchmark
completed in 8.356085 seconds (11,967.33 decisions/second) on the development host; all six
declared safety/recovery checks and deterministic replay passed. This measures policy
overhead only, not model throughput or thermal improvement.

Full validation is 564 passed with 19 intentional opt-in PostgreSQL skips; Ruff,
formatting, strict mypy across 211 source files, dependency, shell, production Compose and
diff checks pass. No sensor probe, persistence, worker wiring, deployment, model setting,
queue mutation, publication, Discord or public route changed. Items 10 and 11 remain
explicit design deferrals; item 12 is the next implementation slice.

## Functional-radar and vector/vision deferral checkpoint

Items 10 and 11 are complete as explicit non-implementation decisions. A functional
event map is not authorized until novelty, evidence-strength, materiality/attention and
event-category inputs are accepted in guarded production and their visual semantics can
be defended without inventing a score. The current decorative radar remains explicitly
non-quantitative. Likewise, no measured filing-comparison problem has defeated the
deterministic event/section diff, XBRL or CompanyFacts paths, so ChromaDB/vector RAG and
multimodal vision remain out of scope. No package, model, data store, route or UI changed.
Item 12 freshness/performance measurement is the first incomplete gate item.

## Freshness/performance measurement checkpoint

Item 12 defines 20 closed engineering-quality metrics under version `1.0.0`.
Reference-labeled novelty measures retain raw numerators and denominators for
false-new publication rate, recap-suppression accuracy, material-update recall and
fresh-event precision. The same boundary covers Qwen calls per completed deep-analysis
filing, evidence characters, provider-reported input tokens, analyst latency/timeouts,
queue depth/age, CPU temperature/load, available RAM, swap use, publication and Discord
exact-once, and all three required disclosure/discovery/publication/alert latencies.
No metric is an investment-performance or market-alpha measure.

Ratio receipts preserve their source counts and a deterministic integer-millionths
projection. Distributions use exact non-negative samples and a documented nearest-rank
minimum/p50/p90/p95/maximum projection. Gauges are instantaneous. A window is explicitly
`available`, `partial` with its later telemetry epoch, or `unavailable` with a bounded
metric-compatible reason and no plausible zero value. Missing reference labels, actual
provider token counts or host sensors remain unavailable rather than being inferred.

Content-free filing latency receipts bind the autonomous accession, durable discovery,
optional event lineage, immutable publication and exact sent-delivery timestamps. A known
authoritative first-disclosure time requires its append-only lineage. Lineage may remain
present with an unknown first-known time; in that case every dependent latency is
unavailable. Missing publication or alert times are likewise explicit, and no negative or
guessed duration is accepted.

Migration 0021 adds a private immutable metric catalog, aggregate measurement receipts and
filing-latency receipts. Relational columns reconcile to a closed JSON record, extra fields
are rejected, NULL lifecycle keys cannot duplicate, and the application role has insert/
select but no mutation authority. Backup/restore and fresh-Compose manifests include all
four tables. The disposable PostgreSQL 18 gate applies migrations 0001--0021 and proves
catalog/hash agreement, shape enforcement, private-field rejection, UNKNOWN behavior,
append-only triggers and least privilege. This is an undeployed engineering checkpoint;
it contains definitions but no fabricated historical measurements or backfill.

## Guarded runtime activation

Migrations 0018--0021 and the accepted novelty/link/measurement worker code are live as
of 2026-08-31 UTC. Runtime measurement generation reads only prospective content-free
analyst attempts, terminal decisions, publications, sent deliveries, queue state and safe
host probes. It creates one complete 24-hour/168-hour set plus instantaneous gauges at
most hourly. Stable replay is exact and idempotent; a sub-hour cycle emits no new rows.
A measurement failure may degrade the current run but cannot rewrite publication or
delivery history.

The first genuine post-deployment cycle completed normally and created 34 receipts:
14 per aggregate window and six gauges. With no post-epoch terminal filing yet, 20
aggregate receipts truthfully report an incomplete telemetry epoch; eight reference
metrics report absent labels; five resource/queue gauges are available; and empty-queue
age is unavailable rather than zero. No filing-latency receipt was fabricated. The private
repository reconciles exactly 14/14/6 latest receipts, while the public operations route is
absent. Pre- and post-write backups passed checksums, structural validation, exact-count
network-isolated restores, and no prior filing, decision, dossier or delivery was changed.
The next normal worker poll completed at 19:02:43 UTC and retained exactly the original 34
rows at one measurement timestamp, proving the hourly production write boundary. Event,
Focus and validated-link tables still have no prospective filing observation; this remains
an explicit production-observation limitation, not a claimed successful event-path result.
