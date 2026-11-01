# Runbook ID: RB-PG-FAILOVER-002
## Title: PostgreSQL Primary Failover and Storage Recovery
## Target Services: postgres
## Automation Policy: HUMAN_ONLY_STRICT

### 1. Scope & Safety Restriction
- **CRITICAL:** This procedure is strictly `HUMAN_ONLY`. The OpsPilot AI agent must NEVER propose automated failover or storage volume manipulation.

### 2. Symptoms
- Complete PostgreSQL service unreachability or corrupted WAL segments.

### 3. Human Operator Steps
1. Verify infrastructure storage volume health and network reachability.
2. Execute manual backup verification and controlled replica promotion by senior SRE/DBA.
3. Coordinate with Developer A to verify Alembic schema revision and application data integrity after restore.
