"""Predefined remediation action catalog and deterministic policy rules."""

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, Field

from app.agents.schemas import RiskLevel
from app.db.models import ApprovalStatus, ServiceId


class AllowedActionType(StrEnum):
    """Allowlisted remediation actions permitted in the disposable MVP environment."""

    RESET_DB_CONNECTION_POOL = "reset_db_connection_pool"
    RESTART_SERVICE_CONTAINER = "restart_service_container"


@dataclass(frozen=True)
class ActionCatalogEntry:
    """Immutable specification of an allowlisted remediation action."""

    action_type: AllowedActionType
    allowed_targets: frozenset[ServiceId]
    default_risk_level: RiskLevel
    requires_human_approval: bool
    allowed_parameter_keys: frozenset[str]
    rollback_plan: str


ACTION_CATALOG: dict[AllowedActionType, ActionCatalogEntry] = {
    AllowedActionType.RESET_DB_CONNECTION_POOL: ActionCatalogEntry(
        action_type=AllowedActionType.RESET_DB_CONNECTION_POOL,
        allowed_targets=frozenset({ServiceId.ORDER_SERVICE, ServiceId.POSTGRES}),
        default_risk_level=RiskLevel.MEDIUM,
        requires_human_approval=True,
        allowed_parameter_keys=frozenset({"force", "drain_timeout_seconds"}),
        rollback_plan=(
            "Restore standard pool configuration and restart order-service "
            "if connection acquisition does not stabilize within 60s."
        ),
    ),
    AllowedActionType.RESTART_SERVICE_CONTAINER: ActionCatalogEntry(
        action_type=AllowedActionType.RESTART_SERVICE_CONTAINER,
        allowed_targets=frozenset({ServiceId.ORDER_SERVICE}),
        default_risk_level=RiskLevel.HIGH,
        requires_human_approval=True,
        allowed_parameter_keys=frozenset({"grace_period_seconds"}),
        rollback_plan=(
            "Re-deploy previous healthy container image tag and reset traffic routing."
        ),
    ),
}


class ActionRequest(BaseModel):
    """Validated remediation action request matching the shared remediation contract."""

    action_id: str = Field(min_length=4, max_length=64)
    incident_id: str = Field(min_length=4, max_length=64)
    action_type: str = Field(min_length=3, max_length=64)
    parameters: dict[str, str | int | bool] = Field(default_factory=dict)
    target: str = Field(min_length=2, max_length=64)
    risk_level: RiskLevel
    preconditions: list[str] = Field(default_factory=list)
    requested_by: str = Field(min_length=2, max_length=64)
    approval_status: ApprovalStatus
    idempotency_key: str = Field(min_length=4, max_length=128)


class PolicyEvaluationResult(BaseModel):
    """Result of evaluating an ActionRequest against the deterministic policy catalog."""

    allowed: bool
    requires_human_approval: bool = True
    violation_code: str | None = None
    reason: str
    rollback_plan: str = ""


def evaluate_remediation_policy(request: ActionRequest) -> PolicyEvaluationResult:
    """Validate action type, target service, parameters, and preconditions."""
    try:
        typed_action = AllowedActionType(request.action_type)
    except ValueError:
        return PolicyEvaluationResult(
            allowed=False,
            violation_code="UNALLOWLISTED_ACTION_TYPE",
            reason=f"Action type '{request.action_type}' is not in the allowlisted catalog.",
        )

    catalog_entry = ACTION_CATALOG[typed_action]

    try:
        typed_target = ServiceId(request.target)
    except ValueError:
        return PolicyEvaluationResult(
            allowed=False,
            violation_code="INVALID_TARGET_SERVICE",
            reason=f"Target '{request.target}' is not a recognized service identifier.",
        )

    if typed_target not in catalog_entry.allowed_targets:
        return PolicyEvaluationResult(
            allowed=False,
            violation_code="TARGET_NOT_PERMITTED_FOR_ACTION",
            reason=(
                f"Target '{typed_target.value}' is not permitted for action "
                f"'{typed_action.value}'."
            ),
        )

    unknown_keys = set(request.parameters.keys()) - catalog_entry.allowed_parameter_keys
    if unknown_keys:
        sorted_unknown = ", ".join(sorted(unknown_keys))
        return PolicyEvaluationResult(
            allowed=False,
            violation_code="INVALID_ACTION_PARAMETERS",
            reason=f"Unsupported parameter keys for '{typed_action.value}': {sorted_unknown}",
        )

    if not request.preconditions:
        return PolicyEvaluationResult(
            allowed=False,
            violation_code="MISSING_PRECONDITIONS",
            reason="Remediation action requests must declare verifiable preconditions.",
        )

    return PolicyEvaluationResult(
        allowed=True,
        requires_human_approval=catalog_entry.requires_human_approval,
        reason="Action request conforms to deterministic remediation policy catalog.",
        rollback_plan=catalog_entry.rollback_plan,
    )