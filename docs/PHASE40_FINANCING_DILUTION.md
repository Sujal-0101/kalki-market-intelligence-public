# Phase 40 Financing and Dilution Intelligence

## Contract foundation

Phase 40 begins with closed primary-source contracts. Supported SEC metadata is
limited to S-1/S-1A, S-3/S-3A, 424B1/2/3/4/5/7, and financing 8-K/8-KA filings.
The initial instrument taxonomy distinguishes shelves, ATMs, public offerings,
PIPEs, convertibles, preferred equity, warrants, equity lines, and debt.

Amounts retain their explicit basis—maximum registered amount, gross proceeds, net
proceeds, principal, or commitment—and currency. Shares, price, conversion price,
exercise price, announcement, closing, maturity, and covenant text remain optional;
an absent value is UNKNOWN and is never calculated from prose. A shelf registration
is not a completed issuance, an ATM capacity is not proceeds already raised, and an
issuable-share count is not a dilution percentage without an authoritative share
denominator. Every term requires unique evidence identity and exact SEC source/hash/
acceptance/retrieval provenance.

## Primary-source inspection

The 2026-08-28 SEC master index was inspected on 2026-08-30 UTC for representative
current form families: Sunshine Biopharma S-1 `0001683168-26-006779`, SeeQC S-1/A
`0001213900-26-095175`, Adial Pharmaceuticals S-3 `0001213900-26-095122`, Live
Ventures S-3/A `0001437749-26-029163`, i-CABLE 424B3
`0001019155-26-000416`, Kazia Therapeutics 424B5 `0001213900-26-094600`, and
Sangamo Therapeutics 8-K `0001193125-26-374328`. These accessions establish public
shape/provenance references only; no uninspected amount or financing conclusion is
recorded from them.

## Bounded shelf and ATM evidence

The first parsing slice works only on normalized visible text from at most 8 MB of
primary SEC HTML. Script, style, SVG, noscript, legacy XBRL, and hidden inline-XBRL
header content are excluded. It selects at most 16 deterministic 720-character
windows and at most 8,000 characters in total. Each exact window retains normalized
text offsets, a text hash, a stable evidence UUID, a closed signal set, the source
byte hash, and the normalized-visible-text hash. The signals are candidate evidence,
not financing conclusions.

Two bounded excerpts copied from the inspected primary documents are committed as
fixtures. Their comments retain the accession, canonical SEC URL, inspection date,
and full retrieved-document hash while clearly labelling the fixture as incomplete.
The same extractor and term parser were also run locally against the complete
retrieved documents:

- Adial's S-3 is classified narrowly as a 25,148,970-share selling-stockholder
  resale registration with explicit `NONE_TO_ISSUER` proceeds status. It is not
  treated as a completed issuance, issuer offering, or proceeds event.
- Kazia's 424B5 is classified as an amended ATM program with an $80,000,000 maximum
  aggregate offering capacity and 510,000 previously sold ADSs carrying a reported
  aggregate sale price of $5,106,516. `AGGREGATE_SALE_PRICE` is a separate money
  basis and is not relabelled as gross or net issuer proceeds.

Ambiguous repeated numeric contexts fail closed, term evidence IDs must resolve to
the extraction bundle, and a `REPORTED` issuer-proceeds status requires an explicit
gross- or net-proceeds amount. The parser performs no dilution calculation and does
not infer an authoritative share denominator.

## Priced offerings and remaining instrument families

Six additional bounded fixtures were copied from complete primary SEC documents and
then checked against those complete documents, not only the excerpts:

- Wellchange Holdings 424B4 `0001213900-26-094944` retains a best-efforts offering
  of up to 50,000,000 Class A ordinary shares at a stated $0.15 per-share price. It
  does not turn an expected future closing into a completed sale or calculate
  proceeds.
- Madison Air Solutions 8-K `0001628280-26-058764` retains a priced PIPE for
  90,108,130 Class A shares at $24.97. The disclosed $2.25 billion gross proceeds
  remain explicitly `EXPECTED`, and the expected future closing is not recorded as
  completed.
- Mobix Labs 8-K `0001493152-26-040658` keeps a closed $1.2 million principal
  senior secured convertible note, its stated 10% annual rate and December 25, 2026
  maturity separate from a proposed 1,000-share convertible preferred sale with
  $1,000 reported gross proceeds. Its variable conversion formula remains UNKNOWN
  rather than being collapsed to an unsupported fixed price.
- Pluri 424B5 `0001213900-26-094704` retains the concurrent private-placement
  warrant's 2,228,940 issuable shares and $1.65 exercise price. It does not claim
  warrant exercise or cash receipt.
- Momentus 8-K `0001628280-26-058934` retains the historical $50 million equity-line
  commitment only with the filing's explicit `TERMINATED` disposition. It is not
  available capacity, and the filing says the line was never used.
- Valvoline 8-K `0001628280-26-058633` retains a closed $600 million principal
  offering of 6.125% senior notes and the exact August 15, 2034 maturity. A mismatch
  between the stated due year and exact maturity fails closed.
- Virtuix 8-K `0001213900-26-073449` retains an amendment from the previously
  reported $4.00 warrant exercise price to $3.00. It records no exercise, proceeds,
  or newly issued shares.
- AIM ImmunoTech 8-K `0001493152-26-021863` retains a proposed warrant-exercise
  inducement at $0.48 per existing warrant share, 17,439,856 issuable shares under
  new warrants at $0.60, and only conditional expected gross proceeds of $4.20
  million. It does not record a completed exercise or closing.

Reported, expected and estimated money statuses are separate closed values. Debt
interest is accepted only for debt or convertible-debt instruments. Complete-source
replays produce the same intended terms while repeated historical or generic
prospectus language does not create extra terms. No Qwen inference is involved.

## Persistence, lifecycle, and routing

Migration 0017 adds a bounded discovery queue plus immutable filing and Tier-0 routing
receipts. Discovery retains exact SEC daily-index URL/hash, all aligned index CIK/name
rows, form, filing date, and retrieval time. A multiple-issuer accession remains a
truthful metadata failure rather than selecting a lead issuer. Claims do not consume
an attempt until work completes, stale claims are recoverable, retries are bounded at
three, and valid filings with no exact supported grammar close separately as
`no_terms`. Completed jobs require their append-only receipt pair.

The private worker accepts at most 250 active jobs, processes two every 15 minutes,
and prioritizes priced offerings and prospectus supplements ahead of the much larger
structured-note and 8-K populations so one form cannot starve the phase's high-signal
families. It uses only official SEC metadata and exact primary HTML, shares the SEC
rate limiter, has no model or Discord/public network, and creates only a non-directional
model-free Tier-0 `RETAIN` receipt. Private Mission Control exposes aggregate queue,
form, context, failure, and receipt counts. Backup/restore manifests include all four
tables, while the application role cannot mutate immutable history.

Guarded production migration, activation, reconciliation, and genuine observation are
the remaining acceptance gate. Production thresholds, Qwen/Gemma, publication,
Discord, and public routes remain unchanged.

## Production acceptance

Phase 40 commit `af99943` is active on image
`sha256:a75a97a8fbd36e1eb13d90bde2342af3a228bc77037b4200e1ef05730d6335d9`.
Pre-migration backup `kalki-20260830T052222Z.dump` passed its isolated restore gate;
migration 0017 applied at 2026-08-30 05:22:44 UTC and its idempotent rerun passed.
Post-migration backup `kalki-20260830T052530Z.dump` contains the new queue and genuine
receipt pair and also passed checksum, exact-count, transient-state, and network-
isolated restore validation.

The first genuine cycle discovered 250 bounded jobs from official index
`master.20260828.idx` with SHA-256
`429ee9a12766933bdb248aae6724c347f427a81df73f70da44dbb1d7787d9db4`.
Wellchange 424B4 `0001213900-26-094944` completed on attempt one with the expected
full-source hash, 50,000,000 offered shares, $0.15 price, UNKNOWN proceeds, and one
model-free non-directional Tier-0 receipt. A co-registrant 424B5 remained a truthful
`metadata_unavailable` retry; no issuer was guessed. Current state is 248 pending,
one completed, one retry-wait, and zero no-terms/failed/processing rows.

Private Mission Control reconciled exactly to direct database aggregates. The worker
runs as UID/GID 10001 with a read-only filesystem, all capabilities dropped, no ports,
only database/research-egress networks, 53.8 MiB observed memory, and zero restarts.
Admin requires authentication locally; public `/research`, `/radar`, and `/screened`
remain 200 and public `/admin` remains 404. Qwen, Gemma, research publication,
Discord, and public exposure were unchanged. Phase 40 is accepted.
