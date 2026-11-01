# OpsPilot — Security Architecture and Remaining Risk Register

## 1. Security Ownership Split
- **(Application & AI Security):**
  Input validation, typed tool schemas, prompt-injection sanitization for logs and runbooks, credential redaction, independent deterministic policy checks, human approval validation, idempotency enforcement, and immutable audit trails.
- **(Infrastructure & CI Security):**
  Non-root container execution (`USER opspilot`), localhost-bound ports (`127.0.0.1`), resource limits, least-privilege GitHub Actions permissions (`contents: read`), secret injection via environment variables, and backup protection.

## 2. Mandatory Guardrails Enforced in Code
1. **No Unrestricted Execution:** The LLM has zero access to shell commands, arbitrary Python execution, raw SQL writes, or raw PromQL queries.
2. **Independent Authorization:** The LLM only proposes actions from `ACTION_CATALOG`. `app/policies/authorization.py` blocks self-approval (`agent`, `llm`, `system`) and revalidates human approval status and expiration immediately before execution.
3. **Untrusted Data Sanitization:** All log lines (`app/tools/logs.py`) and runbook excerpts (`app/tools/runbooks.py`) are scrubbed for prompt-injection directives and credentials before entering agent state.
4. **XSS & Exposure Protection:** HTML incident views escape all dynamic fields via `html.escape`, and dashboard URL builders strip embedded URL credentials.

## 3. Documented Remaining Risks (MVP Boundary)
- **Authentication & RBAC Integration:** In MVP, human approver identities (`approver_id`) are validated against autonomous-agent blocklists; production rollout requires integrating enterprise OIDC/SSO tokens.
- **In-Process Simulator:** The disposable simulator runs in the same Docker Compose network for deterministic testing; production remediation adapters must use isolated scoped service accounts with network policies.