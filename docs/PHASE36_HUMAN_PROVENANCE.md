# Phase 36 private human-research provenance

## Result boundary

Future private human results use the closed `human-research-v2` contract. A v2
record carries the human lead and disposition plus explicit receipts for:

- resolved ticker, canonical ten-digit CIK, company, form, accession, SEC archive
  URL, filing hash, excerpt hash, filing time, and retrieval time;
- CompanyFacts URL/hash/retrieval time and bounded normalized/same-filing counts;
- filing-diff status and bounded input/change identity;
- the complete deterministic forensic signals and Tier-0 decision;
- every completed content-free `AnalystAttemptReceipt` for the lead;
- deterministic numeric verification receipts, when numeric claims exist; and
- the private Discord results-channel target.

An unavailable input is represented by `UNRESOLVED`, `NOT_ASSESSED`, `UNAVAILABLE`,
or `FAILED`. It is not replaced by guessed identity, a fabricated receipt, an
empty success, or analyst prose. The analyst receipt contains sizes, hashes,
versions, validation status, and bounded failure categories, never prompts,
source text, raw output, or hidden reasoning.

## Immutable schema evolution

Migration `0012_human_result_provenance` adds nullable relational provenance
columns to `research_human_results`. The seven existing v1 rows are not updated;
their new columns remain SQL NULL, meaning historical lineage is UNKNOWN. A new
insert trigger requires all future rows to be v2, checks JSON/column identity,
requires accession identity only for resolved sources, and verifies every listed
analyst attempt is a completed human-origin receipt for the same lead.

The result remains append-only. The existing delivery head is created in the same
transaction and retains the linked channel, status, attempts, and eventual Discord
message ID. It may advance from pending to delivered/failed but cannot cause the
immutable result JSON to be rewritten. Human results and deliveries remain private
and are excluded from all public publication queries.

## Runtime flow

The worker resolves only an unambiguous tracked SEC filing or a validated SEC
archive pointer. After retrieval it records source hashes, performs bounded
excerpt extraction, deterministic forensics/Tier-0 routing, and a separately
contained CompanyFacts normalization. A CompanyFacts failure remains visible but
does not erase valid filing provenance. Qwen remains selective, serialized, and
bounded by the existing 300-second timeout. Completed attempt receipts are read
back from durable storage before the result can be inserted.

Filing diff is currently `NOT_ASSESSED` because the human path does not retrieve a
prior comparable filing. This is truthful provenance, not completion of the richer
Phase 42 comparison work. Numeric verification is `NOT_ASSESSED` when validated
analyst output contains no numeric claims.

## Verification and deployment

Offline tests cover complete and missing-lineage contracts, fail-closed mismatch
validation, content exclusion, Discord parsing, SEC/XBRL/Tier-0/analyst flow, and
migration wiring. The disposable PostgreSQL gate applies migrations 0001–0012,
persists and revalidates a v2 result, verifies its completed analyst-attempt link,
rejects mutation, and advances its private delivery exactly once. A separate
pre-0012 rehearsal proves a legacy v1 row remains unchanged with NULL v2 columns
and that a malformed future v1 insert is rejected.

Production deployment requires a fresh checksummed backup, isolated restore, the
guarded forward migration, a worker/intake image rollout, structural/privilege/
drift checks, and one future genuine human lead for final live validation. Existing
results must never be rewritten to simulate that evidence.
