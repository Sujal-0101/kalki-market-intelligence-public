# ADR 0001: Python Repository Foundation

- **Status:** Accepted for Phase 1
- **Date:** 2026-08-21 UTC

## Context

The project needs a small, reproducible foundation for validated contracts before providers, databases, models, APIs, or user-facing features are implemented. The host has Python 3.14, but contributors should not be forced to use that exact newest interpreter.

## Decision

- Support Python 3.12 and newer, before Python 4, using a `src/` package layout.
- Use Pydantic v2 for immutable boundary contracts and Pydantic Settings for environment-based configuration.
- Use pytest for invariant tests, Ruff for formatting/linting, and mypy in strict mode for static type checks.
- Pin direct dependencies in `pyproject.toml` and the complete tested development environment in `requirements-dev.lock`.
- Install into a repository-local `.venv`; never modify system Python.
- Keep domain contracts independent of providers and persistence. PostgreSQL mappings, Alembic, FastAPI, ingestion, AI, and frontend code remain deferred to their roadmap phases.

## Consequences

The project gains strict inputs, JSON Schema export, predictable tooling, and a clean import boundary with few dependencies. Pydantic becomes a core contract dependency and must be upgraded deliberately with schema regression tests. The lock file is currently resolved and tested on Linux with Python 3.14.4; other supported Python versions should be checked in future automation.
