# Market-Data Provider Boundary

> **Status:** Phase 5 completed on 2026-08-21 UTC with synthetic offline
> providers. Phase 37 adds a disabled private Twelve Data candidate for supporting
> forward outcomes. No live quote vendor, API key, account, accepted provider terms,
> or redistribution right is configured.

## Source decision

Official vendor material was reviewed before selecting an implementation:

- [Alpha Vantage documentation](https://www.alphavantage.co/documentation/) and
  [support](https://www.alphavantage.co/support/) require an API key, describe a
  free limit of 25 requests per day, and reserve real-time/delayed data for
  entitled premium use.
- [Nasdaq Data Link documentation](https://docs.data.nasdaq.com/) describes
  dataset-specific access and an account/API key for normal Python use; premium
  datasets require subscriptions.
- [TMX pricing and contract documents](https://www.tmxinfoservices.com/market-data/pricing-and-contract-documents)
  distinguish direct subscription from redistribution and publish separate
  agreements/pricing for Canadian market data.

No account or key was created and no vendor terms were accepted. A public research
site creates redistribution questions that cannot be answered merely because an
endpoint has a free tier. Unofficial or reverse-engineered endpoints were not
selected because their stability and permitted automated/public use are not clear
enough for this evidence-backed platform.

The approved zero-cost baseline is therefore a tracked, wholly synthetic offline
CSV/JSON provider. It tests the contract without creating false confidence that
Kalki has live prices. A live provider remains a replaceable later decision.

## Canonical contract

`MarketDataProvider` exposes three operations:

- instrument/reference lookup, including equity versus benchmark, symbol,
  exchange name, country, currency, exchange timezone, active dates, source hash,
  availability, and retrieval time;
- daily OHLCV series for an explicit date range, currency, price-adjustment basis,
  volume-adjustment basis, knowledge cutoff, and freshness limit; and
- split, cash-dividend, and symbol-change events with announcement, availability,
  retrieval, source, and effective-date metadata.

The same bar contract represents benchmark series, with `kind=benchmark`. This
avoids special arithmetic paths while keeping a benchmark distinguishable from a
tradable equity.

### Adjustment and currency rules

Every OHLC value in one series has exactly one declared price basis:

- `unadjusted`;
- `split_adjusted`; or
- `split_and_dividend_adjusted`.

Volume has a separate `unadjusted` or `split_adjusted` basis because cash
dividends can alter adjusted prices without altering share volume. Providers must
declare both supported sets. The request, every returned row, and the series
validator must agree. Raw and adjusted values cannot silently mix.

The requested currency must exactly match the instrument and every bar. Providers
do not perform hidden currency conversion. A later deterministic calculation may
convert currencies only with a separately sourced, timestamped FX rate and an
explicit formula.

### Time, freshness, and gaps

`knowledge_cutoff_at` is the point-in-time boundary. A row is eligible only when
both `available_at` and this system's `retrieved_at` are no later than the cutoff.
This is stricter than using publication time alone and prevents look-ahead.

Quality metadata always includes the evaluated cutoff, row count, actual coverage
start/end, latest availability, license reference, freshness state, and issues.
Old data is `stale`; an empty match is `no_data`; neither silently becomes a
plausible price. The provider does not infer missing trading sessions because a
future exchange-calendar component is required to distinguish holidays from gaps.

## Offline implementations and fixtures

`CsvFixtureMarketDataProvider` loads a closed manifest and exact-decimal CSV.
`MemoryMarketDataProvider` implements the same protocol from already validated
records. Shared contract tests run against both implementations, demonstrating
that consumers are not tied to the file format.

The synthetic fixture contains:

- one USD US equity;
- one CAD Canadian equity with raw and split-adjusted series;
- one USD benchmark;
- a synthetic cash dividend and split; and
- four synthetic daily sessions with distinct source hashes and UTC availability.

Every name, identifier, price, volume, event, and license label is invented for
tests. Nothing in the fixture is market evidence.

Example local use:

```python
from pathlib import Path

from kalki_market_intelligence.providers.market_data.offline import (
    CsvFixtureMarketDataProvider,
)

provider = CsvFixtureMarketDataProvider(Path("data/fixtures/market_data"))
print(provider.capabilities.model_dump())
```

## Cache and rate-limit behavior

Provider capabilities carry a count and period together for any vendor rate
limit. The offline provider declares both absent because it makes no requests. A
future live adapter must enforce its documented limit internally; a cache is not a
substitute for compliance.

`MemoryCachingMarketDataProvider` is an optional thread-safe, process-local
decorator with explicit positive TTL and maximum entry count. Cache keys include
the complete validated request, including knowledge cutoff and adjustment bases.
Expiry reloads from the underlying provider. It does not write market data to Git
or alter provenance/freshness metadata.

## Live-provider acceptance gate

Before enabling any live source, document and test:

- account/API-key and secret handling;
- exact US/Canadian, exchange, benchmark, action, and historical coverage;
- source versus consolidated data and delayed/end-of-day timing;
- adjustment formulas, corrections, delistings, symbol changes, and currencies;
- rate limits, quotas, retry rules, caching, bulk access, and availability times;
- automated use, local retention, derived-data, public display, redistribution,
  attribution, termination, and deletion rights; and
- zero-cost limits or explicit user approval for any spend/legal acceptance.

Until that gate passes, Phase 5 provides architecture and deterministic offline
test data, not operational market coverage.

## Phase 37 private outcome candidate

Phase 37 implements a separate replaceable Twelve Data adapter for private,
non-display T+1/T+5/T+20 supporting outcomes. It does not replace the canonical
Phase 5 provider or make prices public. The reviewed Basic tier requires a free
account, API key, and acceptance of binding terms, so it remains disabled pending an
account-holder decision. Its exact methodology, rights boundary, limits, schema, and
recovery procedure are documented in
[PHASE37_PROSPECTIVE_OUTCOMES.md](PHASE37_PROSPECTIVE_OUTCOMES.md).
