# OpsPilot — Telemetry Pipeline Contracts and Exposure Review

## 1. Approved Scrape & Metric Boundaries
Prometheus scrapes `ecomm-simulator:8001/metrics` every 10s and evaluates `monitoring/alert_rules.yaml` every 15s. Only the following 4 metrics are exposed to OpsPilot tools:
- `http_requests_5xx_rate` (unit: `ratio`)
- `http_request_latency_p95` (unit: `ms`)
- `pg_stat_activity_active_connections` (unit: `connections`)
- `pg_pool_wait_time_ms` (unit: `ms`)

## 2. Telemetry Exposure Review (Phase 10 Security Gate)
1. **Network Binding:** Prometheus (`9090`), Alertmanager (`9093`), and Simulator (`8001`) ports are bound strictly to `127.0.0.1` in `docker-compose.yaml` so telemetry endpoints are never exposed to public interfaces.
2. **Credential Stripping in UI Links:** Dashboard URLs rendered in the Incident UI strip any `user:password@` segments via `sanitize_dashboard_base_url` before presentation.
3. **Hidden Ground Truth:** Simulator `/metrics` and `/telemetry/logs` never expose internal scenario names or root-cause flags.
4. **Bounded Retention:** Prometheus TSDB retention is capped at `24h` (`--storage.tsdb.retention.time=24h`) to prevent unbounded disk exhaustion.