# Phase 39 Insider and Ownership Intelligence

## Scope and authority

Phase 39 uses SEC primary filing documents as authoritative evidence for insider
and beneficial-ownership disclosures. The supported closed form set is:

- Forms 3, 3/A, 4, 4/A, 5, and 5/A;
- Forms 144 and 144/A; and
- Schedules 13D, 13D/A, 13G, and 13G/A, including legacy `SC 13*` metadata names
  when the primary document uses the supported structured XML schema.

The implementation does not infer trading intent from a reporting person's
identity. It does not treat a sale as bearish, and it keeps a Form 144 planned-sale
notice separate from a completed Section 16 transaction. Unstructured legacy
Schedule documents are not guessed into the structured contract.

## Acquisition and provenance

`SecClient.fetch_primary_document` accepts only a validated CIK, accession number,
and safe primary-document filename already obtained from SEC submissions metadata.
It derives the exact HTTPS Archives path, caps the decoded response at 2 MB, accepts
only XML/plain SEC media types, rejects redirects, and retains the response URL,
retrieval time, and SHA-256. `SecOwnershipIngestionService` then rejects any issuer,
form, URL, accession, or content-hash disagreement between metadata and parsed XML.
When submissions identifies a rendered ownership document as a one-level
`xslF…/name.xml` path, the ownership metadata adapter deterministically selects only
the same basename from the accession directory; other nested paths are not rewritten.
This preserves raw XML rather than accepting rendered HTML.

The parser rejects empty/oversized XML, DTD/entity declarations, malformed XML,
unsupported forms, invalid numbers/dates/booleans, and contract inconsistencies.
Acceptance and retrieval timestamps are UTC-normalized and retrieval cannot precede
SEC acceptance.

Representative public primary documents were inspected from SEC Archives on
2026-08-29 UTC. Test excerpts preserve the observed schema and selected public
values, with accession and retrieval date recorded alongside each excerpt:

- Form 3 `0001069878-26-000077`, `form3.xml`;
- Form 4 `0001437749-26-029167`, `rdgdoc.xml`;
- Form 5 `0001213900-26-090411`, `ownership.xml`;
- Form 144 `0001950047-26-008827`, `primary_doc.xml`;
- Schedule 13D `0001104659-26-063172`;
- Schedule 13D/A `0001398344-26-006235`;
- Schedule 13G `0002100119-26-000625`; and
- Schedule 13G/A `0000919574-26-003332`.

No private research, credentials, fabricated records, or reconstructed market data
are used.

## Closed receipt semantics

The immutable receipt retains issuer identity, form, event period, reporting owners
and roles, Section 16 holdings and transactions, transaction code/date/shares/price,
acquired/disposed direction, post-transaction shares, direct/indirect ownership,
derivative status, late-report status, Form 144 notice details, beneficial owners,
voting/dispositive powers, percentage of class, amendment metadata, exact disclosed
Item 4 purpose text, source URL/hash/timestamps, and parser version.

Section 16 XML generally does not provide the outstanding-share denominator needed
for a post-transaction percentage. The percentage therefore remains explicitly
`UNKNOWN` unless a future authoritative input supports a reported or deterministic
calculated value. It is never derived from unrelated or later CompanyFacts data.

For Schedule 13D, the receipt distinguishes exact disclosed Item 4 text that still
requires review from an unavailable intent assessment. For Schedule 13G and all
non-Schedule forms, activist/control-intent assessment is `NOT_APPLICABLE`. Presence
of Item 4 text does not itself assert that a holder is an activist or seeks control.

## Conservative Tier-0 routing

The ownership routing receipt is deterministic and model-free for ordinary events:

- Section 16 disclosures are retained as non-directional context;
- Form 144 is retained specifically as a planned-sale notice; and
- Schedule 13D/G ownership rows without explicit review material are retained as
  beneficial-ownership context.

Exact Schedule 13D Item 4 text or an observed 13G-to-13D / 13D-to-13G transition can
route to the existing bounded Tier-2 review. The transition classifier requires the
previous primary-source form; it does not infer history. No threshold, publication
gate, Qwen configuration, Gemma state, or evidence validator is changed.

## Durable discovery and processing boundary

Migrations 0015–0016 add a separate `research_ownership_jobs` queue plus immutable
filing and routing ledgers. Daily-index candidates never enter `research_candidates`, so a
high-volume Form 4 day cannot consume deep-analysis/Qwen queue capacity. The private
ownership worker admits at most 250 active jobs, processes at most two per 15-minute
cycle, permits three attempts, and reclaims abandoned 30-minute leases. SEC/provider
failure details are reduced to a closed private category; no filing text, prompt,
model output, exception message, private human research, or secret enters the queue.

Each successful job resolves its accession against current SEC submissions metadata,
fetches the exact named primary document, parses and routes it deterministically, and
atomically appends both immutable records before the job may become completed. The
database reconciles relational columns to the closed JSON and requires job/receipt
accession, issuer, form, and source hash agreement. Idempotent exact replay is a no-op;
conflicting replay fails closed. Terminal jobs and all filing/routing receipts reject
mutation or deletion.

The SEC daily index repeats an ownership accession for the issuer and its reporting
owners. Discovery groups those rows by accession and retains the sorted, bounded CIK
and name set rather than guessing which row is the issuer. Processing tries only that
closed set and records the issuer identity only when submissions metadata and the
primary document agree. Migration 0016 was added forward after this genuine behavior
was observed; migration 0015 remains unchanged.

A Schedule 13D/13G transition requires earlier retained primary-source history for
the same issuer and the same exact reporting-owner identity set. Another holder's
filing for the issuer cannot create a transition. A reclaimed process lease does not
consume one of the three work attempts until a bounded success or failure is recorded.

The worker uses only the private database and existing SEC egress networks. It has no
Ollama, analyst, Discord, admin, public-connector, or published-port access. Ordinary
ownership context remains model-free; an exact 13D purpose or proven 13D/13G transition
is only marked for a future bounded review and does not bypass an existing research or
publication gate. Private Mission Control reports queue state, immutable receipts,
forms, closed failures, model-free retention, bounded-review routing, and backlog age.

## Production acceptance and limitations

Migrations 0015–0016 and the private worker are deployed. The first corrected cycle
retained two genuine future AVNET Form 4 receipts with resolved issuer identity and
model-free Tier-0 routing; direct database and Mission Control counts reconcile, and
the post-data backup passed isolated exact-count restore. Earlier expected failures
remain in immutable retry history rather than being hidden or relabelled.

Production proof currently covers genuine Form 4 processing; the other supported
families are covered by inspected primary-source fixtures and will accumulate only
through future bounded cycles. An ownership receipt is not itself a dossier,
directional market signal, forecast, trade instruction, or public record. Bounded
review routes remain private and do not bypass the established evidence and
publication pipeline.
