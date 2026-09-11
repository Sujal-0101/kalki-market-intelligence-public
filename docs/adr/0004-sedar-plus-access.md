# ADR 0004: SEDAR+ Access Remains Disabled

- **Status:** Accepted for Phase 4
- **Date:** 2026-08-21 UTC

## Context

Kalki needs Canadian disclosure coverage, but the official SEDAR+ public-site
terms prohibit automated access and database construction. Broader distribution
is described as a licensed subscription or approved ad-hoc request. Bot protection
also presented a CAPTCHA during the access assessment.

## Decision

- Do not build, call, or reverse-engineer a SEDAR+ public-website client.
- Do not use manual downloads as a way to populate Kalki's research database.
- Ship a provider protocol and an unavailable implementation that fails closed
  until a written license or approved source is reviewed.
- Require explicit automation, database-storage, redistribution, expiry, and
  agreement metadata at the future provider boundary.
- Use only synthetic test fixtures and keep provider-profile IDs, LEIs, listings,
  names, and jurisdictions separate for later entity resolution.
- Permit separately reviewed issuer-IR, regulator, and SEC sources as incomplete
  Canadian fallbacks without labeling them SEDAR+ coverage.

## Consequences

The project obeys access controls and incurs no subscription cost, but it cannot
claim comprehensive Canadian filing coverage. The tested normalization boundary
reduces future integration risk without asserting that a licensed feed exists.
Enabling the provider requires user approval for any cost/legal terms and a new
review of privacy, retention, redistribution, deletion, credentials, and technical
requirements.
