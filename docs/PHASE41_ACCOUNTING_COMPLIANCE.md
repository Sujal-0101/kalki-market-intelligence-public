# Phase 41 — accounting, auditor, and compliance intelligence

> **Status:** Accepted in production. Deterministic contract/parser, model-free
> routing, append-only migration, private worker lifecycle, Mission Control projection,
> genuine retained/no-event behavior, and bounded terminal failure are live-validated.

## Accepted engineering slice

The first Phase 41 slice is model-free and accepts only bounded SEC primary-document
HTML for the following closed form set:

- 8-K and 8-K/A Items 3.01, 4.01, and 4.02;
- NT 10-K and NT 10-Q late-filing notices; and
- 10-K, 10-K/A, 10-Q, and 10-Q/A going-concern, internal-control, and material
  accounting-error language.

Literal signals are grouped into listing compliance, auditor change, non-reliance or
restatement, late filing, going concern, internal controls, and significant accounting
events. These are disclosure categories, not fraud findings, investment direction, or
model-generated conclusions. Routine “significant accounting policies” headings do not
create an event by themselves.

Each receipt retains canonical CIK/accession/form identity, the exact validated SEC
primary-document URL, source and normalized-visible-text hashes, SEC acceptance and UTC
retrieval times, bounded exact excerpts, offsets, excerpt hashes, stable evidence IDs,
and the parser version. Input is capped at 2 MB, evidence at 16 excerpts/900 characters
each/9,000 characters total, and active or non-visible markup is excluded. Empty,
oversized, unsafe-URL, invalid-version, identity-mismatched, or chronologically invalid
records fail closed.

## Prior-disclosure semantics

Comparison is closed to `NEW_DISCLOSURE`, `REPEATED_DISCLOSURE`,
`CHANGED_DISCLOSURE`, and `PRIOR_COMPARISON_UNAVAILABLE`. `NEW_DISCLOSURE` requires an
explicitly complete prior search. Only same-issuer, earlier-accepted records that were
already retrieved by the current retrieval time can participate, preventing a later-
retrieved document from leaking into an earlier decision. Exact fingerprints support
conservative repeated/change classification; the parser does not guess unsupported
historical lineage.

## Authoritative fixtures and validation

Complete official SEC documents are hash-anchored for genuine GeoVax Item 3.01, Groovy
Item 4.01, High Wire Item 4.02, Marwynn NT 10-K, TOP Financial NT 10-Q, Aqua Metals
10-Q, CS Diagnostics 10-K, and two successive Genprex Item 3.01 disclosures. The
Genprex pair proves a real changed listing-compliance disclosure. Aqua Metals retains
an exact going-concern event. CS Diagnostics retains going-concern and material-
weakness/control evidence while its explicit no-change control language does not
become a control-change event. Both periodic filings replay through aligned SEC
submissions metadata, exact primary-document acquisition, source hashing, parsing and
model-free routing inputs. Tests also cover hidden-content exclusion, unsupported 8-K
items, generic going-concern and routine-policy false positives, source URL and
chronology rejection, look-ahead prevention, evidence UUID/order reconciliation,
version closure, and the absence of prompt/model/reasoning/fraud fields.

The periodic-fixture checkpoint passes 26 focused tests and the full normal suite at
607 passed with 26 intentional opt-in PostgreSQL skips. The disposable PostgreSQL 18
accounting gate passes all three lifecycle cases across migrations 0001--0022. Ruff
format/lint, strict mypy across 224 source files, dependency consistency, shell,
production/Cloudflare Compose rendering, and Git diff checks pass.

## Deliberate limitations and next work

The follow-on routing prerequisite is implemented locally. A source-bound
`AccountingTier0Receipt` retains the exact event categories and evidence IDs with the
closed `accounting_compliance_context` reason. Its only permitted decision is Tier 0 /
retain / no model.

Migration 0022 adds a private bounded queue plus append-only filing/routing receipt
pairs. Claims do not consume attempts, stale claims recover, failures are closed to
five content-free categories and three attempts, and valid filings without supported
events terminate separately as `no_events`. Prospective absence never establishes a
new disclosure: the worker reads only earlier same-issuer receipts available at the
current retrieval time and keeps `prior_search_complete=false` until an authoritative
complete search exists. Private Mission Control exposes aggregate queue, form, event,
comparison, failure and receipt counts only.

The worker uses official SEC daily-index/submissions/primary-HTML acquisition on only
the database and research-egress networks. It has no model, analyst network, Discord,
publication, public connector, port, or public route. Focused validation is 53 passed;
the complete normal suite is 603 passed with 26 intentional opt-in PostgreSQL skips;
the dedicated PostgreSQL 18 gate passes three cases across migrations 0001--0022;
Ruff, formatting, strict mypy across 224 files, dependency, shell, Compose and diff
checks pass.

## Guarded production activation

Migration 0022 was applied at 2026-09-01 06:08:05 UTC only after backup
`kalki-20260901T060729Z.dump` passed checksum, archive inspection, exact-count and
network-disabled isolated restore. Its guarded rerun was a no-op, least-privilege
checks passed, and no historical accounting row was backfilled. Exact branch image
`sha256:bc174850...61c7f5` is 107,444,650 bytes, runs as UID/GID 10001, and passed a
networkless, read-only, capability-dropped package smoke. Only admin and the new
private accounting worker were recreated. The public and research-Qwen services
remain on their prior accepted image and were not interrupted.

The first four normal 15-minute cycles discovered 204 unique jobs from one genuine
daily-index hash and completed all eight NT 10-K jobs in one attempt each. Every
completion has one exact SEC primary-document receipt, one model-free Tier-0 retain
route and one `LATE_FILING` event. At 06:56 UTC, production reconciles eight completed,
196 pending, eight receipts, eight routes, no retry-wait, no failure and no duplicate
identity. Direct record scans find no prompt, response, reasoning, hypothesis, fraud,
score, secret or exception fields. The private Mission Control aggregate matches the
ledger, public research routes remain available, and public admin remains closed.

Post-write backup `kalki-20260901T061128Z.dump` passed the same checksum, archive,
exact-count and network-disabled isolated-restore gate. All accepted containers are
running; healthchecked services are healthy with zero restarts/OOM. The accounting
worker has no port, model network, analyst path, publication path or Discord path.
The first periodic cycle truthfully placed CytoDyn and Super Micro 10-K jobs in
`retry_wait` with the closed `parse_error` category and retry times exactly one hour
later. Read-only replay confirmed both genuine primary documents exceed the explicit
2 MB parser boundary; the other four queued 10-K primary documents are 0.25--1.29 MB
and parse within the accepted cap. The cap was not enlarged for throughput, no work
remained stuck processing, and neither failure was misrepresented as `no_events`.
Subsequent normal cycles completed four supported 10-Ks and six 10-Qs with exact
going-concern/internal-control evidence, while two 10-Qs and thirteen total periodic/
8-K jobs closed as genuine `no_events`. The two oversized 10-Ks retried on their exact
one-hour schedule and terminated at the third-attempt `failed` ceiling with
`parse_error`; neither created a receipt or masqueraded as `no_events`.

At the acceptance observation, the 204-job ledger contained 19 completed, 13
`no_events`, two failed, two metadata retries, 168 pending and zero processing jobs.
Nineteen receipts reconcile one-to-one with 19 model-free routes and 29 exact events;
there are no missing pairs, non-completed pairs, orphans, hash mismatches, duplicate
accessions/receipt IDs, or forbidden prompt/response/reasoning/private-operation keys.
Mission Control independently projects the same counts, including ten going-concern,
ten internal-control, eight late-filing and one listing-compliance event; comparison
history remains two changed, two repeated and 25 prior-unavailable. The worker has zero
restarts/OOM, uses 71.42 MiB of its 256 MiB limit, and retains only the private database
and SEC-egress networks. Public research routes remain HTTP 200 locally/externally;
public admin, health, docs, OpenAPI and operations remain 404. Phase 41 is accepted.
