# OpsPilot — PostgreSQL Data Model and Retention Policy

## 1. Relational Entities & Idempotency Constraints
1. `incidents`: Core lifecycle entity with 5 separate state machines (`incident_status`, `investigation_status`, `approval_status`, `remediation_execution_status`, `recovery_verification_status`).
2. `alerts`: Linked to `incidents.id` (`ON DELETE CASCADE`), enforced by unique `idempotency_key`.
3. `evidence_records`: Bounded telemetry observations enforced by `uq_evidence_incident_fact` (`incident_id`, `fact_id`).
4. `hypotheses`: Candidate RCA hypotheses enforced by `uq_hypothesis_incident_hyp` (`incident_id`, `hypothesis_id`).
5. `diagnostic_runs`: Executed bounded tool records enforced by `uq_diagnostic_incident_step` (`incident_id`, `step_id`).
6. `remediation_proposals`: Allowlisted action proposals enforced by unique `idempotency_key`.
7. `approval_decisions`: Human operator approval/rejection records with explicit `expires_at_utc`.
8. `action_executions`: Executed remediation records enforced by unique `idempotency_key` and `rollback_plan`.
9. `verification_results`: Post-remediation fresh-telemetry verification outcomes.
10. `incident_reports`: Final structured JSON & summary RCA report (`unique` per `incident_id`).
11. `audit_events`: Append-only compliance log for every state transition and policy check.

## 2. Source-of-Truth & Checkpoint Boundary
- Relational PostgreSQL tables are the sole source of truth for business state and audit history.
- LangGraph state/checkpoints are used strictly for workflow resumability and never replace relational records.
- Raw high-volume logs and metric time series are never stored unbounded in PostgreSQL; only bounded summaries and source references are persisted.