"""Independent pre-execution authorization checks (LLM never self-authorizes)."""

from datetime import UTC, datetime

from pydantic import BaseModel

from app.db.models import ApprovalStatus
from app.policies.remediation_policy import ActionRequest, evaluate_remediation_policy

FORBIDDEN_AUTONOMOUS_APPROVERS: frozenset[str] = frozenset(
    {"agent", "llm", "opspilot-agent", "system", "auto", "ai"}
)


class AuthorizationCheckResult(BaseModel):
    """Outcome of pre-execution authorization and approval validation."""

    authorized: bool
    violation_code: str | None = None
    reason: str
    rollback_plan: str = ""


def validate_human_approver_identity(approver_id: str) -> tuple[bool, str]:
    """Ensure the approver identity is an explicit human operator and never the agent."""
    normalized = approver_id.strip().lower()
    if not normalized or normalized in FORBIDDEN_AUTONOMOUS_APPROVERS:
        return (
            False,
            f"Approver identity '{approver_id}' is forbidden; the LLM/agent may never "
            "authorize its own remediation action.",
        )
    return True, "Valid human operator identity."


def authorize_execution_preflight(
    request: ActionRequest,
    approver_id: str | None,
    approval_expires_at_utc: datetime | None,
    now_utc: datetime | None = None,
) -> AuthorizationCheckResult:
    """Revalidate policy, approval status, human identity, and expiry before execution."""
    current_time = now_utc or datetime.now(UTC)

    policy_res = evaluate_remediation_policy(request)
    if not policy_res.allowed:
        return AuthorizationCheckResult(
            authorized=False,
            violation_code=policy_res.violation_code,
            reason=policy_res.reason,
        )

    if request.approval_status != ApprovalStatus.APPROVED:
        return AuthorizationCheckResult(
            authorized=False,
            violation_code="APPROVAL_REQUIRED",
            reason=(
                f"Execution blocked: action approval_status is "
                f"'{request.approval_status.value}', expected 'APPROVED'."
            ),
        )

    if approver_id is None:
        return AuthorizationCheckResult(
            authorized=False,
            violation_code="MISSING_APPROVER_IDENTITY",
            reason="Execution blocked: no human approver identity recorded.",
        )

    valid_human, identity_msg = validate_human_approver_identity(approver_id)
    if not valid_human:
        return AuthorizationCheckResult(
            authorized=False,
            violation_code="SELF_AUTHORIZATION_FORBIDDEN",
            reason=identity_msg,
        )

    if approval_expires_at_utc is None:
        return AuthorizationCheckResult(
            authorized=False,
            violation_code="MISSING_APPROVAL_EXPIRY",
            reason="Execution blocked: approval decision has no expiration timestamp.",
        )

    expiry_aware = (
        approval_expires_at_utc.replace(tzinfo=UTC)
        if approval_expires_at_utc.tzinfo is None
        else approval_expires_at_utc
    )
    if current_time >= expiry_aware:
        return AuthorizationCheckResult(
            authorized=False,
            violation_code="APPROVAL_EXPIRED",
            reason="Execution blocked: human approval decision has expired.",
        )

    return AuthorizationCheckResult(
        authorized=True,
        reason="Pre-execution policy and human approval checks passed.",
        rollback_plan=policy_res.rollback_plan,
    )