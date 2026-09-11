# Backtesting and self-evaluation

Phase 13 adds an offline, deterministic walk-forward evaluator. It measures recorded
historical research behavior; it does not simulate trade execution or make performance
promises.

## Point-in-time boundary

Each dataset separately records universe membership, an immutable historical
prediction snapshot, and its later outcome. Membership must have been available and
retrieved by the prediction cutoff. Outcome endpoints must be available only after the
declared horizon and by evaluation. Every original universe member must retain a
prediction and outcome row, including delisted and bankrupt securities. Unavailable
endpoints remain in the denominator.

Tuning, validation, and held-out partitions are chronological and non-overlapping.
The policy must be locked before the first held-out publication. Phase 13 does not tune
any rule: the partitions and 20-basis-point round-trip sensitivity were fixed before
held-out evaluation.

## Report semantics

For available outcomes, the descriptive net benchmark-relative result is `asset return
- benchmark return - round-trip cost assumption`. This is not a portfolio return and
assumes neither position sizing nor executable prices. Calibration rows show the
observed fraction of positive net relative outcomes for each ordinal signal label with
a 95% Wilson interval. Signal points remain heuristics, not probabilities.

## Reproduce the fixture report

The tracked fixture is wholly synthetic and contains six cases only. It exercises
safety properties and must never be presented as real-world performance.

```bash
.venv/bin/kalki-backtest data/fixtures/backtesting/phase13_synthetic.json \
  --output data/evaluations/phase13-synthetic-report.json
```

Identical input produces the same fingerprint, timestamp, cases, calibration, and
limitations. The CLI performs no network access and writes only the requested report.

## Known limitations

- No licensed real point-in-time history provider is approved, so real-world coverage
  is zero and no investment conclusion is possible.
- Six synthetic cases cannot estimate accuracy or economic value.
- Cost is a sensitivity assumption, not spread, slippage, impact, borrow, tax, or fill
  modeling.
- There is no exchange calendar or FX conversion.
- Outcome direction is descriptive and does not convert research into trading.
