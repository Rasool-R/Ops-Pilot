# Runbook ID: RB-PG-POOL-001
## Title: PostgreSQL Connection Pool Exhaustion on order-service
## Target Services: order-service, postgres
## Automation Policy: ALLOWLISTED_WITH_HUMAN_APPROVAL

### 1. Symptoms & Telemetry Signatures
- `http_requests_5xx_rate` on `order-service` exceeds `0.05` (5%).
- `http_request_latency_p95` on `order-service` exceeds `1000ms`.
- `pg_stat_activity_active_connections` on `postgres` reaches `>= 95` connections.
- `pg_pool_wait_time_ms` on `order-service` spikes above `1000ms`.
- Application logs contain `QueuePool limit of size 100 overflow 0 reached`.

### 2. Verification Preconditions
1. Confirm `payment-service` and `inventory-service` 5xx rates are normal (`< 0.05`).
2. Confirm `pg_stat_activity_active_connections >= 95` via bounded Prometheus metric tool.

### 3. Approved Automated Remediation Procedure
- **Action Type:** `reset_db_connection_pool`
- **Target Service:** `order-service`
- **Approval Requirement:** Mandatory human SRE approval (`requires_human_approval=True`).
- **Expected Recovery Signal:** Within 5 minutes of execution, fresh telemetry must show `http_requests_5xx_rate < 0.05` and `pg_pool_wait_time_ms < 100ms`.

### 4. Human-Only Escalation Procedure (DO NOT AUTOMATE)
- If fresh telemetry still breaches thresholds after `reset_db_connection_pool`, escalate immediately to the on-call DBA.
- Human DBA manually inspects long-running transactions in `pg_stat_activity` and tunes `max_connections` or PgBouncer limits.
