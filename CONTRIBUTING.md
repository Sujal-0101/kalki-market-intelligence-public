# Contributing to Kalki Market Intelligence

Thank you for improving Kalki. Contributions must preserve its evidence-first,
point-in-time, fail-closed design. The current accepted system is Observation
Baseline V2 (Phase 45), and feature development is frozen. A roadmap item is not
authorization to implement it.

## Before opening work

Read, in order:

1. [README.md](README.md)
2. [ARCHITECTURE.md](ARCHITECTURE.md)
3. [docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md)
4. [docs/KALKI_COMPLETE_GUIDE.md](docs/KALKI_COMPLETE_GUIDE.md)
5. [docs/PHASE45_OBSERVATION_BASELINE_V2.md](docs/PHASE45_OBSERVATION_BASELINE_V2.md)
6. the relevant subsystem/phase documents and migrations
7. [SECURITY.md](SECURITY.md) and [docs/SECURITY_MODEL.md](docs/SECURITY_MODEL.md)

Check current Git status and preserve unrelated changes. Never rewrite shared
history, force-push main, discard user work, or delete production evidence.

## What is appropriate during the freeze

- documentation and public-release hygiene;
- reproducible correctness/security fixes for demonstrated defects;
- tests that characterize current behavior;
- read-only observation/reporting that does not move the baseline;
- narrowly proposed experiments on separate branches, not enabled in production.

Do not change model/digest, prompt/schema, evidence budgets, thresholds,
concurrency, verifier/provider state, database semantics, public exposure, or
publication behavior without explicit owner approval and measured acceptance plan.
Never add brokerage connectivity or automatic trading.

## Local environment

Use Linux and a repository-local virtual environment; do not modify system Python.
The project declares Python 3.12–3.14 compatibility, while exact exercised versions
are recorded in development/baseline docs.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
```

This creates an isolated environment and installs exact hashed development
dependencies. If the OS lacks `ensurepip`, follow the reviewed no-`sudo` fallback in
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

Never copy production `.env`, secrets, backups, models, logs, or human research into
a development checkout. Tests use controlled fixtures and synthetic credentials.

## Branch and commit workflow

1. Start from the accepted mainline and create a descriptive branch:

   ```bash
   git switch main
   git pull --ff-only
   git switch -c fix/short-description
   ```

2. Make one bounded change with tests/docs.
3. Review `git diff` and `git status`; stage explicit files, not secret-prone broad
   paths.
4. Commit a logical checkpoint with a factual message.
5. Push the branch without force and open a review.

Do not merge a phase or migration merely because unit tests pass. Production changes,
external messages, cost/terms, public routes, DNS/tunnel/firewall, credentials, and
destructive actions require owner approval.

## Required checks

Run focused tests while developing, then the relevant full gates:

```bash
.venv/bin/pytest
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy
git diff --check
docker compose -f compose.production.yaml config --quiet
```

The full suite is offline by default; PostgreSQL/model/provider tests are opt-in.
When a migration changes, run its dedicated disposable PostgreSQL lifecycle script.
Do not point integration tests at production. When deployment behavior changes, also
run non-root/read-only image smoke, backup/restore, and public/private route gates
described by the relevant phase.

### Formatting and typing

Ruff is the formatter/linter (100-character line length, Python 3.12 target). Strict
mypy covers source, tests, and the specified benchmark script with Pydantic's plugin.
Do not suppress a type/error rule without a narrow documented reason.

## Deterministic validation philosophy

- Use ordinary tested code for time, arithmetic, financial metrics, hashes, identity,
  filtering, routing, validation, and evaluation.
- Store internal timestamps in UTC and preserve published, available, retrieved,
  recorded, and evaluated meanings.
- Require point-in-time data; separate genuine forward and reconstructed records.
- Never choose the first XBRL value: match concept, accession, form, unit, period, and
  context or return unverifiable.
- Treat model output as hostile input. Validate schemas, exact quotations, evidence
  IDs, numbers, provenance, source identity, and links.
- Unknown/missing/ambiguous data must remain unknown or fail closed.
- No finding, a screen-out, or an incomplete analysis is valid behavior; never loosen
  gates to create output.

Tests must prove failure behavior as well as success. A synthetic fixture validates
mechanics only and cannot support an accuracy/performance claim.

## Evidence requirements for major changes

A major proposal must state:

- observed production/user problem and bounded consumer;
- immutable before/after commit, config, model, prompt/schema, and data identity;
- representative fixed fixtures and why they are representative;
- quality, contract acceptance/rejection, timeout, latency, memory, CPU/GPU, thermal,
  and public-responsiveness measurements where applicable;
- point-in-time/licensing/privacy analysis;
- failure modes, rollback/containment, and acceptance threshold chosen in advance;
- proof that deterministic/public/private boundaries remain intact.

“The model is larger,” “the result looks better,” and one hand-picked example are not
evidence. Do not claim investment performance without genuine forward samples and
the preregistered methodology; current outcome state is insufficient sample.

## Database migrations

- Add the next ordered forward SQL file and a guarded script.
- Record the version once; make reapplication idempotent.
- Use closed constraints, stable domain identities, foreign keys, least-privilege
  grants, and immutable update/delete protection where history is evidentiary.
- Reconcile relational query columns with stored structured JSON.
- Include the migration in new-database initialization, backup manifests, restore
  gates, docs, and tests.
- Test fresh apply, reapply, invalid insert, duplicate identity, least privilege,
  mutation rejection, and crash/reclaim behavior as relevant.

Never edit an applied migration in place. Never supply an automatic destructive down
migration for immutable history. Production application requires a fresh verified
backup and isolated restore gate.

## Security and privacy rules

Never commit or paste:

- API/bot/tunnel/session tokens, passwords, hashes from production, cookies, private
  keys, environment files, or credential URLs;
- database dumps, backups, logs, models, raw data, exports, or generated private
  reports;
- Discord guild/channel/user/message IDs or human message content;
- private emails, IP/MAC addresses, serials, local paths, or private URLs unless a
  public purpose is explicitly approved;
- prompts/raw model responses/hidden reasoning from production.

Use placeholders such as `contact@example.invalid`, `YOUR_CHANNEL_ID`, and generic
paths. Run current-tree and complete-history secret/privacy scans before public
release. A clean HEAD does not clean prior commits.

Report vulnerabilities privately through [SECURITY.md](SECURITY.md). Do not test
production, send real notifications, access other users' data, or create external
accounts/resources.

## Public/private boundary

Public changes must review SQL selection, repository contract, template, static
assets, route registration, caching, error handling, links, and tests. Public output
may contain only approved autonomous SEC identity/evidence and closed dispositions.
Human research, admin telemetry, errors, prompts, model text, sessions, Discord
metadata, and secrets remain private.

The public connector may reach only the public service. PostgreSQL, Ollama, admin,
Docker socket, SSH, backups, and logs must never be added to a public network/route.

## Dependencies and licenses

Do not add a dependency before documenting its exact version, source, license,
transitive footprint, security/update behavior, runtime need, and no-cost/offline
impact. Regenerate both runtime/development locks deterministically and verify them.
Do not copy third-party source, text, images, or models without a documented
redistribution basis and attribution.

Owner-authored project source is licensed under Apache-2.0. Under section 5 of that
license, intentionally submitted contributions are offered under the same terms
unless explicitly stated otherwise. Contributors must have authority to submit their
work and must identify third-party material and its license. See
[third-party licenses](docs/THIRD_PARTY_LICENSES.md).

## Pull-request checklist

- [ ] Scope is approved and compatible with the Phase 45 freeze.
- [ ] No secrets/private identifiers/data in tree or commit history.
- [ ] Deterministic code handles calculations and point-in-time rules.
- [ ] AI output has a closed schema and evidence validation.
- [ ] Public/private SQL and routes remain separated.
- [ ] UTC/provenance/idempotency/immutability are preserved.
- [ ] Focused and full relevant tests pass.
- [ ] Ruff formatting/lint and strict mypy pass.
- [ ] Migration, Compose, image, backup/restore, and route gates pass if affected.
- [ ] Documentation states implemented/optional/disabled/experimental/planned truthfully.
- [ ] No investment-performance or unsupported marketing claim.
- [ ] Diff and Git history were reviewed by a human.
