# ADR 0015 — Supervised SEC filing radar before licensed price coverage

## Status

Accepted on 2026-08-25 UTC.

## Context

The deployed application contained strong ingestion, analysis, signal, prediction,
notification, web, and recovery boundaries but no scheduler connecting them. The
database was empty and the website accurately showed no publications. Reviews of
zero-cost market-data vendors did not establish rights for automated public derived
research, so silently using an unofficial quote endpoint would weaken the product's
evidence and licensing rules.

## Decision

Add a continuously supervised, US filing-driven research radar using documented SEC
daily indexes and archive files. Publish a separate immutable `ResearchBrief`
contract with exact quotations, model lineage, deterministic priority scores, and
explicit no-price limitations. Do not represent these briefs as Phase 9 predictions.

Run the existing local model behind a private internal Compose network, mount the
previously reviewed local model store, disable cloud features, and expose no Ollama
port. Persist mutable queues and status separately from append-only publications,
runs, and delivery audits. Automatically hand accepted briefs to the existing safe
Discord webhook boundary.

## Consequences

Kalki now has an honest continuously running research product without adding a paid
resource, account, brokerage connection, or questionable market-data source. It can
surface filing-driven potential and risk, but cannot make price-aware rankings or
outcome-ready predictions until a licensed point-in-time price source is approved.
SEC live activation still requires the operator's monitored contact identity.
