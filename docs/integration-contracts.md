# OpsPilot — Shared Integration Contracts

All cross-component interfaces must be strictly typed, bounded, validated, and versioned.

## 1. Alert Ingestion & Incident State Contract

### 1.1 Alert Payload (Normalized Input)
- `alert_fingerprint` (str, required): Deterministic hash identifying the alert class and target.
- `service_id` (enum, required): One of `frontend`, `api-gateway`, `order-service`, `payment-service`, `inventory-service`, `postgres`.
- `severity` (enum, required): `CRITICAL` | `HIGH` | `WARNING` | `INFO`.
- `StartsAt` (UTC datetime, required) and `EndsAt` (UTC datetime, optional).
- `labels` (dict[str, str], bounded) and `annotations` (dict[str, str], bounded).

### 1.2 Distinct Incident State Machines
Do not merge lifecycle states into a single generic status field:
1. `incident_status`: `OPEN` | `INVESTIGATING` | `MITIGATING` | `RESOLVED` | `CLOSED`
2. `investigation_status`: `PENDING` | `RUNNING` | `COMPLETED` | `INCONCLUSIVE` | `FAILED`
3. `approval_status`: `NOT_REQUIRED` | `PENDING_APPROVAL` | `APPROVED` | `REJECTED` | `EXPIRED`
4. `remediation_execution_status`: `NOT_STARTED` | `EXECUTING` | `SUCCEEDED` | `FAILED` | `ROLLED_BACK`
5. `recovery_verification_status`: `PENDING` | `VERIFYING` | `VERIFIED_RECOVERED` | `VERIFICATION_FAILED` | `ESCALATED`

## 2. Bounded Telemetry Tool Contract

Raw LLM-generated PromQL or arbitrary log queries are strictly prohibited.

### 2.1 Telemetry Query Input
- `service_id` (enum): Allowed target service identifier.
- `metric_name` (enum): Pre-approved metric key (e.g., `http_requests_5xx_rate`, `http_request_latency_p95`, `pg_stat_activity_active_connections`, `pg_pool_wait_time_ms`).
- `start_time_utc` (datetime) and `end_time_utc` (datetime): Maximum window 60 minutes per call.
- `step_seconds` (int): Minimum 15 seconds.
- `limit` (int): Maximum 100 data points per response.

### 2.2 Telemetry Query Output
- `source` (str): `prometheus` | `log_backend` | `mock`
- `service_id` (str)
- `metric_name` (str)
- `unit` (str): e.g., `req/s`, `ms`, `connections`, `ratio`
- `collected_at_utc` (datetime)
- `truncated` (bool)
- `series` (list[DataPoint]): Bounded to `TELEMETRY_MAX_PAYLOAD_BYTES`.
- `error` (StructuredTelemetryError | None): `error_code`, `message`, `retryable`.

## 3. Remediation & Authorization Contract

### 3.1 Remediation Action Proposal Schema
- `action_id` (UUID)
- `incident_id` (UUID)
- `action_type` (enum): Allowlisted catalog item (e.g., `reset_db_connection_pool`, `restart_service_container`).
- `target` (str): Validated target service identifier.
- `parameters` (dict): Validated against action-specific Pydantic schema.
- `risk_level` (enum): `LOW` | `MEDIUM` | `HIGH` | `CRITICAL`
- `preconditions` (list[str]): Verifiable system state checks.
- `requested_by` (str)
- `approval_status` (enum)
- `idempotency_key` (str, unique)