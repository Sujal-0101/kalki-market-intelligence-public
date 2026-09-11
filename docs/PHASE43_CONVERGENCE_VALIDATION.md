# Phase 43 — convergence and adversarial validation

> **Status:** Accepted in production. Deterministic contracts, fact adapters, append-only
> persistence, source-specific producer eligibility, the first genuine prospective
> receipt, and private aggregate reporting are validated. No public/model consumer exists.

## Current slice

The first Phase 43 boundary evaluates one narrowly stated Boolean claim against a
small set of exact numeric facts. It supports three closed families:

- liquidity: cash at least current liabilities;
- dilution: observed share growth or explicit potentially issuable instruments; and
- insider activity: executed acquired shares exceed executed disposed shares.

Every claim and fact retains canonical issuer CIK, comparison scope, as-of date,
availability and retrieval times, source-record identity, source SHA-256, and bounded evidence IDs.
The result is a recomputable, content-free receipt with a stable UUID and SHA-256
under one closed rule version. Reordering inputs cannot change the receipt.

Outcomes are exactly `SUPPORTED`, `CONFLICTED`, `INSUFFICIENT`, or
`NOT_APPLICABLE`. Missing facts and incomparable periods are never converted to a
safe or neutral result. A Form 144 planned-sale notice is not an executed insider
transaction and therefore yields `NOT_APPLICABLE` when it is the only insider fact.

## Conservative semantics

A positive registration share count alone does not prove issuer dilution. It may
represent already-issued selling-holder shares or unused capacity. Positive
potentially issuable shares, a positive closed dilutive-instrument count, or an
actual increase between ordered outstanding-share observations can support the
positive predicate. A negative dilution conclusion additionally requires a closed
zero-instrument count; unchanged shares or zero registration alone remain
`INSUFFICIENT`.

Liquidity facts must share a comparison scope, reporting date and currency. Executed
insider totals must share an as-of date. Cross-issuer facts, future/unavailable facts, duplicate
fact kinds or identities, non-finite values, conflicting source-record lineage, and
an evidence ID reused for different sources fail validation.

## Boundaries and next work

Pure adapters now accept only already-validated inputs. Liquidity and outstanding-share
facts require the caller to supply explicit point-in-time source metadata and evidence
IDs. Financing receipts emit only positive active instrument exposure with explicit
issuable shares; resale registrations, terminated terms, unknown status and absence emit
no negative conclusion. Section 16 totals are bounded to one exact transaction date and
derivative class. Schedule 13 records emit no insider-transaction fact, while Form 144
emits only its planned-sale fact. Adapter-derived fact IDs are replay stable.

Migration `0026_contradiction_receipts` adds one private append-only table. Its indexed
columns mirror the receipt and claim identities, issuer, family/predicate, assertion,
scope, claim time, knowledge cutoff, disposition/reason, fact counts, content hash and
rule version. PostgreSQL independently checks the closed JSON key sets, relational/JSON
agreement, family/predicate and disposition/reason combinations, fact identity
uniqueness, consumed-fact references, issuer/scope agreement and point-in-time
chronology. The application revalidates and recomputes a receipt before insertion;
exact replay is a no-op and conflicting content fails closed. Private reads require an
explicit UTC knowledge cutoff.

The migration and store do not read production records, alter Tier-0 or Qwen behavior,
publish a dossier, deliver Discord, or add a route. They do not assign market direction
or calculate financial metrics. The backup manifest now covers both filing-change and
contradiction tables; restore remains compatible with older schema-0025 manifests that
predate those exact-count entries. The migration is live and empty after guarded
activation.

A bounded private service now requires every claim and supplied fact to carry the closed
`VALIDATED` input status and labels the fact set as required-complete, partial-validated,
or not-applicable context. The deterministic evaluator remains authoritative: if the
caller's completeness label disagrees with the computed disposition, nothing is written.
The service is locally validated but has no deployed producer integration yet.

The first producer policy is versioned as `convergence-producers-v1`. It creates no
new fetch or queue. Same-filing CompanyFacts liquidity is eligible only when the latest
available reporting period has one exact USD instant cash fact and one exact current-
liabilities fact; duplicate tags or contexts fail as ambiguous. Financing is eligible
only for a revalidated active potentially dilutive instrument with explicit issuable
shares; resale registration and parser absence produce no request. Ownership is limited
to one exact Section 16 transaction-date/derivative scope, while Form 144 is retained
only as not-applicable planned-sale context and Schedules 13D/G produce no transaction
request.

Each producer-generated claim is a content-free deterministic policy assertion bound to
the separately revalidated routing or XBRL-selection manifest. Its numeric facts retain
the primary receipt/CompanyFacts lineage. Claim and fact record/hash pairs and evidence
identities must remain distinct. Eligible requests pass through the existing recomputing
service before append-only persistence; ineligible decisions write nothing. Private
integration is deployed privately in the existing research, financing, and ownership
workers, but it changes no model, publication, Discord, or public behavior. Its first
natural cycles contained no eligible source and correctly retained no receipt. A later
genuine Form 4 cycle produced the first eligible Section 16 request.

Private Mission Control has a bounded lifetime aggregate over the append-only ledger. It
reports only the observation time, total count, closed family/disposition counts, and
closed producer-source counts. Source classification requires both an exact producer claim
identifier shape and the matching family; unrecognized provenance is counted as `UNKNOWN`.
The projection cannot carry receipt JSON, issuer identity, claim/fact/evidence IDs, values,
hashes, excerpts, model content, private-human content, or internal errors. It is registered
only in the authenticated admin application; the public process has no route or query.

## Production acceptance

Form 4 accession `0001193125-26-383655` completed its existing ownership job on attempt
one with no error. Its immutable filing and model-free routing records revalidated, its
issuer and source lineage matched, and the producer reconstructed the same claim and two
executed-transaction facts. Deterministic recomputation returned the exact stored
`INSIDER` / `CONFLICTED` receipt, and an application replay returned the same immutable row
without changing the one-row ledger. No interpretation, market direction, publication,
Discord delivery, or public output was created.

The private projection reconciled exactly to one family (`INSIDER`), one disposition
(`CONFLICTED`), and one source (`OWNERSHIP_SECTION_16`). The exact admin image is
`sha256:8f44e31707af37f191f220897c902bc0623a9988036d90a7a70925a832eec6fa`.
It runs non-root and read-only with all Linux capabilities dropped and
`no-new-privileges`; only the loopback admin service was recreated. This activation found
and fixed a pre-existing Compose gap where admin lacked the capability-drop setting.
Public research remained HTTP 200 and public admin remained 404 locally and externally.
Post-write backup `kalki-20260908T000722Z.dump` passed checksum, exact-count, transient-
state and network-disabled isolated restore.
