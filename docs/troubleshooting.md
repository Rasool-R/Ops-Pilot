# OpsPilot — Deployment, Backup/Restore, and Operational Runbook

## 1. Reproducible Local Setup
1. Copy `.env.example` to `.env` and set non-production local passwords.
2. Start all services with health checks and resource limits:
   ```bash
   docker compose up --build -d
   ```
3. Apply Alembic migrations:

    ```bash
    alembic upgrade head
    ```
4. Verify service readiness:

    ```bash
    curl [http://127.0.0.1:8000/api/v1/health/ready](http://127.0.0.1:8000/api/v1/health/ready)
    ```
## 2. PostgreSQL Backup and Restore Procedure
### 2.1 Infrastructure Backup
```bash
docker exec -t opspilot-postgres pg_dump -U opspilot_user -d opspilot_db -F c -f /tmp/opspilot_backup.dump
docker cp opspilot-postgres:/tmp/opspilot_backup.dump ./opspilot_backup.dump
```

### 2.2 Infrastructure Restore
```bash
docker cp ./opspilot_backup.dump opspilot-postgres:/tmp/opspilot_backup.dump
docker exec -t opspilot-postgres pg_restore -U opspilot_user -d opspilot_db --clean --if-exists /tmp/opspilot_backup.dump
```

### 2.3 Application Data Consistency Validation
Container startup or pg_restore completion does not prove application schema correctness. Developer A must verify:

1. Current Alembic revision matches head: `alembic current`

2. Readiness probe passes: `GET /api/v1/health/ready` returns `200 OK`

3. Repository integrity tests pass: `pytest tests/database -v`