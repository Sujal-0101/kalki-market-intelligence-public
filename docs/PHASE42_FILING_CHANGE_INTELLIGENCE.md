# Phase 42 — Filing-change and narrative intelligence

## Purpose

Phase 42 extends the earlier section-diff primitive into a closed, provenance-bound
comparison path for 10-K, 10-Q, amendments and supported prospectus forms. The path is
deterministic before any optional local-model interpretation. It cannot assert
materiality merely because text changed, and it cannot use a filing that was unavailable
at the comparison knowledge cutoff.

## First deterministic contract checkpoint

The initial `filing-change-sections-v1` contract accepts only explicit normalized
sections in eight categories: liquidity, risks, going concern, debt, issuance,
litigation, controls and outlook. Every section binds its canonical selector, heading,
category, exact normalized text and SHA-256. Each snapshot additionally binds canonical
CIK, accession, closed form, SEC source URL, source-document hash, filing/availability/
retrieval timestamps, extraction version and a deterministic manifest hash.

Comparisons require the same issuer, distinct accessions, no future retrieval, matching
extraction versions and one explicit admissible relationship:

- a non-amended filing followed by its same-family amendment;
- two successive non-amended 10-Ks or two successive non-amended 10-Qs; or
- two supported registration/prospectus forms.

The content-free delta lists every added, removed or modified selected section and both
source-side hashes/sizes. A deterministic package then selects at most six changes and
3,600 exact characters in the closed category order above. Modified sections preserve
exact before/after ranges around the first changed character; added and removed sections
retain the available side. Omitted changed selectors remain explicit. The complete
selection has a stable hash and UUID. No model, prompt, publication, route, persistence,
threshold or production behavior changes in this checkpoint.

## Remaining Phase 42 gates

- Deterministically extract and categorize relevant sections from complete official SEC
  10-K/Q, amendment and prospectus documents, excluding hidden metadata and exhibits
  unless the form contract explicitly admits them.
- Add hash-anchored genuine fixtures covering all eight categories, aliases, table-of-
  contents duplication, missing/removed sections, unchanged boilerplate and adversarial
  cross-issuer/time/form cases.
- Reconcile the new receipt with the existing amendment manifest/evidence budget rather
  than creating an independent inference path.
- Benchmark identical pre/post packages for characters, estimated and actual tokens when
  available, latency, timeout behavior and evidence/numeric fidelity.
- Keep optional Qwen interpretation disabled until deterministic fidelity and resource
  evidence justify it under the existing serialized 4,096-token boundary.

## Deterministic extraction checkpoint

The next local slice implements a bounded four-megabyte official-HTML parser without
changing any worker. It excludes scripts, styles, SVG, inline-XBRL headers, `hidden`,
`aria-hidden=true`, `display:none` and `visibility:hidden` content. Exact normalized
source offsets and hashes flow into the snapshot contract. Closed heading selectors
retain the first substantive occurrence after rejecting short/table-of-contents
candidates; distinct use-of-proceeds, dilution, securities, unregistered-sales, debt,
credit-facility, borrowing, controls/procedures and internal-control sections do not
collapse into one category record.

Hash-anchored complete official fixtures currently cover Aqua Metals 10-Q
`0001437749-26-025091`, CS Diagnostics 10-K `0001214659-26-004694`, and Wellchange
Holdings 424B4 `0001213900-26-094944`. The Wellchange source SHA-256
`33b4016a...ca39` exactly reconciles the already accepted production financing receipt.
Synthetic adversarial cases cover hidden content, table-of-contents duplication, all
prospectus categories, empty/oversized input and the extraction-to-snapshot-to-diff path.
The parser makes no materiality, outcome or closing inference.

## Genuine same-issuer fidelity checkpoint

The first complete real sequence uses four official Kazia Therapeutics prospectus
filings in SEC acceptance order:

- 424B5 `0001213900-26-094600`;
- 424B5 `0001213900-26-095303`;
- 424B3 `0001213900-26-095349`; and
- 424B3 `0001213900-26-095351`.

Their exact primary filenames, forms, filing dates, acceptance timestamps, byte sizes
and retained hashes were reconciled against both current SEC submissions metadata and
fresh primary-document fetches. The end-to-end path retains added, removed and modified
selectors, and distinguishes a later source-document change whose selected risk section
is byte-for-byte unchanged. Every selected excerpt is an exact source-side slice and the
closed package remains within the six-change/3,600-character boundary.

Phase 42 snapshots also project into the existing conservative amendment-delta manifest
under the accepted event-novelty, evidence-budget and extraction versions. Manifest
version 1.1 admits the full Phase 42 section-size boundary for comparison, but it does
not relax the 3,600-character delta ceiling: oversized changes and removed relevant
sections require full reanalysis, while unchanged selected evidence yields no delta.
This bridge remains shadow-only and does not authorize cached output, model use,
publication or any worker behavior.

## Identical-relationship model benchmark

The first isolated replay compares the accepted current-filing excerpt with the exact
two-source Phase 42 delta for Kazia's 424B5 expansion from accession
`0001213900-26-094600` to `0001213900-26-095303`. The ignored frozen package set has
SHA-256 `2ecdbcd8...aa5e`; it binds both complete source hashes, both snapshot manifests,
the selection receipt, exact evidence manifests and hashed inspected-fragment checks.
Loaded packages reject non-UTC chronology, wrong CIK/accession paths, source-hash drift,
duplicate strategies and changed required-fragment lineage.

The unchanged serialized Qwen3 4B two-role path produced these small-N results:

| Measure | Accepted current excerpt | Phase 42 delta |
|---|---:|---:|
| Model evidence characters | 3,342 | 2,421 |
| Estimated evidence tokens | 836 | 606 |
| Actual prompt tokens, two calls | 3,888 | 4,116 |
| Wall time | 405.601 s | 164.226 s |
| Accepted contracts | 1/2 | 2/2 |
| Timeouts | 0 | 0 |
| Validated findings/citations/numeric tokens | 0/0/0 | 0/0/0 |

Both inputs passed their exact manually inspected fragment checks. The accepted baseline's
second response was rejected as malformed JSON; the delta contracts were accepted but
contained no validated finding. Reduced evidence characters therefore did not reduce total
prompt tokens in this two-source representation, and there is no substantive reference for
semantic non-regression. The closed decision is
`insufficient_substantive_comparison`: Phase 42 remains deterministic-only and no worker,
prompt, model, context, validator, publication or notification behavior changes.

The content-free ignored report is
`data/benchmarks/filing-change-shadow-20260907T0845Z.json`, SHA-256
`54480a31...0258`. During the four calls, observed Ollama use was about 400--417% CPU and
3.1--3.5 GiB RAM, CPU package temperature was 76--90°C, and sampled public research
requests all returned HTTP 200 in 0.022--0.086 seconds. These are engineering observations
from one order-biased case, not model-quality, market-performance or causal speed evidence.

## Private append-only lifecycle checkpoint

Migration 0025 adds two private tables and no public projection. A filing-change snapshot
stores the validated closed record plus indexed accession, zero-padded CIK, form, distinct
filing/availability/retrieval times, official SEC URL, source and normalized-visible hashes,
section count, and contract versions. A selection stores the deterministic relationship,
both snapshot manifest keys, both accessions, selected character count, selection hash, and
the exact time at which both persisted sources were retrievable.

The application revalidates serialized model instances and recomputes the complete
selection from both snapshots before beginning one transaction. Exact replays are no-ops;
a stable identity with different content fails closed. Prior lookup requires both source
availability and retrieval at or before the requested UTC knowledge cutoff. Database
triggers reconcile relational columns to JSON, CIK/accession URL identity, same-issuer/time
ordering, and relationship/form families. Update, delete, and truncate are rejected; the
application role receives only select/insert. Bounded source excerpts remain private and
there is no worker, Qwen, cache-reuse, brief, Discord, or public-route integration in this
checkpoint.

Validate the complete fresh schema, pre-cutoff lookup, tamper rejection, idempotent replay,
and append-only grants with `scripts/test-filing-change-lifecycle-postgres.sh`. Apply
migration 0025 only after a verified backup with
`scripts/migrate-filing-change-lifecycle.sh`.

## Private persistence production acceptance

Migration 0025 is live through commit `d5c3f0d`. A fresh identified SEC replay of the two
Kazia 424B5 expansion sources matched both frozen hashes and stored two immutable snapshots
plus one 2,400-character selection. The same validated application replay was a no-op.
Both the schema-0024 pre-migration backup and post-write schema-0025 backup passed exact-
count, checksum and network-disabled isolated restore. The deployed image is
`sha256:7cf42600...4746d`; admin, public and research-worker remained healthy and the
public/private route boundary did not change. Existing 147 briefs and 147 sent deliveries
remain untouched. No model or public consumer uses these records.

## Deterministic lifecycle service

The next service-only slice validates the primary-document hash before bounded extraction,
rebuilds the closed snapshot, and queries prior snapshots only at the current retrieval
cutoff. It chooses the latest admissible same-issuer source, except that an explicit
amendment always prefers its matching non-amended base over a generic prospectus update.
Incompatible forms and future knowledge produce a closed snapshot-only result. A compatible
pair is recomputed and atomically stored, including a zero-character selection when all
selected sections are unchanged. This content-free result does not authorize Qwen, cache
reuse, publication, Discord or public rendering.

The service is live in exact image `sha256:3c2a5380...b816`. Fresh identified fetches of
the retained third and fourth Kazia sources reproduced their frozen hashes. The third
persisted the expected three removed issuance selectors and modified risk; the fourth
persisted no selected change. Production contains four unique snapshots and three unique,
non-orphaned selections, and the post-write backup passed isolated restore. This proof is
still operator-invoked; prospective integration will reuse primary HTML already acquired by
the private deterministic financing and accounting paths.

## Prospective deterministic sink checkpoint

The financing and accounting ingestion services now accept one typed observer after exact
primary URL and body-hash validation. Their existing private workers bind that observer to
the same append-only filing-change store already used by the lifecycle service. Eligible
sources therefore reuse the one primary HTML response already acquired by the parent job;
there is no second fetch or Phase 42 queue.

The observer is optional and form-closed. Unsupported 8-K, NT and 424B1 sources, documents
outside the four-megabyte Phase 42 parser boundary, and documents without a relevant closed
section produce no snapshot and do not relabel the parent filing. For an eligible bounded
source, identity, replay and database errors remain fail-closed and use the parent queue's
existing bounded retry path. The observer runs before financing `no_terms` or accounting
`no_events` closure, so those valid terminal classes are included when their filing contains
a comparable section. This integration adds no model, publication, Discord or public-view
consumer.

If a snapshot is already present for the same accession, a parent-job retry reuses the
first immutable source record rather than creating a second record from later retrieval
timestamps. Form, filing date, canonical URL and source hash must still agree exactly;
conflicting same-accession history fails closed. This keeps a persistence-success/parent-
completion-failure boundary restart-safe without rewriting the first observation.

Production inspection also found that the remaining financing backlog ordered older known
multi-issuer 424B2 rows ahead of 106 single-issuer rows in the same form family. Because the
worker deliberately refuses to guess among multiple issuers, those rows cannot reach a
primary fetch. Same-form claim ordering now prefers one exact index CIK before multi-issuer
sets, while preserving the accepted form priority and eventual bounded failure of ambiguous
rows. This is scheduling only; it neither resolves nor guesses an issuer.

## Prospective production acceptance

The restart-safe sink and queue-order fixes are pushed in commits `e991439` and `de7765b`.
Exact non-root image `sha256:e0cc7b68...caaa` passed its hardened offline smoke and was
deployed only to the financing and accounting workers at a verified zero-claim boundary.
Both remained healthy with zero restarts/OOM and no ingress. Their first natural production
cycle claimed two exact-single-issuer JPMorgan 424B2 filings ahead of the ambiguous backlog,
closed both as valid `no_terms`, and appended two filing-change snapshots from the same
already-fetched response bytes. The later source produced one 598-character deterministic
prospectus-update selection.

The complete private lifecycle now contains six unique accession/manifests and four
selections with zero duplicate accessions and zero orphan lineage. Existing briefs and sent
deliveries remain 147/147; public research remains available and restricted public routes
remain absent. Backup `kalki-20260907T143125Z.dump` passed checksum, exact-count,
transient-state and network-disabled isolated restore. No Qwen, cache authorization,
publication, Discord delivery or public projection consumed the records. This closes Phase
42's deterministic lifecycle gate; optional Qwen interpretation remains disabled because
the earlier identical-package benchmark did not establish substantive non-regression.
