# ADR 0010: Disabled-by-Default Discord Notifications

- **Status:** Accepted
- **Date:** 2026-08-24 UTC

## Context

Optional research notifications must not expose webhook secrets, ping users
unexpectedly, become trade instructions, duplicate ambiguous sends, or affect the
core research pipeline when disabled or removed.

## Decision

- Use one outbound incoming-webhook boundary with no bot token or inbound service.
- Require an explicit enable switch plus an origin-validated local secret.
- Render only bounded immutable research metadata with no thesis prose, mention
  parsing, promise, or requested action.
- Confirm successful persistence with `wait=true`, apply a conservative local
  limiter, and honor Discord-provided 429 delays.
- Deduplicate confirmed and ambiguous sends; never automatically retry an
  ambiguous transport or server result.
- Record only closed audit statuses, payload/destination hashes, attempt counts,
  timestamps, and confirmed message IDs—never the webhook token or URL.

## Consequences

The adapter can be removed or disabled without affecting predictions and outcomes.
Process-local deduplication must later move behind a durable persistence boundary.
One synthetic message was confirmed in the approved private destination before
acceptance, and the webhook remained outside Git and logs. An earlier synthetic
test was deleted after reaching the wrong channel; it contained no research data.
