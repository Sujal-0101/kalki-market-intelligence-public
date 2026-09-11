# Tracked Data

Only small, explicitly documented test fixtures belong in this directory. The
`fixtures/sec/` files are synthetic SEC-schema examples: every issuer and value is
invented for deterministic tests and must never be presented as market evidence.
The `fixtures/sedar_plus/` envelope is also wholly synthetic and tests only a
hypothetical future authorized-feed contract; it is not SEDAR+ content or a license.
The `fixtures/market_data/` manifest and bars are invented offline values for
provider contract tests and must never be presented as real prices or actions.
The `fixtures/quantitative/` cases contain small, hand-checkable invented number
series and expected results for calculation tests; they are not market evidence.
The `fixtures/analysis/` cases are invented excerpts and expected structured
analyst output for grounding, contradiction, and injection-defense tests.
The `fixtures/signals/` cases are invented combinations of metric values and
validated findings for exact scoring and label-boundary tests.
The `fixtures/predictions/` case contains invented start/end values for immutable
outcome and benchmark-return tests; it is not a performance record.

All live responses, normalized output, caches, databases, model output, exports,
and other generated research data under `data/` are ignored by Git.
