# Deterministic Signal Engine

> **Status:** Phase 8 completed on 2026-08-21 UTC. These are versioned ordinal
> research rules over validated inputs. They are not probabilities,
> recommendations, return forecasts, or trade instructions.

## Boundary

`SignalEngine` accepts only Phase 6 `MetricResult` values and Phase 7
`ValidatedAnalysis` values with their retrieved evidence. A request fixes the
research subject, allowed metric subjects, as-of date, UTC knowledge cutoff, and
30–180 day horizon. Future inputs, unknown evidence, hash mismatches, duplicate
metrics or roles, and evidence for a different subject fail validation.

Ruleset `1.0.0` produces three separate integer point scales:

- **opportunity** summarizes selected momentum, benchmark-relative,
  fundamental, valuation, technical, catalyst, and bull-case inputs;
- **risk** summarizes volatility, drawdown, leverage, validated risk/bear
  findings, and contradictions; and
- **research confidence** summarizes coverage, cited-source class, analyst-role
  diversity, and unresolved contradiction penalties.

The values are deliberately marked `heuristic_points_not_probability`. They
have not been calibrated against historical outcomes.

## Labels and missing evidence

Critical inputs are momentum, at least one risk metric, validated qualitative
analysis, and cited retrieved evidence. If any is absent—or research confidence
is below 55—the label is **Insufficient evidence** and the risk profile remains
unclassified. Missing benchmark, fundamental, or valuation coverage is reported
and reduces the attainable confidence score.

With sufficient evidence, ruleset 1.0 maps:

- opportunity at least 70, risk at most 35, and confidence at least 70 to
  **Strong opportunity**;
- opportunity at least 55 and risk above 60 to **Speculative opportunity**;
- other opportunity scores at least 55 to **Moderate opportunity**; and
- lower opportunity scores to **Weak opportunity**.

Risk profiles are separate. Low-risk, well-supported results may be
`conservative`; high-opportunity results above 60 risk points are
`aggressive_speculative`; other classified results are `balanced` or
`elevated_risk`. A high opportunity score can therefore never conceal high risk.

## Explanation and reproducibility

Every contribution records a rule ID and version, dimension, integer points,
human-readable explanation, applicable metric names, analyst roles, evidence
IDs, and SHA-256 hashes of the immutable inputs. The result fingerprint hashes
the complete request plus ruleset version. Result validation recalculates each
score from its traces and rejects recommendation or probability wording in rule
explanations.

`data/fixtures/signals/reference-cases.json` contains four wholly invented,
fixed scenarios for conservative, speculative, weak, and insufficient labels.
They are contract tests, not market evidence.

## Limitations

- Version 1 thresholds are explicit engineering heuristics, not empirically
  optimized weights or calibrated statistical estimates.
- The engine does not rank a market universe, predict a price target, persist or
  publish a result, schedule work, or evaluate outcomes.
- Source-class weights describe evidence authority for this initial contract;
  they do not establish truth and discovery-only evidence adds no authority
  points.
- Adding metrics, changing weights, or changing thresholds requires a new
  ruleset version and new fixed reference cases.
