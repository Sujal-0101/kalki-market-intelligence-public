# Phase 37 — $0 prospective supporting outcomes

> **Implementation status:** The private adapter, exchange-session planner,
> deterministic evaluator, restart-safe PostgreSQL lifecycle, and disabled Compose
> profile are implemented. No Twelve Data account was created, no terms were
> accepted, no API key exists in the repository, and no live market observation has
> been retrieved. Provider activation remains an account-holder decision.

## Provider decision and rights boundary

The provider candidate is Twelve Data's Basic individual tier. Official material was
reviewed on 2026-08-28 UTC:

- [pricing](https://twelvedata.com/pricing) describes Basic as $0, 8 API credits per
  minute, 800 per day, and internal non-display use;
- the [terms dated 2026-01-01](https://twelvedata.com/terms) say creating an account
  or accessing the platform accepts a binding agreement, restrict free-tier data to
  non-commercial use, and require separate rights for redistribution or external
  display;
- the provider's [commercial/personal-use guidance](https://support.twelvedata.com/en/articles/5332349-commercial-and-personal-usage)
  says individual plans are for personal/internal use and do not permit redistribution
  or commercial third-party display;
- the [US equities guidance](https://support.twelvedata.com/en/articles/9935903-us-equities-market-data)
  says historical/end-of-day US data is available after midnight Eastern Time on the
  next trading day, while OTC data needs separate licensing; and
- the [API documentation](https://twelvedata.com/docs/introduction/overview) defines
  daily OHLCV, exchange MIC, `adjust=splits`, response metadata, and header-based API
  authentication.

Kalki therefore classifies this source as `SUPPORTING`, never primary evidence. Raw
bars and outcomes remain private. No public route reads these tables, and neither a
raw price nor a derived return may be displayed or redistributed without a later
rights review. The adapter covers only USD securities that Kalki can conservatively
map to Nasdaq, NYSE, NYSE Arca, or NYSE American plus the SPY benchmark. OTC and
Canadian listings are skipped. The provider's coverage and availability statements
are provider claims; Kalki has no live reliability sample yet.

This option has high replacement risk: the provider may change free-tier quotas,
coverage, terms, or exchange rights, and there is no free-tier SLA. The boundary is
replaceable, and stored rows name the provider, reviewed terms version, use mode,
response hashes, retrieval/availability times, and calculation version.

## Pre-registered methodology

For each immutable filing dossier and each horizon T+1, T+5, and T+20:

1. The first exchange close at or after the dossier's exact UTC publication time is
   the reference close. A publication even one second after a close moves to the next
   session.
2. T+N is N complete exchange sessions after that reference. The pinned
   `exchange-calendars` schedule handles weekends, holidays, early closes, and session
   timestamps; calendar days are not substituted.
3. The worker requests the asset and SPY reference/target daily bars no earlier than
   12 hours after the target close, matching the provider's stated next-day EOD
   availability boundary conservatively.
4. The deterministic Decimal calculation is `(target_close - reference_close) /
   reference_close`; benchmark-relative return is asset price return minus SPY price
   return. These are split-adjusted **price returns**, not total returns, forecasts,
   evidence, probabilities, or trading instructions.
5. Enrollment before the target close is `GENUINE_FORWARD`; enrollment at or after it
   is `RECONSTRUCTED`. The two origins are never merged silently.

Missing or mismatched symbols, MICs, currencies, sessions, rows, hashes, or timestamps
never become plausible prices. A bounded job may try at most six times. A permanent
or exhausted failure appends `data_unavailable` with no return. Attempts and terminal
outcomes commit atomically, so a process crash can re-claim the same unconsumed attempt
without creating a gap or duplicate immutable result.

The provider limiter serializes calls at 7.5-second spacing and enforces an in-process
rolling 800-call daily ceiling. The production profile uses at most eight jobs per
hour, or 384 calls in 24 hours including retry jobs, leaving headroom under the
documented free limit. A process restart resets only the local limiter history; the
conservative batch ceiling, durable attempts, provider enforcement, and operator
monitoring remain additional controls. This limitation must be reassessed before
activation.

## Database and recovery

Migration `0014_prospective_outcomes` adds:

- immutable publication/horizon/provider plans;
- mutable claim heads with bounded attempts and stale-lease recovery;
- immutable provider-attempt receipts; and
- immutable `SUPPORTING` outcomes containing the exact retained bars, raw and
  benchmark-relative returns, timestamps, hashes, status, origin, and versions.

The unique key is publication × horizon × provider. Database triggers reconcile
relational query fields with the closed JSON record, require every retained attempt,
and reject update/delete/truncate of immutable history. Backups and isolated restores
include all four tables.

Run the isolated gate without a provider account or network call:

```bash
./scripts/test-prospective-outcomes-postgres.sh
```

After a verified production backup and only when the code gate passes, apply the
forward, data-preserving schema with:

```bash
./scripts/migrate-prospective-outcomes.sh
```

There is no destructive down migration. Recovery uses a verified pre-migration backup
in a new database.

## Disabled activation boundary

The `supporting-outcomes` Compose profile is absent from normal production startup.
Activation would require the account holder to review and accept the current terms,
create a free Basic account, place its API key only in ignored
`secrets/twelve_data_api_key`, and explicitly approve starting the profile. Codex must
not perform those account/legal actions. Even after approval, first use requires a
private identity/availability/latency/quota check before historical backlog processing.

No paid upgrade, card, redistribution add-on, market-data display, public endpoint, or
automatic trading path is part of Phase 37.
