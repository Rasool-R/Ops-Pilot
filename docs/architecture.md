# OpsPilot — System Architecture

## 1. End-to-End Product Flow
```text
Alert source
  → Validation & normalization
  → Idempotent incident persistence (PostgreSQL)
  → LangGraph investigation workflow
  → Bounded telemetry tools (Prometheus / Logs / Traces / Mocks)
  → Evidence records, hypotheses & targeted diagnostics
  → Root-Cause Analysis (RCA) assessment
  → Predefined remediation proposal
  → Independent deterministic policy check
  → Human approval (when required)
  → Restricted execution in disposable environment
  → Fresh-telemetry recovery verification
  → Structured incident report & immutable audit history
```

## 2. Epistemic Boundaries in Agent Reasoning
Every investigation step and incident report must strictly separate:

1. **Observed Facts**: Verifiable data points returned by bounded telemetry tools with timestamps and source metadata.

2. **Hypotheses / Inferences**: Candidate explanations linking observed facts, annotated with confidence and supporting/contradicting evidence IDs.

3. **Recommendations / Actions**: Proposed diagnostic steps or allowlisted remediation actions.

4. **Unknowns & Uncertainty**: Missing signals, failed tool calls, or ambiguous patterns. When evidence is insufficient, the agent must report uncertainty and propose a bounded next diagnostic rather than guessing.

## 3. Data Architecture & Source-of-Truth Boundaries (Owned by Developer A)
OpsPilot maintains strict separation between five data categories:

1. **Business & Lifecycle Data (PostgreSQL Relational Tables — Source of Truth)**:
incidents, alerts, evidence_records, hypotheses, diagnostic_runs, remediation_proposals, approval_decisions, action_executions, verification_results, incident_reports.

2. **Audit History (audit_events Append-Only Table — Source of Truth for Compliance)**:
Immutable records of state transitions, policy decisions, approvals, and action executions.

3. **LangGraph Checkpoints (Execution State Only)**:
Used strictly to pause and resume interrupted graph workflows. Checkpoints are never the primary record of business state, and resuming a checkpoint must check business-table idempotency keys so remediation actions are never duplicated.

4. **Temporary Diagnostic Data**:
Transient in-memory or bounded scratchpad state during a single node execution.

5. **External Telemetry References**:
Raw high-volume metrics, logs, and traces remain in Prometheus/log backends. PostgreSQL stores only bounded summaries, time windows, and source references.

## 4. Security & Remediation Guardrails
- No unrestricted shell, arbitrary Python execution, raw SQL writes, or raw LLM-generated PromQL queries are exposed to the agent.

- The LLM only proposes actions from a predefined catalog; an independent deterministic policy engine validates targets, parameters, preconditions, approval status/expiry, and idempotency keys immediately prior to execution.

- Telemetry outputs and runbook snippets are treated as untrusted data and sanitized against prompt injection.