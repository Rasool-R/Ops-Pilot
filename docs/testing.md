# OpsPilot — Testing Strategy and Quality Gates

**Application, Database, Graph & Security Tests Owner:** Rasool  
**CI Pipeline & Infrastructure Config Validation Owner:** Mohammad

## 1. Test Suite Architecture
- `tests/unit/`: Fast deterministic tests for configuration bounds, secret masking, telemetry tools, log/runbook sanitization, remediation policy, and evaluators.
- `tests/database/`: SQLAlchemy ORM schema, foreign keys, idempotency constraints, alert correlation, and Alembic migration verification.
- `tests/graph/`: Stateful LangGraph investigation workflow, evidence grounding, hypothesis refutation, loop bounds (`max_steps`), and uncertainty handling (`INCONCLUSIVE`).
- `tests/integration/`: FastAPI routers (`/incidents`, `/approvals`, `/alerts/webhook`), pagination, safe workflow resume, and HTML UI inspection.
- `tests/security/`: Secret redaction in structured logs, XSS prevention in HTML UI, burst-idempotency resilience, and localhost port binding checks.
- `tests/scenarios/`: Full end-to-end product flow connecting the disposable e-commerce simulator with OpsPilot ingestion, RCA, approval, remediation, and fresh-telemetry recovery verification.

## 2. Running the Verification Suite Locally
```bash
ruff check app evaluation tests scripts
mypy app evaluation tests scripts
pytest -v
python -m evaluation.run_eval
```

## 3. Mandatory CI Quality Gates
1. Zero Ruff lint or formatting violations.
2. Strict Mypy static type verification across all packages.
3. All unit, database, graph, integration, security, and scenario tests pass.
4. Zero safety violations (`total_safety_violations == 0`) on the labeled evaluation suite.