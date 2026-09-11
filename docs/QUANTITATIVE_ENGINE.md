# Deterministic Quantitative Engine

> **Status:** Phase 6 completed on 2026-08-21 UTC. The engine is a tested local
> calculation library over validated inputs. It does not fetch live data, rank
> securities, generate research conclusions, or execute trades.

## Design and source references

Every calculation uses ordinary Python code and `Decimal`; no model or prompt is
in the arithmetic path. A fixed 34-significant-digit, round-half-even context
makes results independent of a caller's process-wide Decimal settings. The
implementation version is `1.0.0` and every result records parameters, UTC
knowledge cutoff, effective date, units, currency where applicable, and every
consumed source row/value/hash.

The formulas and input semantics were checked against these primary or official
references:

- [TA-Lib's official function documentation](https://ta-lib.org/functions/),
  including its [RSI formula](https://ta-lib.org/functions/rsi.html), for standard
  technical-indicator definitions and Wilder smoothing;
- [NIST's sample standard-deviation formula](https://www.itl.nist.gov/div898/handbook/eda/section3/eda356.htm)
  for the `n-1` dispersion calculation;
- [SEC EDGAR API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
  for the period and unit distinctions present in company facts; and
- [Python's `Decimal` documentation](https://docs.python.org/3/library/decimal.html)
  for deterministic decimal arithmetic and square roots.

These references do not make the synthetic fixture market evidence. They define
calculation behavior; the project fixture remains invented and hand-checkable.

## Implemented formulas

Price calculations require one consistent split-adjusted (or split-and-dividend-
adjusted) series. Volume calculations requiring comparisons use split-adjusted
volume. Results are not silently converted between currencies.

| Metric | Version 1 formula or convention |
|---|---|
| Cumulative price return | `last_close / first_close - 1`; dividends are not inferred |
| SMA | arithmetic mean of each complete trailing window |
| EMA | `alpha = 2/(period+1)`, seeded with the first complete SMA |
| RSI | Wilder gain/loss averages, SMA seed, then `1/period` smoothing; flat series is 50 |
| MACD | fast EMA minus slow EMA; the signal is an EMA of that line; all EMAs use the documented seed |
| True range / ATR | maximum of intraday range and prior-close gaps; ATR uses Wilder smoothing and excludes the first no-prior-close range from its seed |
| Historical volatility | sample standard deviation of simple close returns times `sqrt(periods_per_year)` |
| Relative volume | latest volume divided by the mean of the preceding comparison window |
| 52-week position | `(latest - window_low) / (window_high - window_low)`; default window is 252 sessions |
| Maximum drawdown | worst `close / prior_peak - 1` in the supplied window |
| Benchmark-relative return | asset cumulative price return minus benchmark cumulative price return on matched sessions |
| Beta | covariance sum of matched simple returns divided by benchmark variance sum |

The first fundamental and valuation formulas are current assets/current
liabilities, debt/equity, gross/operating/net margins, return on average beginning
and ending equity, period growth, CAGR, aggregate P/E (market capitalization/net
income), aggregate P/S, and enterprise value/EBITDA. Inputs must share an issuer,
compatible periods, units, and currencies. Valuation denominators and other
economically required denominators must be positive. CAGR's declared whole-year
count must match the fact end dates.

## Temporal and data-quality gates

A calculation fails rather than guesses when:

- a bar series is stale, empty, too short, or uses an unsafe adjustment basis;
- benchmark sessions, currencies, adjustment bases, or knowledge cutoffs differ;
- a required denominator or comparison range is zero;
- a financial fact has the wrong issuer, period kind/range, unit, or currency;
- a source row was unavailable or had not actually been retrieved by the UTC
  knowledge cutoff; or
- a financial period ends after that cutoff.

Each `MetricResult` is immutable and schema-closed. Its `CalculationInput` entries
retain the subject, source record/hash, exact consumed values, unit/currency,
adjustment bases, effective period, availability time, and retrieval time. This is
calculation lineage, not a confidence score.

## Reference cases and tolerance

`data/fixtures/quantitative/reference-cases.json` contains small synthetic series
with exact expected values. Repeating decimal paths use an absolute assertion
tolerance of `1e-24`; exact cases remain exact. Tests also change the caller's
Decimal precision to prove the engine's results do not change.

## Current limitations

- There is no live market-data provider, production fact-selection policy, FX
  conversion, exchange calendar, persistence layer, scheduler, or user interface.
- The engine counts supplied sessions; it cannot yet distinguish a holiday from a
  missing trading day. Providers must make gaps explicit until a calendar exists.
- Cumulative and benchmark returns are price returns. Total return requires a
  declared split-and-dividend-adjusted series; dividends are never invented.
- Financial inputs are validated contracts, but automated selection among amended,
  duplicated, dimensional, or differently framed SEC facts remains future work.
- These metrics are research inputs, not recommendations, promises, probabilities,
  or trading instructions.
