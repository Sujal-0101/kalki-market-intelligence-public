# Phase 12 production threat model

`YOUR_PUBLIC_HOSTNAME` replaces the private engineering deployment's hostname. It
denotes the operator-controlled value from ignored local configuration.

> **Production status (2026-08-25):** the reviewed research surface is live at
> `YOUR_PUBLIC_HOSTNAME`. The outbound connector is healthy;
> remote admin and origin/database exposure remain absent.

## Protected assets and trust boundaries

The protected assets are PostgreSQL research records, immutable prediction and
filing-brief history, admin credentials and sessions, security audits, database credentials,
the Cloudflare tunnel token, and local backups. The intended request path
is:

```text
Internet -> Cloudflare edge -> outbound-only Tunnel connector
         -> public container -> least-privileged PostgreSQL role

Loopback operator -> admin container -> the same least-privileged role
                                  -> durable sessions and append-only audits

SEC -> identified worker -> private Ollama -> validated append-only brief
```

The public and admin applications are separate processes with separate route
tables. `cloudflared` joins only the public connector network. PostgreSQL joins an
internal Docker network and publishes no host port. Admin publishes only on
`127.0.0.1:8000`; public also remains available on `127.0.0.1:8001` for local
health and recovery checks. The remote tunnel route targets only
`http://public:8001`.

Phase 15 adds an internal analyst network shared only by the worker and Ollama.
Neither publishes a port or joins the connector network. The deliberate public
`/api/v1/radar/status` projection contains only bounded state, timestamps, counts,
model name, and error codes; it exposes no health route, logs, source text, contact
identity, webhook, or database detail.

The worker alone also joins a non-internal `research_egress` bridge so it can reach
the SEC and Discord through outbound NAT. It publishes no port. SEC and Discord
clients independently enforce exact HTTPS host allowlists, redirect validation,
timeouts, response-size limits, and rate limits.

## Threats and controls

| Threat | Primary controls | Residual risk / response |
|---|---|---|
| Internet access to admin or operational routes | Public process has no admin, login, health, OpenAPI, or documentation routes; connector cannot join the admin network | Recheck externally before acceptance; immediately remove the published route and stop the connector if any private route responds |
| Origin bypass | No router port forwarding; host binds are loopback only; PostgreSQL has no host port; Tunnel is outbound-only; the public response pins HTTPS with HSTS | A later host firewall/router change could weaken this; inspect listeners and router state during every deployment review |
| Host-header or route confusion | Exact production hostname validation; public route table defaults unknown paths to 404; Cloudflare route is a single exact hostname | Proxy behavior remains an external dependency; verify wrong-host and private-path probes from outside |
| Credential theft | Secrets are ignored files mounted only into services that need them; tunnel uses `--token-file`; session bearer values are stored only as SHA-256 digests; no secrets in logs/audits | Anyone with a tunnel token can run the connector; rotate it in Cloudflare and replace the local file after suspected disclosure |
| Admin brute force/session theft | Admin remains loopback-only; Argon2id password; CSRF; client binding; idle/absolute expiry; durable login throttling; HttpOnly SameSite cookies | A compromised local account or host remains privileged; use a strong unique password and host login protection |
| Database mutation or audit erasure | Application role has prediction/outcome read-only grants, narrow mutable-session/rate grants, and audit insert/select only; database triggers reject immutable-record and audit update/delete/truncate | Database owner or host root can still alter data; restrict owner credential and use verified off-host backup copies later |
| Scraping, denial of service, expensive queries | Bounded and paginated public projections, indexed ordering, durable client rate limit, body limit, container CPU/memory/PID limits, Cloudflare DDoS/WAF, and an active free-plan edge rate rule | The public process trusts forwarded client IPs because only loopback and the private connector network can reach it; a future origin exposure would invalidate that assumption. One free edge rule is coarse; monitor and disable route under sustained abuse |
| Malicious stored content / XSS | Closed response schemas, server-side escaping, restrictive CSP and security headers, no rendering of arbitrary HTML | Browser and dependency flaws remain possible; patch pinned dependencies after review and rerun gates |
| Malicious filing content / prompt injection | Deterministic bounded excerpt selection, no model tools, private model network, injection quarantine, closed schemas, exact quote/figure/URL validation | Pattern and lexical controls are defense layers, not semantic proofs; reject on uncertainty and retain exact evidence |
| Worker abuse of sources or secrets | SEC identification and per-process rate limiting; exact SEC HTTPS origins; one read-only local-settings mount; no worker connector network | A compromised worker can read its SEC identity and Discord webhook; keep its image non-root/read-only/capability-free and rotate the webhook after suspected compromise |
| Supply-chain compromise | Exact Python locks and digest-pinned base, PostgreSQL, and connector images; non-root read-only app containers; dropped capabilities | Digests freeze known artifacts rather than prove safety; review release notes and vulnerability audit before upgrades |
| Data loss/corruption | Checksummed PostgreSQL volume, custom-format backup plus SHA-256 and row-count manifest, isolated restore rehearsal, forward migrations | A backup on the same disk is not disaster recovery; copy encrypted backups to separately approved storage before relying on it |
| Privacy leakage through logs/audits | Closed audit event/detail vocabulary, hashed client metadata, no raw IP or credential storage, normal connector log level | Cloudflare receives public visitor/network metadata under its terms; do not expose private research or admin through the tunnel |

## Security invariants

- No brokerage connection or automatic trading exists.
- Only reviewed read-only research projections may be public.
- The admin interface is local-only; Cloudflare Access is not a substitute for
  that physical route separation in this phase.
- Production start fails closed if a required secret, database, migration, or
  exact hostname is missing.
- Rollback removes the Cloudflare published route first, then stops the connector;
  local services and data remain available for diagnosis.

The Phase 12 external hostname, route-isolation, TLS, header, rate-rule, and rollback
probes passed. Phase 14 retained those boundaries after the bounded-query deployment.
