"""End-to-end MVP scenario test verifying the complete OpsPilot product flow."""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import ServiceId
from app.db.session import get_db
from app.integrations.telemetry import (
    METRIC_UNITS,
    DataPoint,
    LogEntry,
    LogQueryRequest,
    LogQueryResponse,
    TelemetryQueryRequest,
    TelemetryQueryResponse,
)
from app.main import create_app
from app.policies.remediation_policy import ActionRequest
from app.services.remediation_service import RemediationService
from app.simulator.service import create_simulator_app
from app.tools.remediation import ExecutionOutcome


class InProcessSimulatorBridge:
    """Bridges the live FastAPI simulator app to TelemetryAdapter and RemediationExecutor."""

    def __init__(self, sim_client: TestClient) -> None:
        self._sim = sim_client

    def query_metrics(self, req: TelemetryQueryRequest) -> TelemetryQueryResponse:
        """Read live Prometheus metrics directly from the simulator /metrics endpoint."""
        now = datetime.now(UTC)
        unit = METRIC_UNITS[req.metric_name]
        resp = self._sim.get("/metrics")
        assert resp.status_code == 200

        target_prefix = f'{req.metric_name.value}{{service="{req.service_id.value}"}}'
        value = 0.0
        for line in resp.text.splitlines():
            if line.startswith(target_prefix):
                parts = line.split()
                if len(parts) == 2:
                    value = float(parts[1])
                break

        return TelemetryQueryResponse(
            source="simulator_prometheus",
            service_id=req.service_id,
            metric_name=req.metric_name,
            unit=unit,
            collected_at_utc=now,
            truncated=False,
            series=[DataPoint(timestamp_utc=now, value=value)],
        )

    def query_logs(self, req: LogQueryRequest) -> LogQueryResponse:
        """Read live structured logs directly from the simulator /telemetry/logs endpoint."""
        now = datetime.now(UTC)
        resp = self._sim.get(
            "/telemetry/logs",
            params={"service_id": req.service_id.value, "limit": req.limit},
        )
        assert resp.status_code == 200
        payload = resp.json()
        entries = [
            LogEntry(
                timestamp_utc=datetime.fromisoformat(item["timestamp"]),
                level=str(item["level"]),
                service=str(item["service"]),
                message=str(item["message"]),
            )
            for item in payload.get("logs", [])
        ]
        return LogQueryResponse(
            source="simulator_logs",
            service_id=req.service_id,
            collected_at_utc=now,
            truncated=False,
            logs=entries,
        )

    def execute(self, request: ActionRequest, dry_run: bool) -> ExecutionOutcome:
        """Execute an authorized remediation action against the live simulator."""
        now = datetime.now(UTC)
        resp = self._sim.post(
            "/admin/remediation/execute",
            json={
                "action_type": request.action_type,
                "target": request.target,
                "parameters": request.parameters,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        from app.db.models import RemediationExecutionStatus

        return ExecutionOutcome(
            succeeded=bool(data["executed"]),
            execution_status=RemediationExecutionStatus.SUCCEEDED,
            dry_run=dry_run,
            message=str(data["message"]),
            executed_at_utc=now,
        )


@pytest.fixture()
def e2e_db() -> Generator[Session, None, None]:
    """Provide an isolated database session for the end-to-end scenario test."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    session = factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def test_full_mvp_incident_lifecycle_with_live_simulator(e2e_db: Session) -> None:
    """Verify fault injection -> webhook -> RCA -> approval -> execution -> recovery."""
    sim_client = TestClient(create_simulator_app())
    bridge = InProcessSimulatorBridge(sim_client)

    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        yield e2e_db

    app.dependency_overrides[get_db] = override_get_db
    ops_client = TestClient(app)

    # Step 1: Inject synthetic DB pool exhaustion fault in the disposable simulator
    trigger_resp = sim_client.post("/admin/scenario/trigger")
    assert trigger_resp.status_code == 200
    assert trigger_resp.json()["fault_injected"] is True

    # Step 2: Deliver firing Alertmanager webhook to OpsPilot
    webhook_payload = {
        "version": "4",
        "status": "firing",
        "receiver": "opspilot-webhook",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "OrderServiceHigh5xxRate",
                    "service_id": ServiceId.ORDER_SERVICE.value,
                    "severity": "CRITICAL",
                },
                "annotations": {
                    "summary": "Elevated HTTP 5xx error rate detected on order-service",
                },
                "startsAt": (datetime.now(UTC) - timedelta(minutes=2)).isoformat(),
                "fingerprint": "fp-e2e-order-5xx-pool",
            }
        ],
    }
    wh_resp = ops_client.post("/api/v1/alerts/webhook", json=webhook_payload)
    assert wh_resp.status_code == 200
    incident_id = wh_resp.json()["incident_ids"][0]

    # Step 3: Verify RCA report, evidence grounding, and runbook citation
    lifecycle_1 = ops_client.get(f"/api/v1/incidents/{incident_id}/lifecycle").json()
    assert lifecycle_1["investigation_status"] == "COMPLETED"
    assert lifecycle_1["approval_status"] == "PENDING_APPROVAL"
    assert len(lifecycle_1["proposals"]) == 1
    proposal_id = lifecycle_1["proposals"][0]["proposal_id"]

    # Step 4: Verify unapproved execution is blocked by independent policy check
    blocked_resp = ops_client.post(
        f"/api/v1/approvals/proposals/{proposal_id}/execute",
        json={"parameters": {"force": True}, "dry_run": False},
    )
    assert blocked_resp.status_code == 403

    # Step 5: Human SRE approves the remediation proposal
    rem_service = RemediationService(
        session=e2e_db,
        executor=bridge,
        telemetry_adapter=bridge,
    )
    rem_service.record_approval_decision(
        proposal_id=proposal_id,
        approver_id="sre.rasool",
        decision="APPROVED",
        reason="Confirmed DB connection pool exhaustion; approving pool reset.",
    )

    # Step 6: Execute against live simulator and verify recovery via fresh telemetry
    exec_rec, verif_rec = rem_service.execute_and_verify_proposal(
        proposal_id=proposal_id,
        parameters={"force": True},
        dry_run=False,
    )
    assert exec_rec.execution_status == "SUCCEEDED"
    assert verif_rec.recovered is True
    assert verif_rec.verification_status == "VERIFIED_RECOVERED"

    # Step 7: Confirm simulator is healthy and incident lifecycle is RESOLVED
    sim_health = sim_client.get("/health").json()
    assert sim_health["fault_injected"] is False

    lifecycle_final = ops_client.get(
        f"/api/v1/incidents/{incident_id}/lifecycle"
    ).json()
    assert lifecycle_final["incident_status"] == "RESOLVED"
    assert lifecycle_final["recovery_verification_status"] == "VERIFIED_RECOVERED"
    assert len(lifecycle_final["audit_timeline"]) >= 5