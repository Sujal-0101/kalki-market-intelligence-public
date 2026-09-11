# Phase 35 public publication model

## Decision

Kalki has two immutable public record types, and they are not interchangeable:

- a **filing dossier** is an evidence-backed `ResearchBrief` produced from an
  authoritative filing and published at `/radar/{brief_id}`;
- a **forecast record** is a `PredictionRecord` with an explicit horizon,
  benchmark/evaluation contract, and later outcome lineage, published at
  `/research/{prediction_id}`.

The `/research` page is the chronological public library for both types. Each
row carries an explicit type label, type-specific fields, and its canonical
detail URL. `/radar` remains the operational filing observatory and dossier
search surface. A dossier is never projected as a forecast merely because it is
listed in the research library.

## Compatibility and API boundary

Existing URLs remain valid. The forecast detail URL and its closed API contract
are unchanged. In particular, `/api/v1/research` remains the forecast-only
`PublicResearchSummary` collection and `/api/v1/research/{prediction_id}` remains
the forecast detail endpoint. Dossiers remain available through the existing
`/api/v1/radar` endpoints. Phase 35 adds no new public route or mutation method.

The server-rendered `/research` page reads a combined repository projection. It
orders `research_briefs` and `predictions` by immutable UTC `published_at`, then
stable identifier, with dossiers first only for the otherwise-impossible-to-
distinguish cross-table tie. Pagination happens in PostgreSQL before contract
validation, so every public row appears once without loading either table in
full.

## Privacy and truthfulness boundary

The combined query names only `research_briefs` and `predictions`.
`research_human_results`, human hypotheses, private delivery records, prompts,
raw model output, and operational telemetry are not joined or projected. The
closed page projection contains only bounded dossier summary fields or the
existing forecast summary fields.

Production currently has seven dossiers and zero forecasts. The corrected
library must therefore show seven rows labelled `Filing dossier`; it must not
manufacture forecast horizons, prediction IDs, market outcomes, or duplicate
the same dossiers from `/radar`. Private human-result counts must not influence
the public result count.

## Verification

Offline tests cover mixed-type projection, exact-once listing, stable ordering,
pagination, canonical URLs, explicit HTML labels, closed contracts, and
forecast-API compatibility. The opt-in PostgreSQL test inserts a dossier, a
forecast, and a deliberately invalid-as-public private human record; the public
repository must return exactly the dossier and forecast. Deployment acceptance
also reconciles the rendered row count to direct production table counts and
rechecks that public admin/health routes remain absent.
