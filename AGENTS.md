# Repository Instructions

- Work incrementally and stop after the requested milestone.
- Read `README.md`, `ARCHITECTURE.md`, `ROADMAP.md`, and relevant files under `docs/` before changing the project.
- Explain important commands and decisions in plain language for a beginner.
- Preserve user changes and Git history. Never perform destructive system, repository, or disk actions without explicit approval.
- Ask before decisions affecting cost, privacy, security, public exposure, or destructive operations.
- Never create paid resources or external accounts, or expose a service publicly, without explicit approval.
- Never hard-code or commit secrets. Keep local data, models, logs, exports, and backups out of Git.
- Never implement automatic trading or brokerage connectivity.
- Never fabricate market data, financial figures, sources, filings, quotations, URLs, or evidence.
- Store timestamps in UTC internally and preserve publication, retrieval, and availability times.
- Prevent look-ahead and survivorship bias in schemas, ingestion, signals, predictions, and evaluation.
- Use deterministic, tested code for calculations; do not delegate arithmetic or financial metrics to an LLM.
- Treat AI output as untrusted: require validated structured schemas and evidence references.
- Isolate dependencies with containers, `uv`, or another project environment; do not modify the system Python.
- Run relevant tests before declaring a milestone complete.
- Keep detailed product requirements in `docs/PROJECT_SPEC.md` and update documentation when approved decisions change.

## Persistent autonomous execution

When the user requests continuous roadmap execution, maintain the living
`.agent/KALKI_EXECPLAN.md`. Treat commits, checkpoints, phase merges, and branch
creation as internal milestones; continue to the next justified milestone without
pausing for routine status. Update the plan with the exact resume point before any
usage-limit interruption.

## Autonomous Roadmap Execution

When the user explicitly authorizes roadmap-wide autonomous execution:

- Proceed phase-by-phase without pausing for routine implementation, dependency, test, or safe Git decisions.
- Use a dedicated phase branch; merge and push `main` only after the phase gates pass. Never force-push or rewrite published `main` history.
- Keep `docs/PROGRESS.md` current with completed work, decisions, verification, blockers, and the next phase.
- Fix recoverable failures and review the complete phase diff before merging.
- Pause only for unavoidable manual authentication, cost or legal acceptance, credentials, destructive disk/data work, irreconcilable requirements, or exhausted usage limits.
- Roadmap-wide authorization never permits secrets in Git, paid resources, automatic trading, unapproved public exposure, or irreversible loss of important data.
