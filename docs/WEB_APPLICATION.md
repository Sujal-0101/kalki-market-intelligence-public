# Local Web Application

Phase 11 provides a local, read-only presentation boundary for immutable research.
It does not deploy a public service or create editable research records.

## Available views

- `/radar` and `/radar/{brief_id}` provide the live searchable filing desk and
  exact-evidence dossiers.
- `/api/v1/radar`, its detail endpoint, and `/api/v1/radar/status` expose closed
  research and public-safe worker contracts.
- `/research` is the chronological public library for explicitly typed filing
  dossiers and forecasts; `/research/{prediction_id}` remains the forecast detail.
- `/api/v1/research` and its detail endpoint retain the closed forecast contracts;
  dossier APIs remain under `/api/v1/radar`.
- `/admin/login` authenticates the one configured local administrator.
- `/admin` and `/admin/research/{prediction_id}` show full immutable records and
  recent security audit events.
- `/api/v1/admin/audit` requires the same authenticated session.
- `/health` reports only `{"status":"ok"}`.

Public summaries omit thesis prose, publisher identity, internal input hashes, and
operational state. Detail views retain the evidence identifiers, hashes, UTC
availability/retrieval times, and calculation/model/prompt version lineage needed
to understand the publication. Every public page displays the research-only
disclaimer. Empty repositories say so explicitly and never generate display data.

Phase 15 makes `/radar` the public home page. Phase 35 makes `/research` the
combined public publication library without treating dossiers as predictions or
changing the forecast API/detail URLs. See
[PHASE35_PUBLIC_MODEL.md](PHASE35_PUBLIC_MODEL.md). The redesign uses server-rendered HTML, native
forms and meters, CSS-only visual systems, no external fonts, and no JavaScript. The
existing restrictive content-security policy therefore remains unchanged.

Phase 16 replaces the earlier dashboard treatment with **The Evidence Observatory**.
The warm editorial canvas, original Kalki SVG mark, CSS instrument, numbered signal
register, inspectable evidence line, and dossier folios use typography and rules in
place of interchangeable cards. Every radar label is a real brief and color alone
encodes only its stored classification; sweep, rings, angle, and distance are stated
to be non-quantitative ornament. Quiet mode renders no security blips. The system
pulse exposes only the existing public-safe worker snapshot and makes no health claim
without a recent recorded state.

The ordinary page path downloads no JavaScript, web font, tracker, or third-party
asset. The social preview is an original local 1200×630 PNG rendered from the tracked
SVG composition and is referenced only through metadata. CSS honors reduced motion;
navigation, native details, filters, dossiers, and source links remain usable by
keyboard and touch without animation.

## Local setup

Install the pinned dependencies as described in `DEVELOPMENT.md`, then generate a
password hash interactively:

```bash
.venv/bin/kalki-hash-admin-password
```

Copy the printed `KALKI_ADMIN_PASSWORD_HASH=...` line to the ignored `.env`, then
set:

```dotenv
KALKI_WEB_ENABLED=true
KALKI_WEB_HOST=127.0.0.1
KALKI_WEB_PORT=8000
```

Start the local server:

```bash
.venv/bin/kalki-serve-local
```

Open `http://127.0.0.1:8000/research`. Do not bind a development server to
`0.0.0.0`, forward the port, create a tunnel, or expose it through a router. The
validated settings reject non-loopback hosts. `KALKI_WEB_SECURE_COOKIES=false` is
appropriate only for loopback HTTP; an approved HTTPS deployment must set it to
`true` and complete Phase 12's separate review.

The CLI currently supplies an empty in-memory repository. This is honest but not
yet operationally useful: a later persistence adapter must load reviewed Phase 9
records without weakening the read-only protocol or point-in-time lineage.

## Security model

- Passwords are stored only as locally injected Argon2id encoded hashes.
- Login errors do not reveal whether the username or password was wrong.
- One-time client-bound login tokens and session CSRF tokens protect form posts.
- Random session bearer tokens are stored server-side only as SHA-256 digests.
- Sessions are bound to hashed client metadata and have idle and absolute expiry.
- Cookies are HttpOnly and SameSite=Strict; Secure mode is available for HTTPS.
- Admin routes authorize every request and use `Cache-Control: no-store`.
- Trusted-host checks, a content security policy, framing/referrer/MIME controls,
  general and login-specific throttles, and a 16 KiB mutating-body ceiling apply.
- Audit events use closed event/detail values and store only hashed client metadata.
- Templates autoescape untrusted research text and the site needs no JavaScript.

Sessions, throttles, and audit events are process-local. Restarting the server
logs the administrator out and clears those records. That is acceptable for the
single-process local phase, but not for public deployment or multiple workers.

## Verification

Normal tests use synthetic immutable records and an in-process client. They verify
public field minimization, output schemas, disclosures, HTML escaping, responsive
styles, keyboard focus, color contrast, trusted hosts, password verification,
CSRF, cookie flags, session binding/expiry/revocation, admin authorization,
rate limits, request-body limits, security headers, and secret-free audits. No test
starts a public listener or sends network data.
