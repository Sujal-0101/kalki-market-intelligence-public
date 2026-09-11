# Public release audit

**Initial audit:** 2026-09-09 UTC
**Sanitization update:** 2026-09-10 UTC
**Scope:** the private engineering repository, the sanitized tracked source snapshot,
and the independent one-commit public export
**Purpose:** prepare for a possible public GitHub release; this report does not
authorize or perform a visibility change
**Overall result:** **PUBLIC_RELEASE_READY = NO**

> [!IMPORTANT]
> No repository visibility, DNS, tunnel, firewall, container, database, model, or
> production-data setting was changed during this audit. Values resembling secrets
> were never copied into this report. Observation Baseline V2 remains the accepted
> runtime baseline.

## Executive finding

No API key, bot token, password, private key, live webhook, session token, database
URL with credentials, or tunnel token was detected in the current tracked tree or
the complete reachable history by the methods below. That is encouraging, but it
is not sufficient for publication.

The initial audit found no credential but blocked publication on private Discord
identifiers, an operator home path, the private history containing those values, a
missing project license, and a copied NVIDIA investor-relations excerpt. The owner
subsequently selected Apache-2.0 and a **clean public-history export**.

The sanitized source now uses local environment configuration, fail-closed defaults,
generic paths, and a configurable hostname. The NVIDIA/SEC novelty pair was replaced
with fully synthetic structural fixtures. Internal execution records and detailed
private production journals and their supervisor-only regression remain intact in
the private repository but are marked `export-ignore`.
`scripts/create-public-export.sh` copies only tracked approved file
bytes, validates them, initializes a new unrelated repository, and proves that it
has one root commit, no remote, no alternates, and no reachable private-source commit.

The **private engineering history is intentionally not sanitized and must never be
made public**. `PUBLIC_RELEASE_READY` remains `NO` because the new GitHub repository
has not been created and account-side settings cannot be audited locally. This is
distinct from the local `PUBLIC_EXPORT_READY` gate documented at the end.

## Areas checked

| Area | What was examined | Result |
|---|---|---|
| Sanitized source snapshot | Source, tests, fixtures, docs, Compose, scripts, migrations, static assets | Private literals removed or excluded from export |
| Private reachable Git history | All commits and unique blobs reachable from all local and remote-tracking refs | Preserved intact; must remain private |
| Clean public export | Independent archive, privacy scan, Git object/history checks | Verified with one new root commit only |
| Working tree | Tracked, ignored, and untracked status | One preserved `less` capture; local secret/data paths ignored |
| Secret storage | Names, modes, ignore behavior, and Compose mounts; values not read or printed | Ignored; directory protected; some files are `0644` inside a `0700` directory |
| Backups and databases | Paths, modes, ignore behavior, and history names | Current dumps ignored and `0600`; none found in history |
| Logs and exports | Ignore rules and reachable path names | Local supervisor logs ignored; none found in history |
| Human research | Tables, public queries, templates, tests, docs, and history indicators | Runtime/export boundary passes; private history remains private |
| Public web boundary | Route registration and read-only local probes | Public `/admin` is 404; public pages are read-only |
| Deployment metadata | Bindings, Docker networks, secret mounts, container hardening | Appropriate local/private split; public config is parameterized and fails closed |
| Licenses/assets | Project, direct Python dependencies, runtime components, models, copied fixtures/assets | Apache-2.0 selected for original source; third-party terms remain separate |

## Methods used

The audit combined complementary checks; no single regex or scanner is treated as
proof of absence.

### Current-tree checks

- `git status --short --branch`, `git ls-files`, `git check-ignore -v`, and
  `.gitignore`/`.dockerignore` inspection.
- Filename checks for environment files, credentials, keys, certificates, dumps,
  databases, backups, logs, exports, cookies, sessions, and archives.
- Content checks for common provider-token formats, private-key headers, JWTs,
  authorization headers, credential-bearing URLs, password/secret assignments,
  high-entropy credential-shaped strings, emails, IP addresses, Discord snowflakes,
  webhook URLs, and absolute home paths.
- Manual review of every match in sensitive categories. Synthetic IDs, timestamps,
  schema examples, and explicit placeholders were separated from production IDs.
- Public-query and template inspection to ensure human research, prompts, raw model
  responses, hidden reasoning, internal exceptions, and Discord metadata are not
  selected by public routes.
- Read-only host/container, database-count, binding, and HTTP-route checks.

### Complete-history checks

- Enumerated all objects reachable from `git rev-list --objects --all` across all
  refs. The initial baseline scan covered **268 commits**. A second scan after the
  three documentation commits covered **271 commits**, **1,590 unique blobs**, and a
  largest blob of 338,869 bytes. `git count-objects` reported 3,202 loose objects
  using approximately 23.98 MiB at that checkpoint.
- Materialized each unique reachable blob into a temporary audit directory, scanned
  the content, recorded only classifications and paths, then removed the temporary
  directory.
- Searched historical filenames independently from content.
- Checked author identities and oversized objects. All baseline and documentation
  commits use a GitHub `noreply` author address. No reachable blob was 5 MiB or
  larger.
- Located the commits introducing the material privacy categories so remediation can
  be planned without publishing their values.

No maintained scanner was present during the initial audit. During sanitization,
Gitleaks 8.30.1 was downloaded from its official GitHub release, its Linux x64
archive matched the published release checksum, and it was run locally without
uploading repository content. The tracked configuration extends default rules and
allows only reviewed synthetic Discord snowflakes plus one cache-test variable
false positive; it does not ignore broad paths or commits.

## Findings

### Credential findings

| Category | Current tree | Reachable history | Assessment |
|---|---:|---:|---|
| Private-key headers | 0 | 0 | Pass |
| AWS access-key-shaped values | 0 | 0 | Pass |
| GitHub-token-shaped values | 0 | 0 | Pass |
| Slack-token-shaped values | 0 | 0 | Pass |
| Live Discord webhook URLs | 0 | 0 | Pass |
| JWT/tunnel-token-shaped values | 0 | 0 | Pass |
| Basic/Bearer authorization values | 0 | 0 | Pass |
| Credential-bearing database URLs | 0 | 0 | Pass |
| Tracked `.env`, key, dump, backup, or log files | 0 | 0 | Pass |

Password/secret assignment regexes matched test-only placeholder values and local
configuration field names. Manual review did not identify a real credential.

### Privacy and portability findings

| Original finding | Sanitized source/export treatment | Private history treatment |
|---|---|---|
| Discord channel/user/result/message IDs | Compose reads operator-owned values; disabled defaults are empty; enabled intake requires valid local values; the worker reads the configured result channel; the journal occurrence is redacted | Original commits remain unchanged and private |
| Operator home path | Code derives the current home; `.env.example` uses `/home/YOUR_USER`; Compose requires explicit local Ollama mounts | Original commits remain unchanged and private |
| Production hostname | Source accepts one validated hostname and defaults to `localhost`; templates derive request URLs; docs use `YOUR_PUBLIC_HOSTNAME` | Original hostname remains in private commits only |
| Detailed production/execution records | `.agent/`, `docs/PROGRESS.md`, the dated production audit, and the supervisor-only test are excluded by `git archive` attributes | Retained as private engineering evidence |

The commits first associated with these categories remain recorded in the private
audit history. They are not imported as parents or objects into the clean export.

### Human-research boundary

The implementation keeps human research in private tables and the authenticated
admin/Discord workflows. Public `/radar`, `/research`, and `/screened` repository
queries do not read human-lead text, submitter IDs, message IDs, feedback, raw model
output, or private result content. The public app does not register admin, health,
docs, or OpenAPI routes. A read-only local check returned 404 for public `/admin`.

This boundary is **implemented correctly at runtime**. The clean export additionally
omits the private engineering journals and runtime data paths.

## Ignored-sensitive paths verified

The following are ignored in the current repository:

- `.env` and `.env.*`, while `.env.example` remains intentionally tracked;
- `secrets/`, plus common private-key and certificate suffixes;
- `backups/`, `exports/`, `*.bak`, `*.backup`, databases, SQLite files, logs, models,
  raw data, caches, virtual environments, and build products;
- `data/*` except the intentionally committed synthetic/controlled fixture paths.

`.dockerignore` separately excludes Git metadata, environment files, secrets,
backups, data, logs, models, raw data, temporary files, and development artifacts
from the application build context.

Read-only verification found the local `.env` ignored; the `secrets/` and
`backups/` directories are mode `0700`; current PostgreSQL archives are mode `0600`.
Docker secret files should nevertheless be normalized to `0600` before any
deployment copy because several non-Discord files currently rely on the enclosing
`0700` directory for protection. Values were not inspected.

Generic `*.dump`, `*.dump.gz`, `*.sql.gz`, and `*.sql.zst` archives are now ignored
even outside `backups/`. Plain migration `.sql` files remain tracked. Ignore rules
are only defense in depth: `git add -f` can bypass them, while the public export
validator independently rejects database/archive suffixes.

## Suspicious untracked file

The exact untracked filename requested by the operator was inspected without
modification. It is a 15,915-byte ASCII terminal capture containing overstruck
formatting. After safely removing only backspace-overstrike bytes in memory, its
content matches a `less` help screen. It is not source code, a secret, a database,
or research evidence.

**Classification:** accidental terminal/pager capture; unrelated local artifact.
**Action taken:** none. It was not deleted, edited, staged, or ignored.

## License and reuse audit

> [!CAUTION]
> This inventory is technical due diligence, not legal advice.

### Project source

The owner selected Apache-2.0 for owner-authored Kalki source and documentation. The
root `LICENSE` is the unmodified standard Apache License 2.0 text, and project
metadata declares SPDX identifier `Apache-2.0`. No broad per-file headers or owner
identity were invented. Contributors must retain authority over submitted work.

No dependency source tree or model weight is bundled. The dependency inventory did
not identify a term that prevents applying Apache-2.0 to the original project source.
Dependencies, runtimes, models, SEC filing content, and optional services are **not
relicensed**; [the third-party inventory](THIRD_PARTY_LICENSES.md) records their
separate terms and binary-distribution cautions.

Repository visibility and open-source licensing remain separate decisions. Adding a
license grants rights under its terms; it does not create a GitHub repository, push
code, or change visibility.

### Direct Python dependencies

Installed metadata for the exact environment reported:

| Dependency | Installed version | Metadata license |
|---|---:|---|
| argon2-cffi | 25.1.0 | MIT |
| FastAPI | 0.141.1 | MIT |
| Jinja2 | 3.1.6 | BSD license classifier |
| Pydantic | 2.13.4 | MIT |
| pydantic-settings | 2.15.0 | MIT |
| python-multipart | 0.0.32 | Apache-2.0 |
| psycopg / psycopg-binary | 3.3.4 | LGPL-3.0-only |
| psycopg-pool | 3.3.1 | LGPL-3.0-only |
| Uvicorn | 0.52.4 | BSD-3-Clause |
| discord.py | 2.6.4 | MIT |
| exchange-calendars | 4.13.2 | Apache-2.0 |

The lock files contain transitive packages with MIT, BSD, Apache-2.0, PSF, 0BSD,
Zlib, CC0, and other notices. NumPy and pandas include bundled components with
multiple notices. Source publication normally references rather than redistributes
these wheels, but any binary/container release should generate an SBOM and bundle
all required third-party notices. The LGPL terms for Psycopg deserve explicit
release-process review if binaries or images are distributed.

### Runtime and model components

| Component | Basis established | Publication implication |
|---|---|---|
| PostgreSQL | [PostgreSQL License](https://www.postgresql.org/about/licence/) | Permissive; retain required notices when redistributed |
| Docker Engine/Moby | [Apache-2.0](https://github.com/moby/moby) | Docker Desktop is not part of this Linux deployment; images also contain separately licensed packages |
| Docker Compose specification/implementation | [Apache-2.0](https://github.com/compose-spec/compose-spec) | Referenced operational dependency, not copied source |
| Python | [PSF license stack](https://www.python.org/psf/summary/) | Preserve notices when redistributing a Python runtime |
| Ollama | [MIT](https://github.com/ollama/ollama/blob/main/LICENSE) | Runtime downloaded separately; model licenses remain separate |
| Qwen3 open-weight models | [Apache-2.0](https://github.com/QwenLM/Qwen3) | Accepted runtime model is downloaded separately; do not imply weights are bundled |
| cloudflared | [Apache-2.0](https://github.com/cloudflare/cloudflared) plus service terms | Optional client; using Cloudflare services is a separate account/terms decision |

The accepted runtime model lineage is `qwen3:4b`, digest
`359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`,
Q4_K_M, with 4.02 billion parameters. The digest is public integrity metadata, not
a secret. Gemma is installed locally but disabled and is not a repository-bundled
artifact; its separate model terms must be reviewed before any future enablement or
redistribution.

### Bundled/copied material

- Repository-native SVG/CSS and the derived social PNG are documented as original
  in `docs/ASSET_LICENSES.md`; no third-party font is bundled.
- Synthetic market/backtest fixtures are explicitly non-real.
- Tests contain bounded and compressed EDGAR filing fixtures. The SEC states that
  [EDGAR public filing content is free to access and reuse](https://www.sec.gov/about/webmaster-frequently-asked-questions),
  with source attribution and trademark care still appropriate.
- The NVIDIA investor-relations sentence and companion SEC recap fixture were removed.
  Their replacement uses invented prose, entities, reserved identifiers, and
  `example.invalid` canonical URLs. Focused tests prove the same recap fingerprint,
  unknown-time, material-update, and pre-Qwen removal behavior.

## Documentation and repository validation

The sanitized private source branch passed:

- the full offline-default suite: **703 passed, 30 intentionally skipped opt-in
  PostgreSQL integration tests**;
- Ruff formatting/lint and strict mypy over the complete source tree;
- base, optional Discord and optional Cloudflare Compose rendering without starting
  services;
- Bash syntax and `git diff --check`.

The independent clean export then passed:

- **700 tests**, with the same 30 opt-in PostgreSQL skips; the three omitted tests
  exercise only the deliberately excluded private supervisor;
- Ruff over 327 files and strict mypy over 250 source files;
- all three Compose renderings using a synthetic SEC contact identity supplied only
  to the validation process;
- Bash syntax, clean Git status, and `git fsck --full --no-dangling`;
- 74 Markdown files with 116 local file/anchor links, plus balanced fences;
- the public-tree validator before and after Git initialization;
- Gitleaks 8.30.1 directory and one-commit-history scans with **no leaks found**.

The final export contains 471 tracked files; its largest tracked file is 338,869
bytes. It contains no symlink, file over 5 MiB, remote, alternate object database,
or original private source commit. The `git archive` file manifest exactly equals
the new root commit's file manifest.

No external-link crawler was installed. Authoritative licensing/install links were
opened during research; provider pages and terms can change after this audit.

## Remaining risks

1. Regex/entropy scanning cannot prove that no bespoke credential exists. The final
   clean export passed a maintained local scanner; rerun it immediately before the
   eventual push and inspect any new finding.
2. Public forks, caches, or prior clones would not be repaired by a clean export.
   Confirm the private repository has never already been publicly exposed.
3. GitHub Actions, repository variables/secrets, deploy keys, webhooks,
   collaborators, branch protections, issue content, releases, packages, and Pages
   are outside this local repository audit and require an account-side review.
4. Container images are not stored in Git and were not exhaustively scanned here.
   Generate an SBOM and vulnerability report before publishing images.
5. Production backups and private human research are highly sensitive even though
   ignored. A mistaken manual `git add -f` can bypass ignore rules.
6. The future public hostname, if any, remains an operator-controlled ignored value.
7. A public repository invites untrusted contributions. CI, dependency update,
   review, and secret-scanning policy should exist before accepting pull requests.

## Manual user decisions required

1. Confirm contributor/copyright authority for the Apache-2.0 release.
2. Review the exact local clean export and its one root commit.
3. Choose the future GitHub owner/repository name and create it without importing
   history, issues, templates, or starter files.
4. Review GitHub account-side settings, collaborators, Actions, secrets, deploy keys,
   webhooks, Pages, packages, releases, and private vulnerability reporting.
5. Push only the reviewed clean export and compare its root tree/commit count.
6. Create the recommended tag only on the public root commit.
7. Make the separate, explicit repository-visibility decision only after all gates
   pass.

## Final decision

```text
Documentation:                          PASS (sanitized candidate)
Sanitized-tree credential audit:         PASS
Sanitized-tree privacy audit:            PASS
Private engineering history:             PRESERVED / MUST REMAIN PRIVATE
Clean-export history isolation:           PASS (one unrelated root commit)
Sensitive artifacts ignored/excluded:     PASS
Private-human runtime/export boundary:    PASS
License decision:                         APACHE-2.0 SELECTED
Third-party fixture remediation:          PASS (synthetic replacement)
Untracked suspicious file:                accidental less help-screen capture; excluded
PUBLIC_EXPORT_READY:                      YES
PUBLIC_RELEASE_READY:                     NO
```

Do **not** change the private repository's visibility. The remaining steps are the
manual GitHub-side decisions and verification in
[the release-candidate manifest](PUBLIC_RELEASE_CANDIDATE.md); none is authorized by
this report.
