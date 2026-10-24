# ADR 0001: MVP Baseline Architecture, Stack, and Ownership Defaults

- **Status:** Proposed
- **Date:** 2026-10-23
- **Deciders:** Rasool, Mohammad

## Context
OpsPilot requires clear architectural boundaries before Phase 1 implementation begins so that Developer A (AI/Backend/PostgreSQL application engineering) and Developer B (DevOps/SRE/Infrastructure) can work in parallel without schema or contract conflicts.

## Decision
1. **Language & Framework:** Python >= 3.11, FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic, and `pytest` managed via standard `pyproject.toml`.
2. **Database Ownership Split:** Developer A owns all PostgreSQL application schemas, SQLAlchemy models, repositories, transactions, idempotency constraints, and Alembic migrations. Developer B owns PostgreSQL container operations, volumes, health checks, and backup/restore execution.
3. **Business State vs. Graph Checkpoints:** PostgreSQL application tables are the sole source of truth for business state and audit history. LangGraph checkpoints are used solely for workflow resumability.
4. **Telemetry Safety:** All telemetry tools use typed schemas with strict time-window, step, timeout, and payload-size limits. Raw LLM-generated queries are prohibited.
5. **Remediation Safety:** MVP remediation is restricted to an allowlisted catalog (`reset_db_connection_pool`, `restart_service_container`) operating against a disposable simulator environment, gated by an independent policy engine and human approval.

## Consequences
- Enables deterministic local testing using mock telemetry adapters before full Prometheus/Alertmanager integration is online.
- Prevents state corruption or duplicate remediation execution during graph retries.