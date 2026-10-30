"""Service orchestrating human approvals, policy-gated execution, and verification."""

from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.schemas import RiskLevel
from app.config import Settings, get_settings
from app.db.models import (
    ActionExecution,
    ApprovalDecision,
    ApprovalStatus,
    AuditEvent,
    Incident,
    IncidentStatus,
    RemediationExecutionStatus,
    RemediationProposal,
    ServiceId,
    VerificationResult,
)
from app.integrations.telemetry import MockTelemetryAdapter, TelemetryAdapter
from app.policies.authorization import (
    authorize_execution_preflight,
    validate_human_approver_identity,
)
from app.policies.remediation_policy import ActionRequest
from app.tools.remediation import (
    MockRemediationExecutor,
    RemediationExecutor,
    verify_recovery_with_fresh_telemetry,
)


class PermissionDeniedError(Exception):
    """Raised when deterministic policy or authorization checks reject an operation."""

    def __init__(self, violation_code: str, message: str) -> None:
        super().__init__(message)
        self.violation_code = violation_code
        self.message = message


class RemediationService:
    """Application service managing human approvals, execution, and verification."""

    def __init__(
        self,
        session: Session,
        executor: RemediationExecutor | None = None,
        telemetry_adapter: TelemetryAdapter | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._executor = executor or MockRemediationExecutor()
        self._telemetry = telemetry_adapter or MockTelemetryAdapter(fault_injected=False)

    def record_approval_decision(
        self,
        proposal_id: str,
        approver_id: str,
        decision: Literal["APPROVED", "REJECTED"],
        reason: str,
        expiry_minutes: int | None = None,
    ) -> ApprovalDecision:
        """Record an explicit human approval or rejection for a remediation proposal."""
        proposal = self._session.scalar(
            select(RemediationProposal).where(RemediationProposal.id == proposal_id)
        )
        if proposal is None:
            raise ValueError(f"RemediationProposal '{proposal_id}' not found")

        valid_human, msg = validate_human_approver_identity(approver_id)
        if not valid_human:
            raise PermissionDeniedError("SELF_AUTHORIZATION_FORBIDDEN", msg)

        incident = self._session.scalar(
            select(Incident).where(Incident.id == proposal.incident_id)
        )
        if incident is None:
            raise ValueError(f"Incident '{proposal.incident_id}' not found")

        now = datetime.now(UTC)
        ttl_mins = (
            expiry_minutes
            if expiry_minutes is not None
            else self._settings.APPROVAL_EXPIRY_MINUTES
        )
        expires_at = now + timedelta(minutes=ttl_mins)

        new_status = (
            ApprovalStatus.APPROVED.value
            if decision == "APPROVED"
            else ApprovalStatus.REJECTED.value
        )
        proposal.approval_status = new_status
        incident.approval_status = new_status
        incident.updated_at_utc = now

        decision_record = ApprovalDecision(
            incident_id=incident.id,
            proposal_id=proposal.id,
            approver_id=approver_id.strip(),
            decision=new_status,
            reason=reason,
            decided_at_utc=now,
            expires_at_utc=expires_at,
        )
        self._session.add(decision_record)
        self._session.flush()

        self._session.add(
            AuditEvent(
                incident_id=incident.id,
                event_type=f"remediation.approval.{new_status.lower()}",
                actor=approver_id.strip(),
                details_json={
                    "proposal_id": proposal.id,
                    "decision_id": decision_record.id,
                    "decision": new_status,
                    "expires_at_utc": expires_at.isoformat(),
                },
            )
        )

        self._session.commit()
        self._session.refresh(decision_record)
        return decision_record

    def execute_and_verify_proposal(
        self,
        proposal_id: str,
        parameters: dict[str, str | int | bool] | None = None,
        dry_run: bool | None = None,
    ) -> tuple[ActionExecution, VerificationResult]:
        """Revalidate policy and approval, execute idempotently, and verify recovery."""
        proposal = self._session.scalar(
            select(RemediationProposal).where(RemediationProposal.id == proposal_id)
        )
        if proposal is None:
            raise ValueError(f"RemediationProposal '{proposal_id}' not found")

        incident = self._session.scalar(
            select(Incident).where(Incident.id == proposal.incident_id)
        )
        if incident is None:
            raise ValueError(f"Incident '{proposal.incident_id}' not found")

        exec_idem_key = f"exec-{proposal.idempotency_key}"

        # Idempotency guard: never duplicate remediation execution on retry
        existing_exec = self._session.scalar(
            select(ActionExecution).where(
                ActionExecution.idempotency_key == exec_idem_key
            )
        )
        if existing_exec is not None:
            existing_verif = self._session.scalar(
                select(VerificationResult).where(
                    VerificationResult.execution_id == existing_exec.id
                )
            )
            if existing_verif is not None:
                return existing_exec, existing_verif

        latest_decision = self._session.scalar(
            select(ApprovalDecision)
            .where(ApprovalDecision.proposal_id == proposal.id)
            .order_by(ApprovalDecision.decided_at_utc.desc())
        )

        action_req = ActionRequest(
            action_id=proposal.id,
            incident_id=incident.id,
            action_type=proposal.action_type,
            parameters=parameters or {},
            target=proposal.target_service,
            risk_level=RiskLevel(proposal.risk_level),
            preconditions=list(proposal.preconditions_json),
            requested_by="agent.investigation_graph",
            approval_status=ApprovalStatus(proposal.approval_status),
            idempotency_key=exec_idem_key,
        )

        auth_check = authorize_execution_preflight(
            request=action_req,
            approver_id=latest_decision.approver_id if latest_decision else None,
            approval_expires_at_utc=(
                latest_decision.expires_at_utc if latest_decision else None
            ),
        )
        if not auth_check.authorized:
            self._session.add(
                AuditEvent(
                    incident_id=incident.id,
                    event_type="remediation.execution.rejected",
                    actor="policy.authorization_engine",
                    details_json={
                        "proposal_id": proposal.id,
                        "violation_code": auth_check.violation_code,
                        "reason": auth_check.reason,
                    },
                )
            )
            self._session.commit()
            raise PermissionDeniedError(
                auth_check.violation_code or "UNAUTHORIZED",
                auth_check.reason,
            )

        use_dry_run = (
            dry_run if dry_run is not None else self._settings.REMEDIATION_DRY_RUN_ONLY
        )
        incident.incident_status = IncidentStatus.MITIGATING.value
        incident.remediation_execution_status = RemediationExecutionStatus.EXECUTING.value

        exec_outcome = self._executor.execute(action_req, dry_run=use_dry_run)
        incident.remediation_execution_status = exec_outcome.execution_status.value

        execution_record = ActionExecution(
            incident_id=incident.id,
            proposal_id=proposal.id,
            idempotency_key=exec_idem_key,
            action_type=proposal.action_type,
            target_service=proposal.target_service,
            parameters_json=action_req.parameters,
            dry_run=exec_outcome.dry_run,
            execution_status=exec_outcome.execution_status.value,
            output_message=exec_outcome.message,
            rollback_plan=auth_check.rollback_plan,
            executed_at_utc=exec_outcome.executed_at_utc,
        )
        self._session.add(execution_record)
        self._session.flush()

        self._session.add(
            AuditEvent(
                incident_id=incident.id,
                event_type="remediation.action.executed",
                actor="system.remediation_executor",
                details_json={
                    "execution_id": execution_record.id,
                    "proposal_id": proposal.id,
                    "status": execution_record.execution_status,
                    "dry_run": execution_record.dry_run,
                },
            )
        )

        # Fresh-telemetry recovery verification
        if exec_outcome.succeeded:
            verif_outcome = verify_recovery_with_fresh_telemetry(
                service_id=ServiceId(incident.service_id),
                adapter=self._telemetry,
            )
        else:
            verif_outcome = verify_recovery_with_fresh_telemetry(
                service_id=ServiceId(incident.service_id),
                adapter=MockTelemetryAdapter(fault_injected=True, simulate_failure=True),
            )
            verif_outcome.summary = (
                "Remediation execution failed; skipping recovery claim and escalating."
            )

        verification_record = VerificationResult(
            incident_id=incident.id,
            execution_id=execution_record.id,
            verification_status=verif_outcome.verification_status.value,
            recovered=verif_outcome.recovered,
            observed_5xx_rate=verif_outcome.observed_5xx_rate,
            observed_pool_wait_ms=verif_outcome.observed_pool_wait_ms,
            summary=verif_outcome.summary,
        )
        self._session.add(verification_record)
        self._session.flush()

        incident.recovery_verification_status = verif_outcome.verification_status.value
        now = datetime.now(UTC)
        incident.updated_at_utc = now

        if verif_outcome.recovered:
            incident.incident_status = IncidentStatus.RESOLVED.value
            incident.resolved_at_utc = now

        self._session.add(
            AuditEvent(
                incident_id=incident.id,
                event_type="remediation.verification.completed",
                actor="system.recovery_verifier",
                details_json={
                    "verification_id": verification_record.id,
                    "recovered": verification_record.recovered,
                    "verification_status": verification_record.verification_status,
                },
            )
        )

        self._session.commit()
        self._session.refresh(execution_record)
        self._session.refresh(verification_record)
        return execution_record, verification_record