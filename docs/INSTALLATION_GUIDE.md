# Complete beginner installation guide

This guide installs Kalki on a clean 64-bit Ubuntu or Debian home server. It assumes
you have never administered a server. Read the whole guide before running commands.
The [hardware guide](HARDWARE_AND_SCALING.md) explains sizing; the
[operations guide](OPERATIONS_GUIDE.md) covers routine care.

> [!IMPORTANT]
> This guide is written for the sanitized clean-history source candidate. Use it only
> from an owner-approved immutable public commit/tag after a repository is created.
> Never clone/deploy the private engineering history or copy another operator's
> `.env`, secrets, database, hostname, or Discord IDs.

> [!WARNING]
> Docker access is effectively administrator access. A member of the `docker` group
> can mount host files and become root. Keep the server account private, use SSH keys,
> install security updates, and never expose PostgreSQL, Ollama, or Kalki admin to the
> Internet.

## 1. Preflight checklist

Before starting, you need:

- a dedicated x86-64 Ubuntu/Debian machine you control;
- at least the [minimum practical resources](HARDWARE_AND_SCALING.md#hardware-classes);
- reliable Internet access for OS packages, container images, the Qwen model, and
  normal SEC polling;
- a monitor/keyboard or SSH access to the server;
- an owner-approved Kalki repository URL and immutable commit/tag;
- a real contact address for the SEC `User-Agent`;
- two or more hours for first setup and model download;
- a separate disk or trusted destination for encrypted backups (recommended).

Discord, Cloudflare, a domain, GPU, paid service, and market-data account are **not
prerequisites**. Automatic trading is not supported.

## 2. Understand the command format

Commands in this guide run in a Linux terminal. A prompt such as `$` is not part of
the command. “As your server user” means the non-root account you normally log in
with. `sudo` asks Linux to run only that command with administrator authority.

After cloning, commands marked **repository root** run from the directory containing
`compose.production.yaml`. Check your location with:

```bash
pwd
ls
```

`pwd` prints the current directory; `ls` lists it. In the repository root, expect
`README.md`, `compose.production.yaml`, `migrations/`, `scripts/`, `src/`, and
`tests/`. “No such file” usually means you are in the wrong directory; use `cd` to
move there.

## 3. Hardware and Internet requirements

The accepted Qwen model is a roughly 2.5 GB quantized artifact, but inference,
runtime state, PostgreSQL, and containers require substantially more memory. A
practical CPU-only starting point is **4 modern 64-bit CPU cores, 16 GiB RAM, and a
100 GB SSD**, derived from implementation limits and not tested as a minimum. The
reference machine has 4 cores/8 threads, 24 GB installed RAM, and a 250 GB NVMe SSD.

The system makes small periodic index/API requests and occasional large SEC filing
downloads. Do not use a metered connection without monitoring it. Normal operation
also needs DNS and outbound HTTPS. No inbound Internet port is required for local
use.

## 4. Install a supported Linux system

Use a currently supported Ubuntu LTS Server or stable Debian release. During OS
installation:

1. create a non-root account (examples below use `kalkiadmin`);
2. enable OpenSSH only if you need remote administration;
3. use full-disk encryption where unattended reboot requirements allow it;
4. do not install Docker from an unknown image or third-party script.

Log in and identify the OS:

```bash
cat /etc/os-release
uname -m
```

Run this **on the server**. The first command prints the distribution/version; the
second should normally print `x86_64`. Stop if the OS is unsupported or the
architecture does not match the images/models you intend to use.

## 5. Update the OS

```bash
sudo apt update
sudo apt full-upgrade
```

Run on the server. `apt update` refreshes package catalogs; `full-upgrade` installs
available fixes and handles dependency changes. Review the package list before
confirming. DNS errors indicate network trouble; “could not get lock” often means
another update process is running.

If `/var/run/reboot-required` exists after upgrading, reboot before Docker setup:

```bash
test ! -f /var/run/reboot-required || sudo reboot
```

The SSH connection will close during reboot. Wait, reconnect, and continue.

## 6. Confirm the non-root account

```bash
id
sudo -v
```

`id` should show your normal username, not `uid=0(root)`. `sudo -v` verifies that
the account may administer the host and may prompt for its password. If you are root,
create a normal account from the console:

```bash
adduser kalkiadmin
usermod -aG sudo kalkiadmin
```

These root-only commands create the account and add it to Ubuntu/Debian's sudo group.
Log out and back in as that user. Do not run the application routinely as root.

## 7. Install Git and basic tools

```bash
sudo apt install git ca-certificates curl openssl
git --version
```

This installs Git, trusted HTTPS certificates, a download client, and a cryptographic
random generator. The second command should print a Git version. Package-not-found
usually means `apt update` was not completed.

## 8. Install Docker Engine and Compose

Use Docker's current official Ubuntu or Debian repository instructions; commands can
change over time. The authoritative pages are
[Docker Engine for Ubuntu](https://docs.docker.com/engine/install/ubuntu/) and
[Docker Engine for Debian](https://docs.docker.com/engine/install/debian/). The
Ubuntu path is shown below.

Install repository prerequisites:

```bash
sudo apt update
sudo apt install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
```

Run on the server. These create the protected key directory and install Docker's
repository signing key. A TLS/certificate error should be fixed, not bypassed.

Add the repository:

```bash
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
```

This writes a package-source definition using your detected Ubuntu codename and CPU
architecture. On Debian, use Docker's Debian page and `linux/debian` repository;
do not paste the Ubuntu entry.

Install Engine and the Compose plugin:

```bash
sudo apt update
sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

Expected result: packages install and the Docker service becomes active now and at
boot. If packages have no installation candidate, recheck the repository and OS
codename.

Verify with the harmless demonstration container:

```bash
sudo docker run --rm hello-world
sudo docker version
sudo docker compose version
```

The first download ends with a success explanation; the others show client/server
and Compose versions. A daemon connection error means Docker is not running.

Optionally allow your account to use Docker without `sudo`:

```bash
sudo usermod -aG docker "$USER"
newgrp docker
docker info
```

This grants administrator-equivalent Docker access. `newgrp` starts a shell with the
new group; a fresh login is safer if it behaves unexpectedly. `docker info` should
show server details without an access error.

## 9. Clone and pin an immutable revision

Choose a parent directory owned by your user:

```bash
mkdir -p "$HOME/services"
cd "$HOME/services"
git clone OWNER_APPROVED_REPOSITORY_URL kalki-market-intelligence
cd kalki-market-intelligence
```

Replace the placeholder with the exact owner-approved HTTPS or SSH URL. These
commands create a service directory, clone Git history, and enter the repository.
Authentication errors mean your URL/key/access is wrong; do not paste access tokens
into the command line.

Never deploy an unreviewed moving branch. List available tags and commits:

```bash
git fetch --tags --prune
git tag --list
git log --oneline -10
```

The owner should publish an accepted tag or commit. Pin it using one of:

```bash
git switch --detach APPROVED_TAG
git switch --detach APPROVED_40_CHARACTER_COMMIT
```

Detached HEAD is intentional for a deployment. Verify:

```bash
git rev-parse HEAD
git status --short --branch
```

The hash must equal the approved release. Status should show no changed tracked file.
Record the hash in your private change log.

## 10. Learn the directory structure

```text
kalki-market-intelligence/
├── compose.production.yaml     hardened local/private stack
├── compose.cloudflare.yaml     optional public connector
├── Dockerfile                  non-root application image
├── migrations/                 ordered SQL 0001 through 0027
├── deploy/postgres/initdb/     first-database role initialization
├── scripts/                    guarded migration, backup, restore, and test tools
├── src/kalki_market_intelligence/
├── tests/ and data/fixtures/   controlled tests; not production market evidence
├── docs/                       architecture and operator documentation
├── .env                        local ignored settings (you create it)
├── secrets/                    local ignored secret files (you create it)
└── backups/                    local ignored archives (created later)
```

Do not put real secrets or private research in tracked directories.

## 11. Configure local settings

Create the ignored settings file from the template:

```bash
cp .env.example .env
chmod 600 .env
```

Run in the repository root. This copies only placeholders, then restricts the file
to your account. Confirm Git ignores it without printing its content:

```bash
git check-ignore -v .env
stat -c '%a %n' .env
```

Expected: an ignore rule and mode `600`.

Edit it locally:

```bash
nano .env
```

Replace only placeholders. At minimum configure:

```dotenv
KALKI_ENVIRONMENT=production
KALKI_TIMEZONE=UTC
KALKI_SEC_USER_AGENT="Kalki Market Intelligence contact@example.invalid"
KALKI_OLLAMA_BIN=/usr/local/bin/ollama
KALKI_OLLAMA_LIB=/usr/local/lib/ollama
KALKI_OLLAMA_HOME=/usr/share/ollama/.ollama
KALKI_HOST_UID=REPLACE_WITH_OLLAMA_UID
KALKI_HOST_GID=REPLACE_WITH_OLLAMA_GID
KALKI_IMAGE_TAG=release-APPROVED_SHORT_COMMIT
```

Use your real monitored contact address for the SEC line; `.invalid` is only a
documentation placeholder. After installing Ollama, use `id -u ollama` and
`id -g ollama` for its actual numeric IDs, and verify the binary, library, and model
paths rather than assuming the example matches every installer version. Do not change
UTC, Qwen digest, model concurrency, verifier state, or provider state without a
separately measured release.

### Important environment variables

| Variable | Meaning | Safe baseline |
|---|---|---|
| `KALKI_SEC_USER_AGENT` | Descriptive application + real contact for SEC requests | Required |
| `KALKI_SEC_REQUESTS_PER_SECOND` | Client-side SEC throttle | 2, below SEC maximum |
| `KALKI_WORKER_MODEL` / `_DIGEST` | Accepted model identity | Baseline values only |
| `KALKI_WORKER_VERIFIER_ENABLED` | Optional Gemma path | `false` |
| `KALKI_PROSPECTIVE_OUTCOMES_ENABLED` | Optional provider worker | `false` |
| `KALKI_OLLAMA_*` | Host binary/library/model locations | Absolute local paths |
| `KALKI_IMAGE_TAG` | Immutable locally built image label | Release/commit-specific |
| `KALKI_DISCORD_*` | Optional private integration | Disabled/empty until configured |
| `KALKI_WEB_PUBLIC_HOSTNAME` | One allowed public Host value | `localhost` until optional exposure is reviewed |
| `KALKI_HOST_UID` / `_GID` | Host Ollama service identity used by Compose | Values reported by `id -u ollama` / `id -g ollama` |

The SEC asks automated users to identify their tool and remain within fair-access
limits; its published maximum is 10 requests/second. Kalki defaults to 2. See the
[SEC rate-control notice](https://www.sec.gov/filergroup/announcements-old/new-rate-control-limits).

## 12. Create secrets safely

Create the ignored directory and two independent database passwords:

```bash
install -d -m 700 secrets
openssl rand -hex 32 > secrets/postgres_owner_password
openssl rand -hex 32 > secrets/postgres_app_password
chmod 600 secrets/postgres_owner_password secrets/postgres_app_password
```

Run in the repository root. `openssl rand` writes unpredictable 64-character values
directly to files; it does not display them. Never reuse the owner and application
password. Verify names/modes only:

```bash
find secrets -maxdepth 1 -type f -printf '%m %f\n'
git check-ignore -v secrets/postgres_owner_password
```

Expected mode is `600`; the path must be ignored. Production bind-mount ownership
can require a carefully reviewed `0644` inside the `0700` parent, as the existing
runbook notes, but prefer `0600` and adjust ownership to the container UID rather
than broadening access.

Create an empty placeholder for the **disabled** Discord service if Compose
validation requires the declared secret:

```bash
install -m 600 /dev/null secrets/discord_intake_bot_token
```

An empty file is not a token and must never be used with intake enabled.

## 13. Install Ollama and Qwen

Use the [official Ollama Linux guide](https://docs.ollama.com/linux). For a production
host, inspect the installer before granting it root authority:

```bash
curl -fsSL https://ollama.com/install.sh -o /tmp/ollama-install.sh
less /tmp/ollama-install.sh
sudo sh /tmp/ollama-install.sh
```

The first command downloads the official script, `less` lets you review it, and the
last installs Ollama. Expected result: an `ollama` binary and usually an `ollama`
system service. Network/TLS errors must not be bypassed. Verify:

```bash
command -v ollama
ollama --version
systemctl status ollama --no-pager
id -u ollama
id -g ollama
find /usr/local/lib /usr/lib -maxdepth 2 -type d -name ollama -print 2>/dev/null
getent passwd ollama
```

The final commands identify the service UID/GID, library directory, and home
directory. Put those exact values/paths in `.env`. A different result is not an
error; it means the installation layout differs from the example.

Pull the exact accepted model once:

```bash
ollama pull qwen3:4b
ollama show qwen3:4b
```

Run while the just-installed host service is active. `pull` downloads several
gigabytes; `show` displays model metadata. Confirm the digest through the repository's
benchmark/lineage tooling, not by model name alone. The accepted digest is documented
in the [complete guide](KALKI_COMPLETE_GUIDE.md#step-5-serialized-qwen-roles).

Now stop the host service before Kalki's private container owns the same model files;
do not run two servers against one model directory:

```bash
sudo systemctl disable --now ollama
```

This stops/disables the host service but leaves binary and models installed. The
Kalki Compose service starts the binary privately with no host port, cloud disabled,
CPU-only baseline settings, and one request at a time.

Do **not** pull/enable Gemma for normal installation. Do not increase context,
parallelism, or choose an 8B/14B model merely because it starts.

## 14. Build the application image

Validate the configuration without starting anything:

```bash
docker compose -f compose.production.yaml config --quiet
```

No output and exit status 0 means Compose can interpolate the files. If it reports a
missing variable/file, fix that specific placeholder; never copy production secrets
from another server.

Build the immutable local image:

```bash
docker compose -f compose.production.yaml build --pull
docker image ls kalki-market-intelligence
```

Run in the repository root. BuildKit downloads pinned base layers and installs exact
locked Python dependencies. The image list should contain your `KALKI_IMAGE_TAG`.
Build failures commonly mean low disk space, DNS trouble, or a lock mismatch.

Generate the admin Argon2id hash using the built image. This prompts twice and saves
only the hash:

```bash
docker run --rm -i kalki-market-intelligence:release-APPROVED_SHORT_COMMIT \
  kalki-hash-admin-password \
  | sed -n "s/^KALKI_ADMIN_PASSWORD_HASH='\(.*\)'$/\1/p" \
  > secrets/admin_password_hash
chmod 600 secrets/admin_password_hash
test -s secrets/admin_password_hash
```

Replace `release-APPROVED_SHORT_COMMIT` with the literal safe image tag from `.env`.
The password is read without appearing in a command argument;
the file receives only a one-way Argon2id hash. `test -s` succeeds silently if the
file is nonempty. Choose at least 14 characters and store the password in a trusted
password manager.

## 15. Initialize PostgreSQL and apply migrations

On a **brand-new empty Docker volume**, PostgreSQL's entrypoint runs the mounted SQL
files in numeric order, creates the least-privileged `kalki_app` role, and records
all 27 migrations. Start only PostgreSQL first:

```bash
docker compose -f compose.production.yaml up -d postgres
docker compose -f compose.production.yaml ps postgres
```

Expected: `healthy` after initialization. First start can take longer. Inspect logs
without printing environment values:

```bash
docker compose -f compose.production.yaml logs --tail=100 postgres
```

Verify the migration ledger read-only:

```bash
docker compose -f compose.production.yaml exec -T postgres \
  psql -X -U kalki_owner -d kalki -c \
  "SELECT version, applied_at FROM schema_migrations ORDER BY version;"
```

Expected final version: `0027_outcome_science_invariants`.

> [!CAUTION]
> Init files run only for an empty data directory. Adding a migration file and
> restarting PostgreSQL does **not** apply it to an existing database. For an update,
> create a fresh backup, pass the isolated restore gate, review the named migration
> script, apply migrations in order, then verify. Never run migrations from two
> checkouts concurrently and never restore over the only production volume.

## 16. Start the minimum local/private stack

Explicitly omit the optional Discord, Cloudflare, and prospective-outcome profiles:

```bash
docker compose -f compose.production.yaml up -d \
  postgres ollama admin public worker ownership-worker financing-worker accounting-worker
docker compose -f compose.production.yaml ps
```

This starts the database, private model service, loopback admin/public processes,
main research worker, and deterministic specialized workers. It does not start the
optional tunnel, Discord intake, or market-data/outcome profile. Expected: every
listed service reaches `running`/`healthy`; the first Ollama health check can take
longer.

Verify no database/model port is published:

```bash
docker compose -f compose.production.yaml ps --format json
sudo ss -lntp
```

Only Kalki `127.0.0.1:8000` and `127.0.0.1:8001` should be visible from this stack.
Do not paste complete network output into public issues because it may contain host
addresses.

## 17. Post-install checks

### Container health

```bash
docker compose -f compose.production.yaml ps
docker compose -f compose.production.yaml logs --tail=50 worker
```

Look for healthy services and bounded polling, not necessarily a published dossier.
Do not expect an alert immediately.

### PostgreSQL

```bash
docker compose -f compose.production.yaml exec -T postgres \
  pg_isready -U kalki_owner -d kalki
```

Expected: “accepting connections.” This checks readiness, not data correctness.

### Ollama

```bash
docker compose -f compose.production.yaml exec -T ollama ollama list
```

Expected: `qwen3:4b`. The service has no public host port.

### Public process and Radar

```bash
curl -I http://127.0.0.1:8001/
curl -fsS http://127.0.0.1:8001/radar >/dev/null
curl -fsS http://127.0.0.1:8001/research >/dev/null
curl -fsS http://127.0.0.1:8001/screened >/dev/null
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8001/admin
```

Run on the server. `/` redirects; the three public pages should succeed; public
`/admin` must print `404`. From your laptop, create an SSH tunnel:

```bash
ssh -L 8001:127.0.0.1:8001 -L 8000:127.0.0.1:8000 kalkiadmin@SERVER_LAN_NAME
```

Run this **on your laptop**, replacing the placeholder with the private LAN name.
Keep it open, then browse `http://127.0.0.1:8001/radar`. The admin page is available
only through the second local tunnel. Do not use a public IP placeholder in shared
documentation.

### Post-install checklist

- [ ] Deployed hash matches an approved immutable revision.
- [ ] `.env`, `secrets/`, backups, and model files are ignored.
- [ ] Database owner/app passwords are distinct.
- [ ] Migration ledger ends at the release's expected version.
- [ ] Qwen name and digest match the accepted release.
- [ ] Gemma, model concurrency, prospective outcomes, Discord, and Cloudflare are off.
- [ ] PostgreSQL and Ollama have no host port.
- [ ] Admin/public bind only to loopback.
- [ ] Public admin/docs/OpenAPI/health probes are 404.
- [ ] A backup and isolated restore test are scheduled.

## 18. Optional Discord

Discord has two separate capabilities: public outbound webhook notification and
private allowlisted Gateway intake/results. Neither is required. Creating a bot,
webhook, channel, or account-side permission is an external privacy/security action;
review [Discord integration](DISCORD_INTEGRATION.md) first.

Never place tokens or webhook URLs in tracked YAML, shell history, Git, chat, or
screenshots. The webhook is supported only in the ignored mode-`0600` `.env`; the
Gateway bot token belongs in its separate ignored secret file. Restrict both to the
minimum guild/channel permissions, configure IDs through local placeholders, and
test only in a private non-production channel. Human content remains private.

For private Gateway intake, edit the ignored `.env` and replace every placeholder
with IDs from **your** server. Discord IDs are identifiers, not tokens, but they are
still private deployment metadata:

```dotenv
KALKI_DISCORD_INTAKE_CHANNEL_ID=YOUR_RESEARCH_CHANNEL_ID
KALKI_DISCORD_INTAKE_RESULTS_CHANNEL_ID=YOUR_RESULTS_CHANNEL_ID
KALKI_DISCORD_INTAKE_ALLOWLIST='["YOUR_ALLOWED_USER_ID"]'
```

Type the bot token directly into the already ignored file created in section 12:

```bash
nano secrets/discord_intake_bot_token
chmod 600 secrets/discord_intake_bot_token
```

Run these commands from the repository root. Do not paste the token as a command-line
argument because shell history can retain it. Confirm only the file mode and ignore
rule, never its content:

```bash
stat -c '%a %n' secrets/discord_intake_bot_token
git check-ignore -v secrets/discord_intake_bot_token
```

Only after reviewing Discord permissions and the private boundary, start the opt-in
profile and verify its local health/log classification:

```bash
docker compose -f compose.production.yaml --profile discord up -d discord-intake
docker compose -f compose.production.yaml --profile discord ps discord-intake
```

For outbound webhook alerts, `KALKI_DISCORD_ENABLED=true` and the webhook URL are
read from the ignored `.env` mounted as `local_environment`. Treat the entire `.env`
as a secret-bearing file. The two Discord capabilities are independent; neither is
required to run Kalki.

## 19. Optional Cloudflare Tunnel

Cloudflare is not required for local/LAN/SSH-tunnel use. It requires an external
account, domain/tunnel configuration, acceptance of current terms, and a tunnel-
scoped secret. Those decisions are outside installation and may have privacy or
cost consequences.

Before exposure, read [Security Model](SECURITY_MODEL.md), verify public route tests,
back up/restore, and confirm the tunnel ingress points **only** to the public service
on the private `public_connector` network. Never route admin, PostgreSQL, Ollama,
Docker socket, SSH, logs, or backup directories. The Compose profile is described in
[Production Deployment](PRODUCTION_DEPLOYMENT.md).

Set exactly one operator-controlled hostname in the ignored `.env` before validating
the optional tunnel:

```dotenv
KALKI_WEB_PUBLIC_HOSTNAME=YOUR_PUBLIC_HOSTNAME
```

Validate an owner-reviewed optional configuration without starting it:

```bash
docker compose -f compose.production.yaml -f compose.cloudflare.yaml config --quiet
```

Do not run `up` until the owner explicitly approves public exposure and configures a
tunnel-scoped token. Docker-published ports can bypass uncomplicated-firewall rules;
Kalki's loopback bindings are part of the protection, not a convenience.

## 20. Firewall guidance

Firewall changes can lock you out and are host-specific. From local console access,
an Ubuntu operator may inspect before changing anything:

```bash
sudo ufw status verbose
sudo ss -lntp
```

If you decide to use UFW, allow SSH from a trusted LAN source before enabling it.
Do not add inbound rules for 5432, 11434, 8000, or 8001. Cloudflare Tunnel makes an
outbound connection and needs no inbound public web port. Review Docker's official
firewall caveat because published container ports can bypass UFW policy.

## 21. Reboot persistence

Compose uses `restart: unless-stopped`; Docker starts at boot. Test during a planned
maintenance window:

```bash
sudo reboot
```

Reconnect, then:

```bash
systemctl is-active docker
cd "$HOME/services/kalki-market-intelligence"
docker compose -f compose.production.yaml ps
```

Expected: Docker active and services recover. A service you manually stopped before
reboot remains stopped under `unless-stopped`.

## 22. Backups and restore testing

Create a consistent custom-format archive and checksum:

```bash
./scripts/backup-postgres.sh
```

Run in the repository root. It writes under ignored `backups/postgres/`, produces a
manifest/checksum, and asks PostgreSQL to validate the archive list. List names and
modes, not contents:

```bash
find backups/postgres -maxdepth 1 -type f -printf '%TY-%Tm-%Td %TH:%TM %m %f\n' | sort
```

Test a selected archive in an isolated network-disabled temporary database:

```bash
./scripts/restore-postgres-gate.sh backups/postgres/kalki-YYYYMMDDTHHMMSSZ.dump
```

Replace the placeholder with the exact archive. The gate verifies checksum, restores
to a disposable container, compares durable counts/migrations, and removes transient
sessions. Passing this test does not create an off-host backup. Encrypt any off-host
copy and treat it as sensitive human/research/security data.

## 23. Logs and routine monitoring

```bash
docker compose -f compose.production.yaml logs --since=30m --tail=200
docker stats --no-stream
df -h /
free -h
```

These show recent container output, one resource snapshot, disk space, and memory.
Do not post logs publicly before redacting identities, URLs, errors, paths, and
research content. See the [operations guide](OPERATIONS_GUIDE.md).

## 24. Safe updates

1. Read release notes and migration changes.
2. Create and restore-test a fresh backup.
3. Fetch without changing the checkout:

   ```bash
   git fetch --tags --prune
   ```

4. Review the exact change:

   ```bash
   git log --oneline CURRENT_COMMIT..NEW_APPROVED_COMMIT
   git diff --stat CURRENT_COMMIT..NEW_APPROVED_COMMIT
   ```

5. Stop workers, not PostgreSQL, if the release procedure requires a quiet queue:

   ```bash
   docker compose -f compose.production.yaml stop worker ownership-worker financing-worker accounting-worker
   ```

6. Detach at the approved commit, build a **new immutable tag**, run tests/migration
   gates, apply forward migrations in order, then recreate only reviewed services.

Never reuse a mutable image tag for two different builds. Historical incidents showed
that “rolling back” a tag after rebuilding it can actually deploy new bytes under an
old name. Record the Git hash, image ID/digest, migration ceiling, model digest, and
backup together.

### Safe rollback

Application rollback means selecting the recorded old commit and old image digest
compatible with the current schema, then recreating only application services. SQL
rollback is different: immutable migrations often have no safe reverse script.
Restore a verified backup into a **new** volume/database and compare it before
cutover. Never overwrite the only production volume or delete the newer backup.

### Model updates

A model update is a behavioral release. Pin name and digest; rerun fixed model,
schema, evidence, timeout, and resource benchmarks; keep inference serialized; and
do not replace the accepted model until all gates pass. A larger model is not
automatically more accurate, faster, or safer.

### Secret rotation

Rotate one boundary at a time during a maintenance window, back up first, and update
the secret file without printing it. Database password rotation also requires a
transactional PostgreSQL role-password update and coordinated container restart;
follow a reviewed release-specific runbook. Revoke old Discord/tunnel credentials at
the provider after the new credential works. A Git-history credential exposure
requires provider-side revocation even after history cleanup.

## 25. Troubleshooting decision tree

```text
Service unavailable?
├─ Does `docker compose ... ps` show the service?
│  ├─ No → validate Compose, then start only the missing reviewed service.
│  └─ Yes
├─ Is it healthy?
│  ├─ No → inspect its last 100 log lines and dependency health.
│  └─ Yes
├─ Public page fails?
│  ├─ Local curl fails → check public process, PostgreSQL, Host validation.
│  └─ Local works → SSH/tunnel/DNS boundary, not Kalki core.
├─ Worker quiet?
│  ├─ Heartbeat/queue moves → silence may be healthy screening.
│  ├─ Retry_wait grows → inspect bounded reason/provider/SEC health.
│  └─ No heartbeat → process/config/database/model dependency issue.
└─ Disk or RAM exhausted?
   ├─ Stop workers safely; preserve database and backups.
   └─ Inventory usage; do not delete volumes/models/backups blindly.
```

Common cases:

| Symptom | Safe check | Likely response |
|---|---|---|
| Permission denied on Docker socket | `id`; `ls -l /var/run/docker.sock` | Re-login after group change; do not chmod socket world-writable |
| PostgreSQL unhealthy | `logs --tail=100 postgres`; `df -h /` | Fix disk/secret/init error; do not delete volume |
| Migration missing | read `schema_migrations` | Back up/restore-test, then run exact guarded forward script |
| Qwen not listed | `exec ollama ollama list` | Check model directory mount and host ownership; do not pull another model as substitute |
| Model timeout | attempt receipts, `docker stats`, temperature | Let bounded retry policy work; reduce host load; do not raise concurrency |
| SEC 403/429 | worker logs, configured rate/identity | Stop aggressive polling, verify real contact identity, wait for rate block to clear |
| No dossiers | heartbeats, screening dispositions, attempts | May be healthy; never loosen gates to manufacture alerts |
| Public 404 on admin | public probe | Correct and expected |
| Admin unreachable remotely | local curl/SSH tunnel | Correct unless using an authorized private tunnel |
| Disk full | `df -h`, `docker system df` | Stop writers, back up, inventory; never run blanket prune |

## 26. Complete uninstall

Uninstall has recoverable and destructive levels. Decide what must be retained.

### Stop without deleting data (recoverable)

```bash
cd "$HOME/services/kalki-market-intelligence"
docker compose -f compose.production.yaml -f compose.cloudflare.yaml down
```

This stops/removes project containers and networks but preserves the named database
volume, host model files, secrets, backups, repository, Docker, and Linux.

### Remove application checkout after archiving (destructive)

First create and restore-test a backup, save the deployed commit/image records, and
move the checkout to an operator-chosen archive location. Do not use a recursive
delete command copied from documentation.

### Remove the database volume (irreversible without a backup)

> [!DANGER]
> This permanently deletes Kalki's database history. It must be separately approved.
> Inspect the exact volume name with `docker volume ls`; never use a wildcard.

After explicit approval and a verified off-volume backup, remove only the exact
identified volume:

```bash
docker volume rm EXACT_KALKI_POSTGRES_VOLUME_NAME
```

Expected: Docker prints that exact name. “Volume is in use” means a container still
references it; inspect rather than forcing removal.

Ollama, Docker Engine, firewall policy, user accounts, Cloudflare resources, Discord
resources, DNS, backups, and repository visibility are separate uninstall decisions.
Removing local software does not revoke external credentials. Use each provider's
account controls, and never delete the last backup until retention obligations are
satisfied.

## Security checklist before any public exposure

- [ ] The clean public export audit passes for the exact one-commit history.
- [ ] Apache-2.0 project license and third-party inventory are present and reviewed.
- [ ] No production IDs, home paths, secrets, private research, or logs are tracked.
- [ ] Maintained secret scanner passes the clean one-commit public history.
- [ ] Public SQL/templates are reviewed for minimization.
- [ ] Public app exposes only `/`, `/radar`, `/research`, `/screened`, and their
  intended static/API support.
- [ ] Admin, health, docs, OpenAPI, PostgreSQL, Ollama, SSH, Docker, and backups are
  absent from the public connector.
- [ ] Secure host patching, firewall, SSH, backups, restore testing, monitoring, and
  incident response are in place.
- [ ] Cloudflare/Discord are explicitly approved, minimally scoped, and optional.
- [ ] The operator understands that a public evidence page is not investment advice.
