# OpsPilot — Task Board

Status values: `Backlog` | `Ready` | `In Progress` | `Blocked` | `In Review` | `Done`.

| Task ID | Phase | Title | Accountable Owner | Collaborator | Dependencies | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **P0-T1** | Phase 0 | Baseline contracts, collaboration charter, task board, and `.env.example` | Rasool | Mohammad | None | `Done` |
| **P0-T2** | Phase 0 | Core architecture doc, implementation plan, `README.md`, `.gitignore`, and ADR-0001 | Rasool | Mohammad | P0-T1 | `Done` |
| **P1-T1** | Phase 1 | FastAPI skeleton, `pyproject.toml`, Pydantic config, `/health`, SQLAlchemy session, unit tests | Rasool | — | P0-T2 | `Done` |
| **P1-T2** | Phase 1 | Hardened Dockerfile, `docker-compose.yml` (Postgres + App), health checks, resource limits | Mohammad | — | P0-T2 | `Done` |
| **P1-T3** | Phase 1 | GitHub Actions CI workflow, `CODEOWNERS`, and PR template | Mohammad | Rasool | P1-T1, P1-T2 | `Done` |
| **P2-T1** | Phase 2 | Incident/Alert SQLAlchemy models, Alembic migration `0001`, idempotent repository | Rasool | — | P1-T1, P1-T2 | `Done` |
| **P2-T2** | Phase 2 | Disposable e-commerce simulator service with DB pool exhaustion scenario | Mohammad | — | P1-T2 | `Done` |
| **P3-T1** | Phase 3 | Bounded telemetry tools, mock/HTTP adapters, and log sanitization | Rasool | — | P2-T1 | `Done` |
| **P3-T2** | Phase 3 | Prometheus, Alertmanager, alert rules, and contract alignment tests | Mohammad | — | P2-T2, P3-T1 | `Done` |
| **P4-T1** | Phase 4 | Stateful RCA investigation graph, epistemic schemas, bounded loops, and graph tests | Rasool | — | P3-T1 | `Done` |
| **P5-T1** | Phase 5 | RCA artifact persistence, Alembic migration `0002`, incident APIs, and safe resume | Rasool | — | P4-T1 | `Done` |
| **P6-T1** | Phase 6 | LangSmith trace correlation, labeled dataset, and 8-metric evaluation suite | Rasool | — | P4-T1 | `Done` |
| **P7-T1** | Phase 7 | Remediation policy catalog, human approval workflow, Alembic `0003`, fresh verification | Rasool | Mohammad | P5-T1 | `Done` |
| **P8-T1** | Phase 8 | Alertmanager webhook ingestion, correlation, staleness checks, and webhook secret auth | Rasool | Mohammad | P3-T2, P5-T1 | `Done` |
| **P9-T1** | Phase 9 | Operational runbooks, RAG retrieval with source attribution, gap disclosure, injection defense | Rasool | Mohammad | P4-T1 | `Done` |
| **P10-T1** | Phase 10 | Incident lifecycle view, RCA report endpoint, and XSS-safe operator HTML UI | Rasool | — | P7-T1, P9-T1 | `Done` |
| **P10-T2** | Phase 10 | Grafana incident dashboard and telemetry exposure review | Mohammad | — | P3-T2, P10-T1 | `Done` |
| **P11-T1** | Phase 11 | Structured secret-redacting logger, data/graph docs, and app/AI security tests | Rasool | — | P10-T1 | `Done` |
| **P11-T2** | Phase 11 | Deployment, backup/restore, troubleshooting docs, and infra readiness tests | Mohammad | — | P10-T2 | `Done` |
| **P12-T1** | Phase 12 | End-to-end MVP scenario test, testing guide, and post-MVP capabilities ADR-0002 | Rasool | — | P11-T1, P11-T2 | `Done` |
| **P12-T2** | Phase 12 | Automated MVP readiness verification script and final task board completion | Mohammad | Rasool | P12-T1 | `Done` |