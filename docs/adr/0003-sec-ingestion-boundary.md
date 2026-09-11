# ADR 0003: SEC Ingestion Boundary

- **Status:** Accepted for Phase 3
- **Date:** 2026-08-21 UTC

## Context

SEC submissions and company facts are the first authoritative live-data boundary.
The project must respect fair access, retain exact source lineage, prevent future
knowledge from leaking backward, and remain independent of a future database.

## Decision

- Use the documented unauthenticated `data.sec.gov` submissions and companyfacts
  JSON endpoints only for explicitly requested CIKs.
- Require a declared application/contact user agent and default to two requests
  per second, with an enforced ceiling of ten.
- Use a dependency-free, injectable HTTP transport with HTTPS host restrictions,
  size bounds, bounded retries, and schema validation.
- Store raw responses content-addressably with atomic writes and immutable
  manifests under the ignored local data root.
- Normalize issuer, recent-filing, and company-fact records into frozen Pydantic
  contracts with stable IDs and source hashes.
- Use retrieval time as the conservative initial `available_at` value.
- Keep Phase 3 independent of PostgreSQL; the normalized contracts become the
  later persistence boundary.

## Consequences

Tests are deterministic and do not consume SEC capacity. Identical fixture input
deduplicates safely, and a failed second endpoint leaves a valid raw checkpoint
for retry. The provider does not yet expand historical submission files or fetch
full filing documents. A live smoke request received HTTP 403 in this environment,
so current production reachability is an explicit operational limitation rather
than something the implementation attempts to circumvent.
