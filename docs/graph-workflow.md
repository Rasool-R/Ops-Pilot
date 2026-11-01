# OpsPilot — LangGraph RCA Investigation Workflow

## 1. Node Execution Sequence
1. `normalize_incident_node`: Initializes `InvestigationState`, sets status to `RUNNING`, and increments `step_count`.
2. `collect_initial_evidence_node`: Queries bounded 5xx rate, p95 latency, and sanitized logs for the primary alerting service.
3. `formulate_hypotheses_node`: Generates competing hypotheses (`hyp-db-pool-exhaustion` vs. `hyp-payment-service-degradation`) and queues bounded `DiagnosticStep` items.
4. `plan_and_execute_diagnostics_node`: Executes queued metric queries (`pg_pool_wait_time_ms`, `pg_stat_activity_active_connections`, downstream `http_requests_5xx_rate`).
5. `reassess_evidence_node`: Evaluates hypotheses against diagnostic facts, marking each `SUPPORTED`, `REFUTED`, or `INCONCLUSIVE`.
6. `produce_rca_report_node`: Queries approved runbooks (`retrieve_runbooks`), cites matching procedures, and emits a structured `RCAReport`.

## 2. Bounded Loops & Uncertainty Handling
- Execution is strictly bounded by `max_steps` (default `10`) and `max_retries` (default `2`).
- When telemetry tools fail or evidence is ambiguous, the graph transitions to `INCONCLUSIVE`, populates `unknowns_and_uncertainties` and `bounded_next_diagnostic`, and proposes zero remediation actions.