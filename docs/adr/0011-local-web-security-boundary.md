# ADR 0011: Local Read-Only Web and Single-Admin Boundary

- **Status:** Accepted
- **Date:** 2026-08-24 UTC

## Context

Research needs deliberately limited public views and a protected inspection
workspace without making an unfinished development service public, weakening
immutable publications, or placing a plaintext administrator secret in Git.

## Decision

- Use a FastAPI application factory over a read-only repository protocol and
  closed Pydantic public response projections.
- Render accessible responsive pages with autoescaped server-side templates and
  an explicit research-only disclosure.
- Support one local administrator using an injected Argon2id hash, one-time login
  CSRF, throttled generic login failures, and expiring server-side sessions.
- Authorize every admin route, protect state-changing forms with session CSRF,
  and maintain a closed secret-free audit trail.
- Enforce loopback configuration and trusted hosts, bounded requests, restrictive
  security headers, no-store admin responses, and no public deployment.
- Keep the workspace inspection-only; corrections and outcomes continue through
  the append-only Phase 9 domain rather than web mutation.

## Consequences

The presentation layer can be tested with an in-memory repository and later gain
a PostgreSQL adapter without changing its public contracts. Sessions, throttles,
and audits disappear on restart, so this architecture is not approved for public
or multi-worker operation. The local CLI shows an honest empty state until a
durable repository is connected. Phase 12 still requires explicit approval and a
separate deployment/security review.
