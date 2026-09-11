# Phase 18 — deterministic forensics and evidence layer

> **Status:** Complete on `phase-18-forensics-evidence`; pending merge checkpoint.

## Direction and order

Phase 18 keeps the existing SEC acquisition, content-addressed storage, evidence
identity, append-only publication, and local-model boundaries. Work is intentionally
incremental:

1. Formalize source authority/quality at the evidence boundary.
2. Add an EdgarTools adapter evaluation and equivalence fixtures without replacing
   the current SEC provider. Integrate only a demonstrated parsing improvement.
3. Add deterministic numerical claim verification and filing-to-filing diffs.
4. Add primary-source forensic detectors with explicit `UNKNOWN`, `NOT_ASSESSED`,
   and `INSUFFICIENT_EVIDENCE` states.
5. Add tier-0 qualification and resource-aware escalation reasons around the existing
   worker; preserve Qwen as the tier-2 analyst and keep Gemma disabled.
6. Extend private/public-safe dossier provenance and define the next outcome-science
   phase without claiming predictive performance.

The ordering makes source lineage and deterministic checks prerequisites for any
future triage or critic model. No model may replace arithmetic, identity, quote,
provenance, or source-authority checks.

## Upstream review (2026-08-26)

| Project | Current upstream observation | License | Kalki decision |
| --- | --- | --- | --- |
| [EdgarTools](https://github.com/dgunning/edgartools) | v5.9.1 tag; SEC/XBRL, 8-K, Form 3/4/5, 13F and ADV helpers; broad dependency set | MIT | Evaluate behind an adapter; do not replace current SEC client or storage yet |
| [PennyTune](https://github.com/lavellehatcherjr/pennytune) | MIT research tool with deterministic micro-cap/forensic concepts | MIT | Reimplement narrowly in Kalki contracts; copy concepts, not code |
| [sec-analyzer-ai](https://github.com/authorturker/sec-analyzer-ai) | MIT bot; useful filing comparison and numeric-grounding ideas, but optional cloud APIs are outside Kalki’s core | MIT | Use concepts only; no OpenRouter/cloud dependency |
| [reverse-quant](https://github.com/zostaff/reverse-research-funds) | v5.3.3; tiered polling/enrichment, temporal diff and hostile-review concepts; Anthropic-oriented | MIT | Adopt stage boundaries and replayability, not its provider/runtime |
| [yuclaw-brain](https://github.com/YuClawLab/yuclaw-brain) | Apache-2.0 evidence-first, hash-anchored forward-validation methodology | Apache-2.0 | Apply to a later outcome-science phase; do not copy its large-model stack |
| [LangAlpha](https://github.com/ginlix-ai/LangAlpha) | Apache-2.0 provenance panel and deterministic tool-use concepts; broad agent stack | Apache-2.0 | Build small Kalki-native provenance projections; no framework adoption |

The upstream licenses permit concept study and adapter work, but no upstream code
is copied in this phase. `sec-analyzer-ai` and `reverse-quant` document paid/cloud
capabilities; those remain explicitly excluded from Kalki’s $0 core.

## Current implementation slice

`SourceClass` remains the factual source taxonomy. A new explicit quality grade is
derived deterministically from it and retained on source documents and analyst
evidence. A lower-authority source can support discovery, but it cannot silently
outweigh contradictory primary evidence. Missing source material remains unknown;
quality is not an AI confidence score.

The numerical-verification contract in `quantitative/claim_verification.py` records
claim/evidence identifiers, claimed and independently extracted values, explicit
tolerance, source hash, calculation version, and one of `VERIFIED`, `CONFLICTING`,
or `UNVERIFIABLE` (with the broader `PARTIALLY_VERIFIED` status reserved for
multi-component claims). Analyst finding literals are now checked against their
exact cited SEC quotations and carried into both the candidate verifier package and
the immutable radar brief. Conflicting results fail closed before publication;
unavailable values remain explicitly unverifiable.

`providers/sec/edgartools_adapter.py` is an isolated, parser-neutral adapter. Its
equivalence fixture converts a representative EdgarTools-shaped filing view into
the existing `SecFilingRecord` and asserts byte-for-byte-equivalent identity and
lineage to the current normalizer. EdgarTools is not installed or invoked by the
production provider; migration remains gated on broader form/XBRL equivalence and
dependency review.

The filing-diff primitive is available in `forensics/filing_diff.py`. It compares
bounded named sections, ignores whitespace-only edits, emits added/removed/modified
changes, and retains both accession numbers and source hashes. It performs no
semantic interpretation; later model calls may receive only selected changed
sections after deterministic filtering.

The initial `forensics/detectors.py` slice adds pure, bounded indicators for share
count growth, cash-versus-current-liabilities pressure, going-concern language,
and reverse-split language. Each result carries source IDs and an explicit status;
missing facts produce `UNKNOWN` or `NOT_ASSESSED`, never a neutral/safe result.
The detectors are fixture-tested but are not yet enabled in production
qualification; that integration is reserved for the tier-0 gate after broader
fact-mapping equivalence is established.

`forensics/tiers.py` now provides a deterministic routing contract for Tier 0
noise elimination, Tier 1 ambiguity, Tier 2 primary analysis, and Tier 3
publication review. It records an explicit escalation reason and bounded context
size. This is a replayable decision primitive only; the live worker remains on its
proven Qwen path until tier fixtures and queue/backpressure integration are
accepted.

The worker now invokes this routing decision immediately after bounded SEC
extraction. Tier-0 filings are skipped before any analyst model call; relevant
filings retain the existing Qwen path. This preserves current production behavior
while making the first resource-aware boundary explicit and testable.

`quantitative/xbrl_claims.py` adds a deterministic same-accession XBRL matcher for
numeric claims. A unique fact can be `VERIFIED`; multiple matching contexts are
`PARTIALLY_VERIFIED`; missing facts remain `UNVERIFIABLE`. It is an isolated
primitive until the worker's SEC companyfacts acquisition is extended to supply
the relevant facts at publication time.

`providers/sec/sections.py` adds a bounded heading-based HTML section mapper,
with deterministic fixtures for section boundaries and preamble handling. It is
compatible with the existing `FilingSnapshot`/diff contracts and provides the
section-level equivalence surface needed for future EdgarTools comparison, without
changing SEC acquisition or parser ownership.

## Acceptance

All Phase 18 focused slices and the full repository gate pass. The final run
reported 283 passed and 2 intentionally skipped opt-in PostgreSQL tests; Ruff and
strict mypy pass. No database schema, production container, model configuration,
public route, or Discord behavior changed. XBRL matching and section mapping are
available as deterministic primitives, while their production acquisition wiring
is explicitly reserved for the next phase to avoid broad unreviewed ingestion
changes.

## Boundaries and non-goals

- No live provider, model, account, paid service, or public hostname is added.
- EdgarTools is not installed in production by this slice.
- No price data, convergence score, or predictive claim is fabricated.
- Outcome calibration and forward statistical reporting are reserved for a later
  phase after real point-in-time observations are available.
