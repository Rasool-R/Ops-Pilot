"""Typed, bounded telemetry contracts and mock/HTTP adapters."""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol

import httpx
from pydantic import BaseModel, Field, model_validator

from app.config import Settings, get_settings
from app.db.models import ServiceId


class MetricName(StrEnum):
    """Pre-approved metric identifiers (raw LLM-generated PromQL is prohibited)."""

    HTTP_5XX_RATE = "http_requests_5xx_rate"
    HTTP_LATENCY_P95 = "http_request_latency_p95"
    PG_ACTIVE_CONNECTIONS = "pg_stat_activity_active_connections"
    PG_POOL_WAIT_TIME_MS = "pg_pool_wait_time_ms"


METRIC_UNITS: dict[MetricName, str] = {
    MetricName.HTTP_5XX_RATE: "ratio",
    MetricName.HTTP_LATENCY_P95: "ms",
    MetricName.PG_ACTIVE_CONNECTIONS: "connections",
    MetricName.PG_POOL_WAIT_TIME_MS: "ms",
}


class StructuredTelemetryError(BaseModel):
    """Standardized error model when a telemetry backend times out or fails."""

    error_code: str
    message: str
    retryable: bool


class DataPoint(BaseModel):
    """Single timestamped metric observation."""

    timestamp_utc: datetime
    value: float


class TelemetryQueryRequest(BaseModel):
    """Bounded, validated input schema for querying service metrics."""

    service_id: ServiceId
    metric_name: MetricName
    start_time_utc: datetime
    end_time_utc: datetime
    step_seconds: int = Field(default=60, ge=15, le=3600)
    limit: int = Field(default=50, ge=1, le=100)

    @model_validator(mode="after")
    def validate_time_window(self) -> "TelemetryQueryRequest":
        """Enforce chronological order and maximum 60-minute query window."""
        if self.end_time_utc <= self.start_time_utc:
            raise ValueError("end_time_utc must be strictly greater than start_time_utc")
        if (self.end_time_utc - self.start_time_utc) > timedelta(minutes=60):
            raise ValueError("Telemetry query time window cannot exceed 60 minutes")
        return self


class TelemetryQueryResponse(BaseModel):
    """Bounded, source-attributed metric query output."""

    source: str
    service_id: ServiceId
    metric_name: MetricName
    unit: str
    collected_at_utc: datetime
    truncated: bool = False
    series: list[DataPoint] = Field(default_factory=list)
    error: StructuredTelemetryError | None = None


class LogQueryRequest(BaseModel):
    """Bounded input schema for retrieving service logs."""

    service_id: ServiceId
    limit: int = Field(default=20, ge=1, le=100)


class LogEntry(BaseModel):
    """Single structured log line with sanitized message content."""

    timestamp_utc: datetime
    level: str
    service: str
    message: str


class LogQueryResponse(BaseModel):
    """Bounded, source-attributed log query output."""

    source: str
    service_id: ServiceId
    collected_at_utc: datetime
    truncated: bool = False
    logs: list[LogEntry] = Field(default_factory=list)
    error: StructuredTelemetryError | None = None


class TelemetryAdapter(Protocol):
    """Protocol implemented by both real and deterministic mock telemetry backends."""

    def query_metrics(self, req: TelemetryQueryRequest) -> TelemetryQueryResponse:
        """Fetch bounded metric series for a service."""
        ...

    def query_logs(self, req: LogQueryRequest) -> LogQueryResponse:
        """Fetch bounded structured logs for a service."""
        ...


class MockTelemetryAdapter:
    """Deterministic telemetry adapter for unit/graph tests without external infra."""

    def __init__(self, fault_injected: bool = True, simulate_failure: bool = False) -> None:
        self.fault_injected = fault_injected
        self.simulate_failure = simulate_failure

    def query_metrics(self, req: TelemetryQueryRequest) -> TelemetryQueryResponse:
        """Return deterministic metric points matching the e-commerce scenario."""
        now = datetime.now(UTC)
        unit = METRIC_UNITS[req.metric_name]

        if self.simulate_failure:
            return TelemetryQueryResponse(
                source="mock",
                service_id=req.service_id,
                metric_name=req.metric_name,
                unit=unit,
                collected_at_utc=now,
                error=StructuredTelemetryError(
                    error_code="TELEMETRY_TIMEOUT",
                    message="Mock telemetry backend timed out after 5s.",
                    retryable=True,
                ),
            )

        value = self._resolve_metric_value(req.service_id, req.metric_name)
        total_points = min(req.limit, 5)
        truncated = req.limit < 5

        points = [
            DataPoint(
                timestamp_utc=req.end_time_utc - timedelta(seconds=i * req.step_seconds),
                value=value,
            )
            for i in range(total_points)
        ]
        points.reverse()

        return TelemetryQueryResponse(
            source="mock",
            service_id=req.service_id,
            metric_name=req.metric_name,
            unit=unit,
            collected_at_utc=now,
            truncated=truncated,
            series=points,
        )

    def query_logs(self, req: LogQueryRequest) -> LogQueryResponse:
        """Return deterministic log entries matching the e-commerce scenario."""
        now = datetime.now(UTC)
        if self.simulate_failure:
            return LogQueryResponse(
                source="mock",
                service_id=req.service_id,
                collected_at_utc=now,
                error=StructuredTelemetryError(
                    error_code="LOG_BACKEND_UNAVAILABLE",
                    message="Mock log backend connection refused.",
                    retryable=True,
                ),
            )

        raw_logs: list[LogEntry] = []
        if not self.fault_injected:
            raw_logs.append(
                LogEntry(
                    timestamp_utc=now,
                    level="INFO",
                    service=req.service_id.value,
                    message="Request processed within normal SLA thresholds.",
                )
            )
        elif req.service_id == ServiceId.ORDER_SERVICE:
            raw_logs.extend(
                [
                    LogEntry(
                        timestamp_utc=now,
                        level="ERROR",
                        service="order-service",
                        message=(
                            "QueuePool limit of size 100 overflow 0 reached, "
                            "connection timed out, timeout 5.00"
                        ),
                    ),
                    LogEntry(
                        timestamp_utc=now,
                        level="ERROR",
                        service="order-service",
                        message="HTTP 503 returned for POST /orders/checkout",
                    ),
                ]
            )
        elif req.service_id == ServiceId.POSTGRES:
            raw_logs.append(
                LogEntry(
                    timestamp_utc=now,
                    level="WARNING",
                    service="postgres",
                    message="active_connections=100/100; idle_in_transaction sessions held",
                )
            )
        elif req.service_id in (ServiceId.API_GATEWAY, ServiceId.FRONTEND):
            raw_logs.append(
                LogEntry(
                    timestamp_utc=now,
                    level="ERROR",
                    service=req.service_id.value,
                    message="Upstream timeout calling order-service: HTTP 504",
                )
            )
        else:
            raw_logs.append(
                LogEntry(
                    timestamp_utc=now,
                    level="INFO",
                    service=req.service_id.value,
                    message="Service operating normally.",
                )
            )

        truncated = len(raw_logs) > req.limit
        return LogQueryResponse(
            source="mock",
            service_id=req.service_id,
            collected_at_utc=now,
            truncated=truncated,
            logs=raw_logs[: req.limit],
        )

    def _resolve_metric_value(self, service_id: ServiceId, metric: MetricName) -> float:
        """Map service and metric to deterministic healthy or fault values."""
        if not self.fault_injected:
            healthy_map: dict[tuple[ServiceId, MetricName], float] = {
                (ServiceId.ORDER_SERVICE, MetricName.HTTP_5XX_RATE): 0.001,
                (ServiceId.ORDER_SERVICE, MetricName.HTTP_LATENCY_P95): 85.0,
                (ServiceId.ORDER_SERVICE, MetricName.PG_ACTIVE_CONNECTIONS): 12.0,
                (ServiceId.ORDER_SERVICE, MetricName.PG_POOL_WAIT_TIME_MS): 4.0,
                (ServiceId.POSTGRES, MetricName.PG_ACTIVE_CONNECTIONS): 26.0,
                (ServiceId.POSTGRES, MetricName.PG_POOL_WAIT_TIME_MS): 3.0,
            }
            return healthy_map.get((service_id, metric), 0.001)

        fault_map: dict[tuple[ServiceId, MetricName], float] = {
            (ServiceId.FRONTEND, MetricName.HTTP_5XX_RATE): 0.145,
            (ServiceId.FRONTEND, MetricName.HTTP_LATENCY_P95): 1850.0,
            (ServiceId.API_GATEWAY, MetricName.HTTP_5XX_RATE): 0.182,
            (ServiceId.API_GATEWAY, MetricName.HTTP_LATENCY_P95): 2100.0,
            (ServiceId.ORDER_SERVICE, MetricName.HTTP_5XX_RATE): 0.240,
            (ServiceId.ORDER_SERVICE, MetricName.HTTP_LATENCY_P95): 2950.0,
            (ServiceId.ORDER_SERVICE, MetricName.PG_ACTIVE_CONNECTIONS): 100.0,
            (ServiceId.ORDER_SERVICE, MetricName.PG_POOL_WAIT_TIME_MS): 4800.0,
            (ServiceId.POSTGRES, MetricName.PG_ACTIVE_CONNECTIONS): 100.0,
            (ServiceId.POSTGRES, MetricName.PG_POOL_WAIT_TIME_MS): 4900.0,
            (ServiceId.PAYMENT_SERVICE, MetricName.HTTP_5XX_RATE): 0.003,
            (ServiceId.INVENTORY_SERVICE, MetricName.HTTP_5XX_RATE): 0.002,
        }
        return fault_map.get((service_id, metric), 0.0)


class SimulatorHttpTelemetryAdapter:
    """HTTP adapter reading bounded metrics and logs from the live simulator."""

    def __init__(self, base_url: str = "http://localhost:8001", settings: Settings | None = None):
        self.base_url = base_url.rstrip("/")
        self.settings = settings or get_settings()

    def query_metrics(self, req: TelemetryQueryRequest) -> TelemetryQueryResponse:
        """Fetch and parse target metric from Prometheus exposition endpoint."""
        now = datetime.now(UTC)
        unit = METRIC_UNITS[req.metric_name]
        try:
            with httpx.Client(timeout=self.settings.TELEMETRY_TIMEOUT_SECONDS) as client:
                resp = client.get(f"{self.base_url}/metrics")
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            return TelemetryQueryResponse(
                source="prometheus_http",
                service_id=req.service_id,
                metric_name=req.metric_name,
                unit=unit,
                collected_at_utc=now,
                error=StructuredTelemetryError(
                    error_code="HTTP_METRICS_ERROR",
                    message=f"Metrics endpoint failed: {exc.__class__.__name__}",
                    retryable=True,
                ),
            )

        target_prefix = f'{req.metric_name.value}{{service="{req.service_id.value}"}}'
        parsed_val = 0.0
        for line in resp.text.splitlines():
            if line.startswith(target_prefix):
                parts = line.split()
                if len(parts) == 2:
                    parsed_val = float(parts[1])
                break

        return TelemetryQueryResponse(
            source="prometheus_http",
            service_id=req.service_id,
            metric_name=req.metric_name,
            unit=unit,
            collected_at_utc=now,
            truncated=False,
            series=[DataPoint(timestamp_utc=now, value=parsed_val)],
        )

    def query_logs(self, req: LogQueryRequest) -> LogQueryResponse:
        """Fetch structured logs for a service from the simulator HTTP endpoint."""
        now = datetime.now(UTC)
        try:
            with httpx.Client(timeout=self.settings.TELEMETRY_TIMEOUT_SECONDS) as client:
                resp = client.get(
                    f"{self.base_url}/telemetry/logs",
                    params={"service_id": req.service_id.value, "limit": req.limit},
                )
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPError as exc:
            return LogQueryResponse(
                source="log_backend_http",
                service_id=req.service_id,
                collected_at_utc=now,
                error=StructuredTelemetryError(
                    error_code="HTTP_LOGS_ERROR",
                    message=f"Log backend failed: {exc.__class__.__name__}",
                    retryable=True,
                ),
            )

        raw_items = payload.get("logs", [])
        entries = [
            LogEntry(
                timestamp_utc=datetime.fromisoformat(item["timestamp"]),
                level=str(item["level"]),
                service=str(item["service"]),
                message=str(item["message"]),
            )
            for item in raw_items[: req.limit]
        ]
        return LogQueryResponse(
            source="log_backend_http",
            service_id=req.service_id,
            collected_at_utc=now,
            truncated=len(raw_items) > req.limit,
            logs=entries,
        )