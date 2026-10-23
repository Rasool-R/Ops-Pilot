# OpsPilot — Team Ownership and Collaboration Charter

## 1. Ownership Boundaries

### Rasool — AI, Backend, and PostgreSQL Application Engineering
- **AI & LangGraph:** State schema, nodes, conditional routing, prompts, structured outputs, bounded tools, RAG/runbooks, LangSmith tracing, and AI evaluation suite.
- **Backend Application:** FastAPI routers, Pydantic domain schemas, incident lifecycle services, approval workflows, remediation orchestration, and incident reporting.
- **PostgreSQL Application Engineering (Final Owner):** Relational schema semantics, tables, foreign keys, constraints, indexes, SQLAlchemy ORM models, repositories, transactions, concurrency/idempotency rules, Alembic migrations, retention rules, DB integration tests, and LangGraph checkpointer persistence design.

### Mohammad — DevOps, SRE, and Infrastructure
- **Containers & Runtime:** Dockerfile, Docker Compose, container networking, ports, health checks, resource limits, and local/staging deployment scripts.
- **Observability & Telemetry Pipeline:** Prometheus, Alertmanager, alert routing rules, log/trace infrastructure, simulator service deployment, and monitoring OpsPilot itself.
- **CI/CD & Infrastructure Security:** GitHub Actions workflows, dependency/image scanning, secret injection, network isolation, and operational runbooks.
- **PostgreSQL Service Operations Only:** Container deployment, volumes/storage, network reachability, service health checks, infrastructure metrics, and backup/restore operations.
  - *Constraint:* Mohammad must not independently modify application tables, SQLAlchemy models, repositories, or Alembic migrations.

## 2. Branching and Pull Request Rules
1. Never push directly to `main`. Use task-scoped branches (`feature/<scope>-<short-name>`, `fix/<scope>-<short-name>`, `docs/<scope>-<short-name>`).
2. Every Pull Request must reference a Task ID from `docs/task-board.md` and include actual test output.
3. Shared contracts (`docs/integration-contracts.md`), remediation policies, and database schema migrations require coordination prior to merging.