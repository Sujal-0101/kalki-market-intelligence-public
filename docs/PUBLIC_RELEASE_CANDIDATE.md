# Public release candidate — Observation Baseline V2

**Candidate state:** local sanitized-source export prepared; no public repository,
remote, release, or visibility change has been created.

**Recommended first tag:** `v0.1.0-observation-baseline-v2`

The tag matches the current `pyproject.toml` package version and identifies the
frozen observation baseline without implying a mature compatibility promise. It is
a recommendation only. Apply it later to the reviewed one-commit public repository—
not to the private engineering repository—and only after the GitHub-side checklist
passes.

## Release identity

| Field | Candidate value |
|---|---|
| Functional baseline | Observation Baseline V2 / Phase 45 |
| Schema ceiling | `0027_outcome_science_invariants` |
| Source snapshot | The exact private `HEAD` supplied to `scripts/create-public-export.sh` |
| Source-commit record | `Private-source-commit:` trailer in the new repository's sole initial commit |
| Public history | One new root commit; no parent and no private Git objects/remotes |
| Project license | Apache License 2.0 (`LICENSE`) |
| Primary environment | Ubuntu/Debian Linux, Docker Engine + Compose plugin, PostgreSQL 18, local Ollama |
| Accepted analyst | Serialized Qwen `qwen3:4b` at the baseline digest |

Because a Git commit cannot contain its own hash, this tracked manifest identifies
the source snapshot procedurally. The export script reads `git rev-parse HEAD` and
records that exact value in the clean root commit's message. Verify it with:

```bash
git show -s --format=fuller HEAD
```

That source hash is provenance only. The corresponding private commit object and its
parents are deliberately absent from the public repository.

## What the public export contains

The export starts from `git archive HEAD`, so it contains only tracked files from
the approved source commit. `.gitattributes` additionally omits:

- `.agent/` private execution/supervisor records;
- `docs/PROGRESS.md`, the detailed private engineering/production journal; and
- `docs/PRODUCTION_AUDIT_2026-08-27.md`, a private point-in-time operator audit; and
- `tests/test_supervisor_quota.py`, which tests only the excluded private supervisor.

It includes application source, migrations through 0027, all application tests and
controlled fixtures, Compose/Docker manifests, deployment scripts, the project license,
security/contributor files, and public/operator documentation. The validator rejects
environment files other than `.env.example`, secret/runtime directories, database
archives, logs, private home paths, literal production Discord IDs, previous host
metadata, non-public email domains, the removed NVIDIA fixture, symlinks, and files
over 5 MiB.

Ignored and untracked files—including the preserved local pager capture—cannot enter
`git archive` and are reported only as an excluded count. Their names or contents are
not copied to the export.

## Repeatable local export

Start from a clean, reviewed sanitization commit. Choose a new path outside the
private checkout; it must not already exist:

```bash
./scripts/create-public-export.sh /tmp/kalki-public-release-candidate
```

The script:

1. verifies required tools, an exact `HEAD`, no tracked/staged changes, and tracked
   release files;
2. rejects an existing output or any output inside the private checkout;
3. archives only tracked `HEAD` content while honoring `export-ignore`;
4. validates the source tree before any new Git metadata exists;
5. initializes a brand-new `main` repository with a generic non-personal author;
6. creates one root commit carrying the private-source provenance trailer;
7. proves the new history has exactly one commit, no remote, no alternates, and no
   reachable source commit;
8. runs `git fsck` and the privacy validator again; and
9. moves the completed repository atomically to the requested output path.

No command contacts GitHub, adds a remote, pushes, tags, changes visibility, reads
production data, or operates Docker. The old history is absent because `git archive`
exports file bytes, not `.git`, refs, commits, reflogs, hooks, remotes, object packs,
or alternates. `git init` creates an unrelated object database afterward.

## Verification commands

Run inside the exported repository:

```bash
python3 scripts/validate-public-tree.py --allow-git-metadata .
git rev-list --all --count
git log --oneline --decorate --all
git remote -v
git fsck --full --no-dangling
bash -n scripts/*.sh
gitleaks --redact=100 dir .
gitleaks --redact=100 git .
```

Expected results are validator `PASS`, commit count `1`, one parentless initial
commit, no remote output, a clean `git fsck`, and successful shell syntax. Then use
the [contributor guide](../CONTRIBUTING.md) for the offline test/static suite and the
[installation guide](INSTALLATION_GUIDE.md) for Compose validation with local
placeholders filled in.

The tracked `.gitleaks.toml` extends Gitleaks' default rules and narrows two reviewed
false-positive exceptions to explicit synthetic Discord snowflakes and one cache-test
variable line. It does not suppress a directory, commit, general token family, or
production configuration path.

## License and third-party notes

Owner-authored Kalki source is offered under Apache-2.0. Dependencies, PostgreSQL,
container bases, Ollama, Qwen weights, optional services, SEC source material, and
other third-party components keep their own licenses/terms. No model weights or
dependency source trees are bundled. See [third-party licenses](THIRD_PARTY_LICENSES.md)
before distributing wheels, images, model bundles, or appliances.

## Known limitations

- This is a frozen observation baseline, not permission for Phase 46 or feature work.
- Outcome and prediction samples are absent; the only supported assessment is
  `INSUFFICIENT_SAMPLE`. No investment-performance claim is made.
- Ownership and financing have bounded historical backlogs/failures.
- All observed novelty cases at baseline were `UNKNOWN_NOVELTY`; Focus membership
  history was empty.
- Gemma/verifier, model concurrency, and the optional market-data provider remain
  disabled.
- Discord and Cloudflare are optional and require operator-owned configuration.
- The reference deployment is Ubuntu/Debian with local Docker/Ollama; other platforms
  are not production-tested by this project.
- Local validation cannot inspect future GitHub settings, issues, Actions, secrets,
  packages, releases, Pages, webhooks, deploy keys, collaborators, or branch rules.

## Checklist before creating a GitHub repository

- [ ] Review the exact exported tree and its sole commit locally.
- [ ] Confirm `LICENSE` matches the standard Apache-2.0 text.
- [ ] Confirm contributor/copyright authority for all owner-authored material.
- [ ] Re-run the maintained local secret scanner against both worktree and new Git history.
- [ ] Confirm no remote exists and no original commit is reachable.
- [ ] Run the normal offline suite, Ruff, mypy, Compose rendering, shell syntax, and Markdown checks.
- [ ] Review `docs/THIRD_PARTY_LICENSES.md` and any binary-distribution obligations.
- [ ] Decide a public repository owner/name and public security-contact workflow.
- [ ] Review the intended repository description, social image, topics, and disclaimer.
- [ ] Confirm the old private engineering repository will remain private and separately backed up.

## Checklist before making the future repository public

- [ ] Review GitHub Actions/workflow permissions and pin any third-party actions.
- [ ] Enable private vulnerability reporting and GitHub secret scanning where available.
- [ ] Review collaborators, teams, deploy keys, webhooks, apps, environments, variables, and secrets.
- [ ] Review issues, pull requests, discussions, wiki, Pages, packages, releases, and cached artifacts.
- [ ] Configure protected/default branches and require reviewed checks appropriate to the project.
- [ ] Push only the clean public repository; never add the private repository as a remote.
- [ ] Compare the remote root tree and commit count with the approved local export.
- [ ] Create the recommended tag only on the reviewed public root commit.
- [ ] Make the separate explicit visibility change only after owner approval.
- [ ] Recheck public pages/docs for private contact, hostname, IDs, paths, or research.

Repository creation, pushing, tagging, and visibility changes remain manual owner
actions outside this candidate.
