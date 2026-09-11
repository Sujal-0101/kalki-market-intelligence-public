# Local Development

The local workflow uses isolated Python tooling and starts no public service. The
SEC command added in Phase 3 performs network ingestion only when the operator
invokes it with an identified user agent.

## Prerequisites

- Python 3.12 or newer
- Git
- Internet access only when installing the pinned Python packages

Do not install project packages into Ubuntu's system Python. All commands below use the ignored `.venv/` directory inside this repository.

## Create the isolated environment

The normal setup is:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --requirement requirements-dev.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation --editable .
```

Ubuntu installations without the `python3-venv`/`ensurepip` component can use this no-`sudo` fallback:

```bash
python3 -m venv --without-pip .venv
curl --fail --location --silent --show-error \
  https://bootstrap.pypa.io/pip/pip.pyz --output /tmp/kalki-pip.pyz
.venv/bin/python /tmp/kalki-pip.pyz install pip==26.2.1
.venv/bin/python -m pip install --requirement requirements-dev.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation --editable .
```

The fallback downloads pip from the official Python Packaging Authority endpoint into temporary storage. Review that command before running it. Installing Ubuntu packages with `sudo` is not required for this project workflow.

## Configuration

Copy `.env.example` to the ignored `.env` file only when overrides are needed. Phase 1 defines four non-secret settings:

| Variable | Default | Purpose |
|---|---|---|
| `KALKI_ENVIRONMENT` | `development` | Either `development` or `test` |
| `KALKI_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, or `ERROR` |
| `KALKI_DATA_DIR` | `data` | Local generated-data root; ignored by Git except fixtures/docs/placeholders |
| `KALKI_TIMEZONE` | `UTC` | Fixed to UTC for internal timestamps |
| `KALKI_SEC_USER_AGENT` | unset | Required application name and contact email for live SEC requests |
| `KALKI_SEC_REQUESTS_PER_SECOND` | `2` | SEC request rate; hard maximum `10` |
| `KALKI_SEC_TIMEOUT_SECONDS` | `30` | Per-request network timeout |
| `KALKI_SEC_MAXIMUM_RESPONSE_BYTES` | `50000000` | Compressed and decoded response-size boundary |
| `KALKI_DISCORD_ENABLED` | `false` | Hard switch for optional outbound Discord notifications |
| `KALKI_DISCORD_WEBHOOK_URL` | unset | Secret URL for an approved private Discord webhook; local `.env` only |
| `KALKI_DISCORD_REQUESTS_PER_SECOND` | `0.5` | Conservative local send-rate ceiling; maximum `2` |
| `KALKI_DISCORD_TIMEOUT_SECONDS` | `10` | Per-request Discord timeout; maximum `30` |
| `KALKI_DISCORD_MAXIMUM_RESPONSE_BYTES` | `100000` | Bounded response size for delivery confirmation |
| `KALKI_DISCORD_MAXIMUM_ATTEMPTS` | `3` | Maximum attempts used only for explicit Discord 429 responses |
| `KALKI_WEB_ENABLED` | `false` | Hard switch for the local web server |
| `KALKI_WEB_HOST` | `127.0.0.1` | Loopback bind; only `127.0.0.1` or `::1` is accepted |
| `KALKI_WEB_PORT` | `8000` | Local unprivileged port |
| `KALKI_WEB_SECURE_COOKIES` | `false` | Set only when an approved HTTPS boundary exists |
| `KALKI_WEB_SESSION_IDLE_MINUTES` | `30` | Admin inactivity expiry, from 5 to 120 minutes |
| `KALKI_WEB_SESSION_ABSOLUTE_HOURS` | `8` | Absolute session expiry, from 1 to 24 hours |
| `KALKI_WEB_LOGIN_ATTEMPTS` | `5` | Failed-login ceiling per client/window |
| `KALKI_WEB_LOGIN_WINDOW_SECONDS` | `300` | Login-attempt window |
| `KALKI_WEB_REQUEST_LIMIT` | `120` | General request ceiling per client/window |
| `KALKI_WEB_REQUEST_WINDOW_SECONDS` | `60` | General request window |
| `KALKI_ADMIN_USERNAME` | `admin` | Single local administrator identifier |
| `KALKI_ADMIN_PASSWORD_HASH` | unset | Required Argon2id hash when the web server is enabled; secret |
| `KALKI_WORKER_ENABLED` | `false` | Hard switch for the supervised filing-radar worker |
| `KALKI_WORKER_POLL_SECONDS` | `900` | Poll interval when the durable queue is caught up |
| `KALKI_WORKER_BATCH_SIZE` | `2` | Maximum filings claimed in one bounded run |
| `KALKI_WORKER_MODEL` | `qwen3:4b` | Reviewed local model used by narrow analyst roles |
| `KALKI_WORKER_MODEL_DIGEST` | pinned SHA-256 | Refuses analyst inference if the local tag changes |
| `KALKI_WORKER_VERIFIER_ENABLED` | `false` | Optional independent review; disabled production uses the full Qwen-plus-deterministic publication gate |
| `KALKI_WORKER_VERIFIER_MODEL` | `gemma4:12b-it-q4_K_M` | Selective local senior verifier; never a public endpoint |
| `KALKI_WORKER_VERIFIER_MODEL_DIGEST` | pinned SHA-256 | Refuses verifier inference if the local artifact changes |
| `KALKI_PROSPECTIVE_OUTCOMES_ENABLED` | `false` | Hard switch for private supporting outcome retrieval |
| `KALKI_PROSPECTIVE_OUTCOMES_POLL_SECONDS` | `3600` | Disabled worker polling interval |
| `KALKI_PROSPECTIVE_OUTCOMES_BATCH_SIZE` | `8` | Maximum due outcome jobs per poll |
| `KALKI_TWELVE_DATA_API_KEY_FILE` | unset | Absolute ignored secret file; required only after account-holder approval |
| `KALKI_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Loopback or private Compose Ollama origin only |
| `KALKI_OLLAMA_BIN` | reviewed user-local path | Host Ollama server binary mounted by Compose |
| `KALKI_OLLAMA_LIB` | reviewed user-local path | Host CPU runner library directory mounted by Compose |
| `KALKI_OLLAMA_HOME` | reviewed user-local path | Ignored local model store mounted by Compose |
| `KALKI_LOCAL_SETTINGS_FILE` | unset | Absolute read-only local `.env` mount used by the worker container |

Unknown values and invalid types fail validation. Do not put credentials in `.env.example` or Git.

## Checks

Run these from the repository root:

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src tests
.venv/bin/pytest
.venv/bin/python -m pip check
```

To apply safe Python formatting before rerunning the checks:

```bash
.venv/bin/ruff format .
```

## Layout

```text
src/kalki_market_intelligence/  package and boundary contracts
tests/                          invariant and configuration tests
docs/                           specification, decisions, and workflows
data/fixtures/                  future lightweight tracked test fixtures only
data/                           all other local generated research data (ignored)
```

No `data/` directory is required in Phase 1. Later phases may add lightweight fixtures when a provider contract needs them.

Phase 3 adds synthetic SEC schema fixtures under `data/fixtures/sec/`. Live raw
artifacts go under ignored `data/raw/sec/`. See [SEC_INGESTION.md](SEC_INGESTION.md)
before running `.venv/bin/kalki-ingest-sec <CIK>`.

Phase 5 adds synthetic market-data fixtures under `data/fixtures/market_data/`.
They require no account, key, or network and are documented in [MARKET_DATA.md](MARKET_DATA.md).

Phase 6 adds no dependency. Its deterministic reference cases live under
`data/fixtures/quantitative/`; calculation semantics and limits are documented in
[QUANTITATIVE_ENGINE.md](QUANTITATIVE_ENGINE.md).

Phase 7 adds synthetic analyst fixtures under `data/fixtures/analysis/`. Its
offline tests need no running model. The optional local quality gate needs the
already reviewed loopback Ollama service and writes its report under ignored
`data/evaluations/`; see [AI_ANALYST_PIPELINE.md](AI_ANALYST_PIPELINE.md).

Phase 8 adds dependency-free signal rules and synthetic reference cases under
`data/fixtures/signals/`. See [SIGNAL_ENGINE.md](SIGNAL_ENGINE.md) for point,
label, missing-input, and lineage semantics.

Phase 9 adds append-only prediction/outcome contracts and the first PostgreSQL
migration without adding a Python dependency. Its normal tests are offline. The
optional isolated database gate and cleanup commands are documented in
[PREDICTIONS_AND_OUTCOMES.md](PREDICTIONS_AND_OUTCOMES.md).

Phase 10 adds no dependency and performs no network send during normal tests. Its
Discord adapter is disabled by default; private setup and the separately confirmed
live connectivity command are documented in
[DISCORD_INTEGRATION.md](DISCORD_INTEGRATION.md).

Phase 11 adds FastAPI, Jinja, Uvicorn, form parsing, and Argon2 inside the same
isolated environment. Generate a hash and then copy only the resulting encoded
hash into the ignored `.env` file:

```bash
.venv/bin/kalki-hash-admin-password
.venv/bin/kalki-serve-local
```

The password generator requires two matching entries of 14–1024 characters and
does not print plaintext. The server refuses to start unless explicitly enabled
and configured, and it binds only to the validated loopback address. Visit
`http://127.0.0.1:8000/research` locally. The current command intentionally starts
with an empty in-memory research repository; it does not fabricate sample
research or connect to PostgreSQL. See [WEB_APPLICATION.md](WEB_APPLICATION.md).

Phase 12 adds pinned PostgreSQL client dependencies and an opt-in integration
gate. Normal development tests remain offline and skip that gate. The supervised
local production stack, secret-file requirements, backup/restore procedure, and
inactive Cloudflare handoff are documented in
[PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md). Do not start the
`exposure` Compose profile without a separate public-exposure approval.

Phase 13 adds no dependency or network requirement. Run the deterministic synthetic
walk-forward gate with:

```bash
.venv/bin/kalki-backtest data/fixtures/backtesting/phase13_synthetic.json \
  --output data/evaluations/phase13-synthetic-report.json
```

See [BACKTESTING.md](BACKTESTING.md) for temporal, survivorship, split, cost,
calibration, uncertainty, and incomplete-coverage semantics.

Phase 14 adds a dependency-free offline performance harness:

```bash
.venv/bin/python scripts/benchmark-phase14.py
```

Results vary by host and load, so compare repeated medians from the same machine. The
tracked baseline, optimized measurements, migration procedure, operating limits, and
provider review are in [PHASE14_OPTIMIZATION.md](PHASE14_OPTIMIZATION.md).

Phase 15 adds no Python dependency. Normal tests use synthetic SEC index and filing
records and never call SEC, Ollama, or Discord. The production worker is supervised by
Compose and its one-time local activation plus status checks are documented in
[LIVE_RESEARCH_RADAR.md](LIVE_RESEARCH_RADAR.md).

Phase 37 pins `exchange-calendars` inside the project environment. Its normal tests
use fixed provider responses and make no network call. The disposable PostgreSQL gate
is:

```bash
./scripts/test-prospective-outcomes-postgres.sh
```

No account or key is needed for that gate. The private live adapter and
`supporting-outcomes` Compose profile remain disabled; see
[PHASE37_PROSPECTIVE_OUTCOMES.md](PHASE37_PROSPECTIVE_OUTCOMES.md).

## Persistent supervisor quota handling

The autonomous supervisor recognizes the Codex CLI's explicit `You've hit your usage
limit` response separately from ordinary CLI failures. A parseable `try again at`
time receives a five-minute buffer, with a 15-minute minimum and 24-hour bounded sleep;
an unparseable reset uses a six-hour bounded fallback. Quota exhaustion neither resets
nor increments the generic failure counter, while genuine CLI errors still stop after
three consecutive failures. `CONTINUE`, `DONE`, and `BLOCKED` semantics are unchanged.
Shell syntax and parsing behavior are covered by `tests/test_supervisor_quota.py`.
