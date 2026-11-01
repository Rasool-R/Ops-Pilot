"""Disposable e-commerce simulator with repeatable DB pool exhaustion scenario."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.db.models import ServiceId


class ScenarioMode(StrEnum):
    """Supported operational states of the disposable simulator."""

    HEALTHY = "healthy"
    DB_POOL_EXHAUSTION = "db_pool_exhaustion"


class ScenarioStateResponse(BaseModel):
    """Public status response (intentionally omits hidden root-cause ground truth)."""

    status: Literal["ok"]
    fault_injected: bool
    updated_at_utc: datetime


class RemediationTargetRequest(BaseModel):
    """Request payload for executing a restricted action against the simulator."""

    action_type: Literal["reset_db_connection_pool", "restart_service_container"]
    target: ServiceId
    parameters: dict[str, str | int | bool] = Field(default_factory=dict)


class RemediationTargetResponse(BaseModel):
    """Execution outcome returned by the disposable simulator target."""

    executed: bool
    action_type: str
    target: str
    message: str
    timestamp_utc: datetime


class SimulatorState:
    """In-memory state container for the disposable synthetic environment."""

    def __init__(self) -> None:
        self.mode: ScenarioMode = ScenarioMode.HEALTHY
        self.updated_at_utc: datetime = datetime.now(UTC)

    def set_mode(self, mode: ScenarioMode) -> None:
        """Transition simulator scenario state and update timestamp."""
        self.mode = mode
        self.updated_at_utc = datetime.now(UTC)


sim_state = SimulatorState()


def create_simulator_app() -> FastAPI:
    """Create the FastAPI disposable e-commerce simulator application."""
    sim = FastAPI(
        title="OpsPilot Disposable E-Commerce Simulator",
        version="0.1.0",
        description="Simulates frontend, api-gateway, order/payment/inventory, and postgres.",
    )

    @sim.get("/health", response_model=ScenarioStateResponse)
    def simulator_health() -> ScenarioStateResponse:
        """Return simulator liveness without leaking ground-truth scenario labels."""
        return ScenarioStateResponse(
            status="ok",
            fault_injected=(sim_state.mode != ScenarioMode.HEALTHY),
            updated_at_utc=sim_state.updated_at_utc,
        )

    @sim.post("/admin/scenario/trigger", response_model=ScenarioStateResponse)
    def trigger_db_pool_scenario() -> ScenarioStateResponse:
        """Inject the MVP synthetic fault (elevated 5xx/latency via DB pool saturation)."""
        sim_state.set_mode(ScenarioMode.DB_POOL_EXHAUSTION)
        return ScenarioStateResponse(
            status="ok",
            fault_injected=True,
            updated_at_utc=sim_state.updated_at_utc,
        )

    @sim.post("/admin/scenario/reset", response_model=ScenarioStateResponse)
    def reset_scenario() -> ScenarioStateResponse:
        """Reset the simulator back to the baseline healthy state."""
        sim_state.set_mode(ScenarioMode.HEALTHY)
        return ScenarioStateResponse(
            status="ok",
            fault_injected=False,
            updated_at_utc=sim_state.updated_at_utc,
        )

    @sim.get("/metrics", response_class=PlainTextResponse)
    def prometheus_metrics() -> str:
        """Expose Prometheus text-format metrics for all 6 e-commerce services."""
        if sim_state.mode == ScenarioMode.HEALTHY:
            metrics_map = {
                "frontend": (0.001, 45.0, 0.0, 0.0),
                "api-gateway": (0.002, 60.0, 0.0, 0.0),
                "order-service": (0.001, 85.0, 12.0, 4.0),
                "payment-service": (0.001, 70.0, 8.0, 2.0),
                "inventory-service": (0.001, 55.0, 6.0, 2.0),
                "postgres": (0.0, 10.0, 26.0, 3.0),
            }
        else:
            metrics_map = {
                "frontend": (0.145, 1850.0, 0.0, 0.0),
                "api-gateway": (0.182, 2100.0, 0.0, 0.0),
                "order-service": (0.240, 2950.0, 100.0, 4800.0),
                "payment-service": (0.003, 75.0, 8.0, 5.0),
                "inventory-service": (0.002, 60.0, 6.0, 4.0),
                "postgres": (0.0, 420.0, 100.0, 4900.0),
            }

        lines: list[str] = [
            "# HELP http_requests_5xx_rate Ratio of HTTP 5xx responses.",
            "# TYPE http_requests_5xx_rate gauge",
            "# HELP http_request_latency_p95 95th percentile HTTP latency in ms.",
            "# TYPE http_request_latency_p95 gauge",
            "# HELP pg_stat_activity_active_connections Active PostgreSQL connections.",
            "# TYPE pg_stat_activity_active_connections gauge",
            "# HELP pg_pool_wait_time_ms Connection pool acquisition wait time in ms.",
            "# TYPE pg_pool_wait_time_ms gauge",
        ]
        for svc, (err_rate, latency, active_conn, pool_wait) in metrics_map.items():
            lines.append(f'http_requests_5xx_rate{{service="{svc}"}} {err_rate}')
            lines.append(f'http_request_latency_p95{{service="{svc}"}} {latency}')
            lines.append(
                f'pg_stat_activity_active_connections{{service="{svc}"}} {active_conn}'
            )
            lines.append(f'pg_pool_wait_time_ms{{service="{svc}"}} {pool_wait}')

        return "\n".join(lines) + "\n"

    @sim.get("/telemetry/logs")
    def service_logs(
        service_id: Annotated[ServiceId, Query(description="Target e-commerce service")],
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> dict[str, object]:
        """Return bounded structured log entries for a target service."""
        now_iso = datetime.now(UTC).isoformat()
        entries: list[dict[str, str]] = []

        if sim_state.mode == ScenarioMode.HEALTHY:
            entries.append(
                {
                    "timestamp": now_iso,
                    "level": "INFO",
                    "service": service_id.value,
                    "message": "Request processed within normal SLA thresholds.",
                }
            )
        else:
            if service_id == ServiceId.ORDER_SERVICE:
                entries.extend(
                    [
                        {
                            "timestamp": now_iso,
                            "level": "ERROR",
                            "service": "order-service",
                            "message": (
                                "QueuePool limit of size 100 overflow 0 reached, "
                                "connection timed out, timeout 5.00"
                            ),
                        },
                        {
                            "timestamp": now_iso,
                            "level": "ERROR",
                            "service": "order-service",
                            "message": "HTTP 503 returned for POST /orders/checkout",
                        },
                    ]
                )
            elif service_id in (ServiceId.API_GATEWAY, ServiceId.FRONTEND):
                entries.append(
                    {
                        "timestamp": now_iso,
                        "level": "ERROR",
                        "service": service_id.value,
                        "message": "Upstream timeout calling order-service: HTTP 504",
                    }
                )
            elif service_id == ServiceId.POSTGRES:
                entries.append(
                    {
                        "timestamp": now_iso,
                        "level": "WARNING",
                        "service": "postgres",
                        "message": "active_connections=100/100; idle_in_transaction sessions held",
                    }
                )
            else:
                entries.append(
                    {
                        "timestamp": now_iso,
                        "level": "INFO",
                        "service": service_id.value,
                        "message": "Service operating normally.",
                    }
                )

        return {
            "service_id": service_id.value,
            "collected_at_utc": now_iso,
            "count": len(entries[:limit]),
            "logs": entries[:limit],
        }

    @sim.post("/admin/remediation/execute", response_model=RemediationTargetResponse)
    def execute_disposable_remediation(
        req: RemediationTargetRequest,
    ) -> RemediationTargetResponse:
        """Execute an allowlisted remediation action in the disposable environment."""
        if req.action_type == "reset_db_connection_pool" and req.target in (
            ServiceId.ORDER_SERVICE,
            ServiceId.POSTGRES,
        ):
            sim_state.set_mode(ScenarioMode.HEALTHY)
            return RemediationTargetResponse(
                executed=True,
                action_type=req.action_type,
                target=req.target.value,
                message="Connection pool drained and reinitialized; active sessions cleared.",
                timestamp_utc=sim_state.updated_at_utc,
            )

        if (
            req.action_type == "restart_service_container"
            and req.target == ServiceId.ORDER_SERVICE
        ):
            sim_state.set_mode(ScenarioMode.HEALTHY)
            return RemediationTargetResponse(
                executed=True,
                action_type=req.action_type,
                target=req.target.value,
                message="order-service container restarted; stale DB connections released.",
                timestamp_utc=sim_state.updated_at_utc,
            )

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported target '{req.target.value}' for action '{req.action_type}'",
        )

    return sim


simulator_app = create_simulator_app()
