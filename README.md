# OpsPilot — Stateful Agentic AIOps Platform

OpsPilot is a stateful incident-management and root-cause analysis (RCA) platform designed for alert ingestion, bounded evidence collection, hypothesis-driven diagnostics, policy-controlled remediation, fresh-telemetry recovery verification, and auditable incident reporting.

## 1. Core Principles
- **Stateful Incident Lifecycle:** Tracks distinct state machines for incident lifecycle, investigation, approval, remediation execution, and recovery verification.
- **Strict Epistemic Separation:** Keeps **observed telemetry facts**, **hypotheses/inferences**, **recommendations/actions**, and **unknowns/uncertainty** explicitly separate.
- **Safety & Policy First:** The LLM proposes actions but never authorizes them. All production-impacting actions require deterministic policy validation and explicit human approval.
- **Verified Recovery:** Action execution is never treated as proof of recovery; recovery requires verification against fresh telemetry.

## 2. Team Ownership Boundaries
- **Rasool (Developer A) — AI, Backend, and PostgreSQL Application Engineering:**
  Owns LangChain/LangGraph orchestration, prompts, bounded tools, RAG/runbooks, LangSmith evaluations, FastAPI services, domain schemas, and all PostgreSQL application engineering (schema semantics, SQLAlchemy models, repositories, transactions, idempotency, Alembic migrations, and checkpointer integration design).
- **Mohammad (Developer B) — DevOps, SRE, and Infrastructure:**
  Owns Docker/Compose, container hardening, Prometheus/Alertmanager, telemetry pipeline health, simulator infrastructure, GitHub Actions CI/CD, secret management, and PostgreSQL service operations only (deployment, volumes, networking, health checks, backups).

## 3. Target MVP Scenario
- **Simulated Topology:** `frontend`, `api-gateway`, `order-service`, `payment-service`, `inventory-service`, and `postgres`.
- **Synthetic Incident:** Elevated HTTP `5xx` responses and latency spikes triggered by PostgreSQL connection-pool exhaustion (with ground truth hidden from the agent).

## 4. Repository Structure
See `docs/architecture.md` for component boundaries and `docs/implementation-plan.md` for phase gates.

## 5. Quick Start
1. Copy `.env.example` to `.env` and populate local non-production placeholders.
2. Start infrastructure services (once Phase 1 Compose files are verified).
3. Run database migrations and test suites via `pytest`.

## 6. Documentation Index
- [Architecture Overview](docs/architecture.md)
- [Implementation Plan & Roadmap](docs/implementation-plan.md)
- [Team Collaboration Charter](docs/collaboration.md)
- [Shared Integration Contracts](docs/integration-contracts.md)