# ADR 0016 — Editorial evidence observatory without a client framework

## Status

Accepted on 2026-08-25 UTC.

## Context

The Phase 15 public radar was accurate and secure, but its dark, card-heavy layout
looked like a generic software dashboard. It did not give Kalki a memorable identity,
make the evidence pipeline tangible, or use the quiet/live worker states as part of
the product experience. A redesign could not add fabricated prices, activity, maps,
or security blips, and it could not weaken the script-free public boundary.

## Decision

Adopt **The Evidence Observatory**: a warm editorial research folio crossed with a
restrained mission instrument. Use original repository-native SVG identity assets,
large editorial typography, marginal folio annotations, ruled registers, semantic
color, an explicitly non-quantitative CSS radar, and dossier-style evidence and
lineage views.

Every labelled radar blip maps to one real immutable brief and uses classification
only for color. Its angle and distance, the sweep, rings, and grid encode no market
quantity. Empty mode contains no security blips. Worker state, UTC times, queue depth,
publication count, model, and Discord readiness continue to come only from the
public-safe snapshot.

Implement the experience with server-rendered semantic HTML, one CSS file, SVG/PNG
brand assets, native forms, meters, details, and links. Add no client framework,
JavaScript, tracker, third-party font, CDN, or hotlinked image. Preserve
`script-src 'none'`, keyboard focus, reduced motion, touch-responsive layouts, and
the existing hostname and route boundaries.

## Consequences

The public site gains a distinct brand, a signature living instrument, a readable
signal register, inspectable pipeline, and evidence-first dossiers while remaining
small and progressively enhanced. Decorative placement must remain labelled forever;
future quantitative encodings require their own documented legend and data contract.
The social-preview PNG is generated locally from the tracked original SVG, so it adds
about 100 KiB to the image but is not loaded during ordinary page visits.
