# Phase 14 optimization and provider review

> **Measured:** 2026-08-25 UTC. Numbers are local engineering measurements, not
> market-performance results.

## Profile and decisions

The full 230-test Phase 13 suite took 2.11 seconds wall time with 166,748 KiB peak
resident memory. One hundred complete six-case synthetic backtest reports took 0.30
seconds and 35,664 KiB peak resident memory. Neither was a meaningful bottleneck, so
the evaluator, calculation engine, model boundary, and test layout were not changed.

Two measured bottlenecks justified work:

| Path | Controlled baseline | Optimized | Result |
|---|---:|---:|---:|
| Three independent cached provider calls, each with 20 ms fixture delay | 61.9 ms median | 21.5 ms median | about 2.9× faster |
| PostgreSQL latest-100 publication query over 50,000 synthetic rows | 21.203 ms | 0.188 ms | about 113× faster |

The cache previously held a global mutex during provider I/O. It now releases the
mutex while loading unrelated keys but retains per-key single-flight behavior, so
concurrent misses for one key still make one provider call. Expired entries are purged
before a live entry is evicted. Concurrency and duplicate-call behavior have tests.

The publication query previously performed a sequential scan and top-N sort. Migration
0003 adds an index matching `(published_at DESC, prediction_id DESC)`. Public API pages
default to 100 records and accept bounded `limit` (1–500) and `offset` (0–100,000).
HTML pages use 50 records with accessible newer/older links. The index migration and
rollback were both exercised before production application.

Reproduce the dependency-free offline microbenchmark with:

```bash
.venv/bin/python scripts/benchmark-phase14.py
```

The PostgreSQL comparison used a disposable PostgreSQL 18 container, production
migrations, 50,000 constraint-valid synthetic table rows, `ANALYZE`, and `EXPLAIN
(ANALYZE, BUFFERS)` on the exact bounded ordering query. The disposable data contained
no real research and was removed.

## Migration and rollback

A fresh checksummed backup is required before live migration. The idempotent runner
uses the local PostgreSQL socket inside the container and never reads or prints a
password:

```bash
./scripts/backup-postgres.sh
./scripts/migrate-postgres.sh up
./scripts/migrate-postgres.sh down  # rollback only if the index causes a regression
```

Rollback removes only the performance index and its migration marker; it does not
delete research, outcomes, audits, sessions, or provider data. Fresh databases apply
0003 in order through Compose.

## Optional provider review

No additional provider was activated, no account was created, and no credentials or
payment details were entered.

- **Massive Stocks Basic:** the official pricing page advertises $0/month, five calls
  per minute, two years of end-of-day history, reference data, and corporate actions.
  Its official market-data terms restrict the individual service to personal,
  non-business use and prohibit public distribution and derived works without consent.
  That conflicts with Kalki's public research surface, so it remains disabled.
  Sources: [pricing](https://massive.com/pricing?product=stocks), [market-data
  terms](https://massive.com/legal/market-data-terms-of-service).
- **Twelve Data Basic:** the official pricing page advertises a free individual tier,
  but describes it as personal, internal, non-commercial and internal non-display use;
  the provider also distinguishes public display/redistribution licensing. It requires
  an account-side terms decision and does not clearly authorize Kalki's public derived
  research on the individual tier, so it remains disabled. Sources: [pricing](https://twelvedata.com/pricing),
  [usage guidance](https://support.twelvedata.com/en/articles/5332349-commercial-and-personal-usage).
- **Alpha Vantage:** the official support page offers a free key with 25 requests per
  day, but obtaining it requires an email/account and acceptance of terms. The official
  terms grant personal, non-commercial use unless otherwise agreed, while commercial
  use requires separate onboarding. This does not satisfy autonomous activation rules,
  so it remains disabled. Sources: [support](https://www.alphavantage.co/support/),
  [terms](https://www.alphavantage.co/terms_of_service/).
- **Stooq/unofficial endpoints:** no sufficiently clear official API contract and public
  redistribution grant was found. No scraper or reverse-engineered adapter was built.

The existing synthetic offline provider remains the only approved market-data
implementation. Provider abstraction, point-in-time timestamps, quality/freshness,
currency, adjustment, and provenance contracts are unchanged.

## Operating limits and remaining bottlenecks

- Public API page size: default 100, maximum 500; maximum offset 100,000.
- HTML page size: 50; maximum page 2,001.
- Market cache: default 1,024 entries and 60-second TTL; process-local only.
- PostgreSQL application statements retain the five-second timeout and two-second lock
  timeout.
- Ollama remains CPU-only, one concurrent request, and by far the slowest optional
  operation (Phase 7 measured 112.83 seconds median). No model optimization was made
  because changing quantization/model/prompt could weaken validated output quality.
- Live SEC access still returns 403 in this environment; retrying or bypassing controls
  is not an optimization.
