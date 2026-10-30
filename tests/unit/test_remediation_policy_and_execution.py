"""Tests for remediation policy, human approval enforcement, and recovery verification."""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.schemas import RiskLevel
from app.db.base import Base
from app.db.models import (
    ActionExecution,
    ApprovalStatus,
    IncidentStatus,
    RecoveryVerificationStatus,
    RemediationExecutionStatus,
    ServiceId,
    Severity,
)
from app.db.repository import NormalizedAlertInput
from app.db.session import get_db
from app.integrations.telemetry import MockTelemetryAdapter
from app.main import create_app
from app.policies.authorization import authorize_execution_preflight
from app.policies.remediation_policy import ActionRequest, evaluate_remediation_policy
from app.services.incident_service import IncidentService
from app.services.remediation_service import PermissionDeniedError, RemediationService


@pytest.fixture()
def remediation_db() -> Generator[Session, None, None]:
    """Provide an isolated in-memory database with all Phase 7 tables initialized."""
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


def _seed_investigated_incident(session: Session) -> tuple[str, str]:
    """Ingest and investigate a synthetic alert, returning (incident_id, proposal_id)."""
    inc_service = IncidentService(
        session=session,
        telemetry_adapter=MockTelemetryAdapter(fault_injected=True),
    )
    incident, _created = inc_service.ingest_and_investigate(
        NormalizedAlertInput(
            idempotency_key="rem-test-alert-001",
            alert_fingerprint="fp-order-pool-rem",
            service_id=ServiceId.ORDER_SERVICE,
            title="Order service 5xx spike from DB pool exhaustion",
            severity=Severity.CRITICAL,
            starts_at_utc=datetime(2026, 10, 29, 10, 0, 0, tzinfo=UTC),
        )
    )
    assert len(incident.remediation_proposals) == 1
    return incident.id, incident.remediation_proposals[0].id


def test_policy_rejects_unallowlisted_actions_targets_and_parameters() -> None:
    """Verify deterministic policy blocks unknown actions, forbidden targets, and bad params."""
    bad_action = ActionRequest(
        action_id="act-1",
        incident_id="inc-1",
        action_type="drop_production_database",
        parameters={},
        target="postgres",
        risk_level=RiskLevel.CRITICAL,
        preconditions=["some check"],
        requested_by="agent",
        approval_status=ApprovalStatus.APPROVED,
        idempotency_key="idem-1",
    )
    res_action = evaluate_remediation_policy(bad_action)
    assert res_action.allowed is False
    assert res_action.violation_code == "UNALLOWLISTED_ACTION_TYPE"

    bad_target = bad_action.model_copy(
        update={
            "action_type": "restart_service_container",
            "target": "postgres",
        }
    )
    res_target = evaluate_remediation_policy(bad_target)
    assert res_target.allowed is False
    assert res_target.violation_code == "TARGET_NOT_PERMITTED_FOR_ACTION"

    bad_params = bad_action.model_copy(
        update={
            "action_type": "reset_db_connection_pool",
            "target": "order-service",
            "parameters": {"shell_cmd": "rm -rf /"},
        }
    )
    res_params = evaluate_remediation_policy(bad_params)
    assert res_params.allowed is False
    assert res_params.violation_code == "INVALID_ACTION_PARAMETERS"


def test_authorization_blocks_unapproved_expired_or_agent_self_approved_actions(
    remediation_db: Session,
) -> None:
    """Verify execution is blocked without human approval, if expired, or if agent approves."""
    _incident_id, proposal_id = _seed_investigated_incident(remediation_db)
    rem_service = RemediationService(session=remediation_db)

    # 1. Attempt execution before approval -> blocked
    with pytest.raises(PermissionDeniedError) as exc_info:
        rem_service.execute_and_verify_proposal(proposal_id=proposal_id)
    assert exc_info.value.violation_code == "APPROVAL_REQUIRED"

    # 2. Attempt self-approval by agent/LLM -> blocked
    with pytest.raises(PermissionDeniedError) as self_Approve_exc:
        rem_service.record_approval_decision(
            proposal_id=proposal_id,
            approver_id="agent",
            decision="APPROVED",
            reason="LLM trying to self-approve",
        )
    assert self_Approve_exc.value.violation_code == "SELF_AUTHORIZATION_FORBIDDEN"

    # 3. Verify expired approval is rejected by pre-flight check
    now = datetime.now(UTC)
    expired_req = ActionRequest(
        action_id=proposal_id,
        incident_id="inc-1",
        action_type="reset_db_connection_pool",
        parameters={"force": True},
        target="order-service",
        risk_level=RiskLevel.MEDIUM,
        preconditions=["pool saturated"],
        requested_by="agent",
        approval_status=ApprovalStatus.APPROVED,
        idempotency_key="idem-exp",
    )
    expired_check = authorize_execution_preflight(
        request=expired_req,
        approver_id="sre.rasool",
        approval_expires_at_utc=now - timedelta(minutes=1),
        now_utc=now,
    )
    assert expired_check.authorized is False
    assert expired_check.violation_code == "APPROVAL_EXPIRED"


def test_approved_execution_verifies_recovery_with_fresh_telemetry_and_is_idempotent(
    remediation_db: Session,
) -> None:
    """Verify approved action executes once, checks fresh telemetry, and resolves incident."""
    incident_id, proposal_id = _seed_investigated_incident(remediation_db)

    # Fresh telemetry adapter reports healthy metrics after remediation
    healthy_fresh_adapter = MockTelemetryAdapter(fault_injected=False)
    rem_service = RemediationService(
        session=remediation_db,
        telemetry_adapter=healthy_fresh_adapter,
    )

    rem_service.record_approval_decision(
        proposal_id=proposal_id,
        approver_id="sre.rasool",
        decision="APPROVED",
        reason="Verified DB pool saturation in Prometheus; approving pool reset.",
    )

    exec_1, verif_1 = rem_service.execute_and_verify_proposal(
        proposal_id=proposal_id,
        parameters={"force": True},
        dry_run=False,
    )
    assert exec_1.execution_status == RemediationExecutionStatus.SUCCEEDED.value
    assert verif_1.recovered is True
    assert (
        verif_1.verification_status
        == RecoveryVerificationStatus.VERIFIED_RECOVERED.value
    )

    # Second call with same proposal must be strictly idempotent (no duplicate execution row)
    exec_2, verif_2 = rem_service.execute_and_verify_proposal(proposal_id=proposal_id)
    assert exec_2.id == exec_1.id
    assert verif_2.id == verif_1.id
    all_execs = list(remediation_db.scalars(select(ActionExecution)).all())
    assert len(all_execs) == 1


def test_execution_escalates_when_fresh_telemetry_remains_unhealthy(
    remediation_db: Session,
) -> None:
    """Verify incident is ESCALATED and not marked RESOLVED if fresh telemetry still fails."""
    _incident_id, proposal_id = _seed_investigated_incident(remediation_db)

    # Fresh telemetry still shows fault_injected=True (unhealthy after action)
    still_faulty_adapter = MockTelemetryAdapter(fault_injected=True)
    rem_service = RemediationService(
        session=remediation_db,
        telemetry_adapter=still_faulty_adapter,
    )

    rem_service.record_approval_decision(
        proposal_id=proposal_id,
        approver_id="sre.mohammad",
        decision="APPROVED",
        reason="Approved for execution test.",
    )

    exec_rec, verif_rec = rem_service.execute_and_verify_proposal(proposal_id=proposal_id)
    assert exec_rec.execution_status == RemediationExecutionStatus.SUCCEEDED.value
    assert verif_rec.recovered is False
    assert verif_rec.verification_status == RecoveryVerificationStatus.ESCALATED.value
    assert exec_rec.incident.incident_status == IncidentStatus.MITIGATING.value


def test_approvals_api_endpoints_end_to_end(remediation_db: Session) -> None:
    """Verify FastAPI /approvals endpoints enforce 403 before approval and 200 after."""
    _incident_id, proposal_id = _seed_investigated_incident(remediation_db)
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        yield remediation_db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    # 1. Execute without approval -> HTTP 403
    unauth_resp = client.post(
        f"/api/v1/approvals/proposals/{proposal_id}/execute",
        json={"parameters": {"force": True}, "dry_run": True},
    )
    assert unauth_resp.status_code == 403

    # 2. Approve with human operator -> HTTP 200
    decide_resp = client.post(
        f"/api/v1/approvals/proposals/{proposal_id}/decide",
        json={
            "approver_id": "sre.rasool",
            "decision": "APPROVED",
            "reason": "Approving pool reset in disposable environment",
            "expiry_minutes": 30,
        },
    )
    assert decide_resp.status_code == 200
    assert decide_resp.json()["decision"] == "APPROVED"

    # 3. Execute after approval -> HTTP 200 and recovered=True
    exec_resp = client.post(
        f"/api/v1/approvals/proposals/{proposal_id}/execute",
        json={"parameters": {"force": True}, "dry_run": True},
    )
    assert exec_resp.status_code == 200
    payload = exec_resp.json()
    assert payload["execution_status"] == "SUCCEEDED"
    assert payload["recovered"] is True
    assert payload["verification_status"] == "VERIFIED_RECOVERED"