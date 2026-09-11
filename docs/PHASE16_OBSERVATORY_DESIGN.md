# Phase 16 observatory design direction

## Concept

**The Evidence Observatory** combines an editorial research folio with a restrained
mission instrument. Warm paper is the default reading surface; midnight indigo
provides authority and structure. Cobalt means interaction, jade means accepted
opportunity-side research, vermilion means risk, and saffron means processing,
waiting, or uncertainty. Violet is reserved for model lineage.

The interface avoids the generic dashboard frame. It uses editorial columns,
rules, folio numbers, marginal annotations, large typographic identifiers, and one
signature circular instrument instead of a field of interchangeable cards.

## Reference synthesis

- [Reuters Graphics](https://reutersagency.com/content/content-types/graphics/): let
  the evidence choose the form; annotate context close to the visual rather than
  requiring a presenter.
- [NASA Open MCT](https://nasa.github.io/openmct/about-open-mct/) and
  [crew-interface guidance](https://www.nasa.gov/reference/10-0-crew-interfaces-vol-2/):
  show synchronized time, state, and health without requiring mental calculation;
  distinguish operational modes.
- Interactive editorial visualization: build one memorable visual thesis and use
  progressive disclosure instead of a dense dashboard.
- [Observable's dashboard guidance](https://observablehq.com/blog/seven-ways-design-better-dashboards):
  overview first, then filter, then details on demand; color is semantic and
  consistent rather than decorative.

No visual, layout, logo, font, or asset is copied from those products.

## Signature instrument

The observatory is CSS and inline SVG/HTML, with no canvas library or framework.
Its visual variables are deliberately narrow:

- every labelled blip is one real published filing brief;
- blip color is its real classification;
- blip label is its real ticker or `CIK` fallback;
- the sweep and orbital ticks are decorative system motion only;
- blip angle and distance are collision-avoiding layout positions and encode no
  price, geography, return, confidence, or ranking;
- counts, worker state, timestamps, queue depth, model, and Discord state come from
  the public-safe worker snapshot;
- when no briefs exist, the instrument says that it is a calibration field and
  renders no security blips.

The instrument becomes still under `prefers-reduced-motion`. On small screens it
becomes a compact square and moves below the status summary without shrinking text
below readable sizes.

## Dossier language

Research results are a numbered signal register, not blog cards. Detail pages label
four epistemic layers explicitly:

1. `Model interpretation` — validated qualitative synthesis.
2. `Deterministic measure` — ordinary-code research-priority points.
3. `Normalized source excerpt` — model-cited text from the deterministic filing
   excerpt, with source/document hashes.
4. `Boundary` — limitations, unavailable price data, and research-only disclosure.

The evidence chronology uses actual filed, retrieved, and published UTC times.

## Motion and interaction

Motion communicates state: a slow sweep while running, a quiet breathing center
while idle, amber calibration while waiting, and a stopped high-contrast marker
when degraded. Pipeline connectors carry a subtle pulse. Links and dossier rows use
short physical translations and rule changes. All meaning remains available without
motion, hover, or JavaScript.

## Performance budget

- no frontend framework;
- no third-party fonts, images, scripts, trackers, or CDN requests;
- one CSS file, original SVG marks, server-rendered HTML;
- no autoplay media and no layout-shifting late content;
- public CSP keeps `script-src 'none'`.
