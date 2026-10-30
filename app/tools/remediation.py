"""Restricted remediation execution adapters and fresh-telemetry recovery verification."""

from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.db.models import RecoveryVerificationStatus, RemediationExecutionStatus, ServiceId
from app.integrations.telemetry import MetricName, TelemetryAdapter
from app.policies.remediation_policy import ActionRequest
from app.tools.metrics import query_service_metrics


class ExecutionOutcome(BaseModel):
    """Structured result of executing a restricted remediation action."""

    succeeded: bool
    execution_status: RemediationExecutionStatus
    dry_run: bool
    message: str
    executed_at_utc: datetime


class FreshVerificationOutcome(BaseModel):
    """Result of verifying service recovery against fresh post-execution telemetry."""

    recovered: bool
    verification_status: RecoveryVerificationStatus
    observed_5xx_rate: float | None = None
    observed_pool_wait_ms: float | None = None
    summary: str


class RemediationExecutor(Protocol):
    """Protocol for executing allowlisted actions in a disposable or dry-run target."""

    def execute(self, request: ActionRequest, dry_run: bool) -> ExecutionOutcome:
        """Execute an authorized remediation request."""
        ...


class MockRemediationExecutor:
    """Deterministic executor for unit/integration tests and dry-run mode."""

    def __init__(self, simulate_execution_failure: bool = False) -> None:
        self.simulate_execution_failure = simulate_execution_failure

    def execute(self, request: ActionRequest, dry_run: bool) -> ExecutionOutcome:
        """Simulate restricted execution outcome without external network calls."""
        now = datetime.now(UTC)
        if self.simulate_execution_failure:
            return ExecutionOutcome(
                succeeded=False,
                execution_status=RemediationExecutionStatus.FAILED,
                dry_run=dry_run,
                message=(
                    f"Simulated execution failure for '{request.action_type}' "
                    f"on '{request.target}'."
                ),
                executed_at_utc=now,
            )

        mode_label = "DRY-RUN" if dry_run else "DISPOSABLE-ENV"
        return ExecutionOutcome(
            succeeded=True,
            execution_status=RemediationExecutionStatus.SUCCEEDED,
            dry_run=dry_run,
            message=(
                f"[{mode_label}] Executed '{request.action_type}' on '{request.target}' "
                f"with idempotency_key='{request.idempotency_key}'."
            ),
            executed_at_utc=now,
        )


class SimulatorHttpRemediationExecutor:
    """HTTP executor invoking the disposable e-commerce simulator remediation endpoint."""

    def __init__(
        self,
        base_url: str = "http://localhost:8001",
        settings: Settings | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.settings = settings or get_settings()

    def execute(self, request: ActionRequest, dry_run: bool) -> ExecutionOutcome:
        """Execute remediation against the disposable simulator or return dry-run result."""
        now = datetime.now(UTC)
        if dry_run:
            return ExecutionOutcome(
                succeeded=True,
                execution_status=RemediationExecutionStatus.SUCCEEDED,
                dry_run=True,
                message=(
                    f"[DRY-RUN] Validated '{request.action_type}' on '{request.target}'; "
                    "no state mutated."
                ),
                executed_at_utc=now,
            )

        try:
            with httpx.Client(timeout=self.settings.TELEMETRY_TIMEOUT_SECONDS) as client:
                resp = client.post(
                    f"{self.base_url}/admin/remediation/execute",
                    json={
                        "action_type": request.action_type,
                        "target": request.target,
                        "parameters": request.parameters,
                    },
                )
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPError as exc:
            return ExecutionOutcome(
                succeeded=False,
                execution_status=RemediationExecutionStatus.FAILED,
                dry_run=False,
                message=f"Simulator remediation call failed: {exc.__class__.__name__}",
                executed_at_utc=now,
            )

        return ExecutionOutcome(
            succeeded=bool(payload.get("executed", False)),
            execution_status=RemediationExecutionStatus.SUCCEEDED,
            dry_run=False,
            message=str(payload.get("message", "Executed in disposable simulator.")),
            executed_at_utc=now,
        )


def verify_recovery_with_fresh_telemetry(
    service_id: ServiceId,
    adapter: TelemetryAdapter,
) -> FreshVerificationOutcome:
    """Query fresh post-action telemetry to verify SLA recovery or trigger escalation."""
    end_time = datetime.now(UTC)
    start_time = end_time - timedelta(minutes=5)

    err_resp = query_service_metrics(
        service_id=service_id,
        metric_name=MetricName.HTTP_5XX_RATE,
        start_time_utc=start_time,
        end_time_utc=end_time,
        limit=1,
        adapter=adapter,
    )
    wait_resp = query_service_metrics(
        service_id=service_id,
        metric_name=MetricName.PG_POOL_WAIT_TIME_MS,
        start_time_utc=start_time,
        end_time_utc=end_time,
        limit=1,
        adapter=adapter,
    )

    if (
        err_resp.error is not None
        or wait_resp.error is not None
        or not err_resp.series
        or not wait_resp.series
    ):
        return FreshVerificationOutcome(
            recovered=False,
            verification_status=RecoveryVerificationStatus.ESCALATED,
            summary=(
                "Fresh telemetry unavailable after remediation execution; "
                "recovery cannot be verified. Escalating to human SRE."
            ),
        )

    latest_5xx = err_resp.series[-1].value
    latest_wait = wait_resp.series[-1].value

    if latest_5xx < 0.05 and latest_wait < 100.0:
        return FreshVerificationOutcome(
            recovered=True,
            verification_status=RecoveryVerificationStatus.VERIFIED_RECOVERED,
            observed_5xx_rate=latest_5xx,
            observed_pool_wait_ms=latest_wait,
            summary=(
                f"Recovery verified via fresh telemetry: 5xx_rate={latest_5xx} (<0.05) "
                f"and pg_pool_wait_time_ms={latest_wait}ms (<100ms)."
            ),
        )

    return FreshVerificationOutcome(
        recovered=False,
        verification_status=RecoveryVerificationStatus.ESCALATED,
        observed_5xx_rate=latest_5xx,
        observed_pool_wait_ms=latest_wait,
        summary=(
            f"Post-remediation telemetry still breaches SLA thresholds "
            f"(5xx_rate={latest_5xx}, pg_pool_wait_time_ms={latest_wait}ms). "
            "Escalating incident for manual intervention."
        ),
    )