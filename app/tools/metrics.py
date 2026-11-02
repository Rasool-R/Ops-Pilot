"""Bounded metric collection tool for the LangGraph investigation agent."""

from datetime import datetime

from app.db.models import ServiceId
from app.integrations.telemetry import (
    MetricName,
    MockTelemetryAdapter,
    TelemetryAdapter,
    TelemetryQueryRequest,
    TelemetryQueryResponse,
)


def query_service_metrics(
    service_id: ServiceId,
    metric_name: MetricName,
    start_time_utc: datetime,
    end_time_utc: datetime,
    step_seconds: int = 60,
    limit: int = 50,
    adapter: TelemetryAdapter | None = None,
) -> TelemetryQueryResponse:
    """Execute a validated, bounded metric query with source attribution."""
    request = TelemetryQueryRequest(
        service_id=service_id,
        metric_name=metric_name,
        start_time_utc=start_time_utc,
        end_time_utc=end_time_utc,
        step_seconds=step_seconds,
        limit=limit,
    )
    active_adapter = adapter or MockTelemetryAdapter()
    return active_adapter.query_metrics(request)