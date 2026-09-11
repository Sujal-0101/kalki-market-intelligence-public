# Predictions and Outcome Tracking

> **Status:** Phase 9 is complete. Its Python checks and isolated PostgreSQL
> migration/mutation gate pass.

## Immutable publication boundary

A `PredictionRecord` is an immutable snapshot of the declared thesis, subject,
instrument and benchmark, 30–180 day horizon, evaluation rule, label, separate
scores, complete Phase 8 signal, evidence known by the UTC cutoff, input hashes,
and calculation/prompt/model/ruleset versions. Validators require the duplicated
scores, labels, fingerprint, scope, evidence IDs, and input hashes to match that
signal exactly.

Publication never edits a prior record. Visible corrections use a separate
`PredictionCorrection`; outcomes use separate `OutcomeRecord` entries. The
application ledger exposes append operations and explicitly rejects prediction
update/delete attempts. It also maintains a SHA-256 chain over append order.

## Outcome evaluation

`OutcomeEvaluator` runs only on or after the declared calendar-day horizon. It
uses ordinary 34-digit `Decimal` code for the asset and benchmark return. The
declared rule decides whether cash distributions are included; it cannot change
after publication. Start observations must have been available and retrieved by
the original prediction cutoff. End observations and corporate actions must be
known by the evaluation cutoff.

Security outcome status explicitly retains active, delisted, acquired, bankrupt,
renamed, and unavailable cases. Missing observations append an unavailable
outcome instead of silently dropping the prediction. Descriptive reports count
all supplied predictions and disclose unavailable cases; they are not calibrated
performance claims.

## PostgreSQL migration

`migrations/0001_prediction_outcomes.sql` creates prediction, correction, and
outcome tables with foreign keys, checks, UTC `timestamptz` fields, and triggers
that reject update, delete, and truncate. This follows PostgreSQL's documented
[trigger model](https://www.postgresql.org/docs/18/triggers.html). Rollback is a
future corrective migration; the immutable history is not destructively removed.

The integration service uses the official PostgreSQL image's documented
[`/docker-entrypoint-initdb.d` initialization](https://hub.docker.com/_/postgres).
It has no network interface or published port and stores its test database in
temporary memory. It is not a production database.

Run the gate from the repository root:

```bash
docker compose --profile integration pull postgres-test
docker compose --profile integration up --detach --wait postgres-test
docker compose --profile integration exec -T postgres-test \
  psql --username postgres --dbname kalki_test --file /dev/stdin \
  < tests/postgres/prediction_immutability.sql
docker compose --profile integration down
```

The test appends a synthetic prediction and delisted outcome, then proves update
and delete attempts fail. Run `down` even after a failed test to remove the
ephemeral container.

## Limitations

- There is no scheduler, production database credential, network ingestion,
  exchange-calendar horizon, API, public publication, or user interface.
- Calendar-day horizons are immutable and explicit. Trading-session rules would
  require a future version and exchange-calendar evidence.
- Corporate-action inputs are recorded and cash distributions are deterministic,
  but merger consideration and bankruptcy recovery require explicit normalized
  inputs; the evaluator never invents them.
- Reports are descriptive over recorded outcomes, not backtests. Walk-forward
  evaluation and calibration remain Phase 13.

## Phase 37 filing-dossier observations

Phase 37's prospective T+1/T+5/T+20 records are a separate supporting observation
ledger over immutable filing dossiers, not Phase 9 predictions and not evidence that a
forecast was made. `GENUINE_FORWARD` and `RECONSTRUCTED` remain explicit, raw price
returns are calculated deterministically, and missing provider observations append an
unavailable result. See
[PHASE37_PROSPECTIVE_OUTCOMES.md](PHASE37_PROSPECTIVE_OUTCOMES.md).
