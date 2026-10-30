"""FastAPI endpoints for human approval decisions and controlled remediation execution."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.remediation_service import PermissionDeniedError, RemediationService

router = APIRouter(prefix="/approvals", tags=["approvals"])

DbSessionDep = Annotated[Session, Depends(get_db)]


class ApprovalDecisionRequest(BaseModel):
    """Input payload for a human operator approving or rejecting a proposal."""

    approver_id: str = Field(min_length=2, max_length=128)
    decision: Literal["APPROVED", "REJECTED"]
    reason: str = Field(min_length=3, max_length=500)
    expiry_minutes: int | None = Field(default=None, ge=1, le=240)


class ApprovalDecisionResponse(BaseModel):
    """Response schema for a recorded human approval decision."""

    decision_id: str
    incident_id: str
    proposal_id: str
    approver_id: str
    decision: str
    reason: str
    decided_at_utc: datetime
    expires_at_utc: datetime


class ExecuteProposalRequest(BaseModel):
    """Input payload for triggering execution of an approved remediation proposal."""

    parameters: dict[str, str | int | bool] = Field(default_factory=dict)
    dry_run: bool | None = None


class ExecuteProposalResponse(BaseModel):
    """Combined execution and fresh-telemetry verification response."""

    execution_id: str
    incident_id: str
    proposal_id: str
    action_type: str
    target_service: str
    dry_run: bool
    execution_status: str
    output_message: str
    rollback_plan: str
    verification_status: str
    recovered: bool
    verification_summary: str


@router.post(
    "/proposals/{proposal_id}/decide",
    response_model=ApprovalDecisionResponse,
    status_code=status.HTTP_200_OK,
)
def decide_proposal_endpoint(
    proposal_id: str,
    payload: ApprovalDecisionRequest,
    db: DbSessionDep,
) -> ApprovalDecisionResponse:
    """Record an explicit human approval or rejection for a remediation proposal."""
    service = RemediationService(session=db)
    try:
        record = service.record_approval_decision(
            proposal_id=proposal_id,
            approver_id=payload.approver_id,
            decision=payload.decision,
            reason=payload.reason,
            expiry_minutes=payload.expiry_minutes,
        )
    except PermissionDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"violation_code": exc.violation_code, "message": exc.message},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return ApprovalDecisionResponse(
        decision_id=record.id,
        incident_id=record.incident_id,
        proposal_id=record.proposal_id,
        approver_id=record.approver_id,
        decision=record.decision,
        reason=record.reason,
        decided_at_utc=record.decided_at_utc,
        expires_at_utc=record.expires_at_utc,
    )


@router.post(
    "/proposals/{proposal_id}/execute",
    response_model=ExecuteProposalResponse,
    status_code=status.HTTP_200_OK,
)
def execute_proposal_endpoint(
    proposal_id: str,
    payload: ExecuteProposalRequest,
    db: DbSessionDep,
) -> ExecuteProposalResponse:
    """Execute an approved remediation proposal and verify recovery via fresh telemetry."""
    service = RemediationService(session=db)
    try:
        exec_rec, verif_rec = service.execute_and_verify_proposal(
            proposal_id=proposal_id,
            parameters=payload.parameters,
            dry_run=payload.dry_run,
        )
    except PermissionDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"violation_code": exc.violation_code, "message": exc.message},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return ExecuteProposalResponse(
        execution_id=exec_rec.id,
        incident_id=exec_rec.incident_id,
        proposal_id=exec_rec.proposal_id,
        action_type=exec_rec.action_type,
        target_service=exec_rec.target_service,
        dry_run=exec_rec.dry_run,
        execution_status=exec_rec.execution_status,
        output_message=exec_rec.output_message,
        rollback_plan=exec_rec.rollback_plan,
        verification_status=verif_rec.verification_status,
        recovered=verif_rec.recovered,
        verification_summary=verif_rec.summary,
    )