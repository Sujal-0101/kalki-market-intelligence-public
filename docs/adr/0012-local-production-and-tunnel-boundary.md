# ADR 0012: Local production and Cloudflare Tunnel boundary

- **Status:** Accepted
- **Date:** 2026-08-25

## Context

Phase 12 requires durable production state, recoverability, and the smallest
possible public surface. The Python service and PostgreSQL database remain on the
operator's host. The user explicitly approved the single research hostname.

## Decision

Run digest-pinned containers under Docker Compose: internal PostgreSQL, a
loopback-only admin process, and a separately routed read-only public process.
Persist admin sessions, request/login limits, and append-only security audits in
PostgreSQL under a least-privileged application role. Use checksummed custom
backups and restore them into a network-disabled temporary database for recovery
validation.

Run a remotely managed Cloudflare Tunnel connector only on the public process
network. Its Published Application may expose only
`YOUR_PUBLIC_HOSTNAME` to the HTTP origin `public:8001`. Its
tunnel-scoped token is file-injected. Remote admin is explicitly excluded.

## Consequences

Public and admin routes cannot be confused by middleware alone because they do
not exist in the same application process. Origin ports remain loopback-only and
the database has no host port. The host, local power/internet, and one database
volume remain availability and disaster-recovery dependencies. A same-host
backup protects against logical failure but not host loss; separate encrypted
backup storage needs a later approved privacy/cost decision.

The external route/TLS/security/rate-limit verification and connector rollback
drill passed before this ADR was accepted.
