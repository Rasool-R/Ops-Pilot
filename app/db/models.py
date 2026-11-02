"""SQLAlchemy ORM models for incidents, alerts, RCA artifacts, remediation, and audit."""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base


def utc_now() -> datetime:
    """Return current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def new_uuid_str() -> str:
    """Generate a new UUID4 string primary key."""
    return str(uuid4())


class ServiceId(StrEnum):
    """Allowed target services in the MVP e-commerce topology."""

    FRONTEND = "frontend"
    API_GATEWAY = "api-gateway"
    ORDER_SERVICE = "order-service"
    PAYMENT_SERVICE = "payment-service"
    INVENTORY_SERVICE = "inventory-service"
    POSTGRES = "postgres"


class Severity(StrEnum):
    """Normalized alert and incident severity levels."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    WARNING = "WARNING"
    INFO = "INFO"


class IncidentStatus(StrEnum):
    """Top-level incident lifecycle status."""

    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    MITIGATING = "MITIGATING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class InvestigationStatus(StrEnum):
    """LangGraph RCA investigation workflow status."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    INCONCLUSIVE = "INCONCLUSIVE"
    FAILED = "FAILED"


class ApprovalStatus(StrEnum):
    """Human approval lifecycle status for remediation proposals."""

    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class RemediationExecutionStatus(StrEnum):
    """Execution status of an authorized remediation action."""

    NOT_STARTED = "NOT_STARTED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


class RecoveryVerificationStatus(StrEnum):
    """Post-remediation fresh-telemetry verification status."""

    PENDING = "PENDING"
    VERIFYING = "VERIFYING"
    VERIFIED_RECOVERED = "VERIFIED_RECOVERED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    ESCALATED = "ESCALATED"


class Incident(Base):
    """Primary business record for an operational incident with distinct state machines."""

    __tablename__ = "incidents"
    __table_args__ = (
        Index("ix_incidents_service_fingerprint", "service_id", "alert_fingerprint"),
        Index("ix_incidents_status", "incident_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid_str)
    service_id: Mapped[str] = mapped_column(String(64), nullable=False)
    alert_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)

    # Distinct state machines (never combined into a single generic status)
    incident_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=IncidentStatus.OPEN.value
    )
    investigation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=InvestigationStatus.PENDING.value
    )
    approval_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ApprovalStatus.NOT_REQUIRED.value
    )
    remediation_execution_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=RemediationExecutionStatus.NOT_STARTED.value
    )
    recovery_verification_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=RecoveryVerificationStatus.PENDING.value
    )

    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    resolved_at_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    alerts: Mapped[list["Alert"]] = relationship(
        "Alert", back_populates="incident", cascade="all, delete-orphan"
    )
    evidence_records: Mapped[list["EvidenceRecord"]] = relationship(
        "EvidenceRecord", back_populates="incident", cascade="all, delete-orphan"
    )
    hypotheses: Mapped[list["HypothesisRecord"]] = relationship(
        "HypothesisRecord", back_populates="incident", cascade="all, delete-orphan"
    )
    diagnostic_runs: Mapped[list["DiagnosticRun"]] = relationship(
        "DiagnosticRun", back_populates="incident", cascade="all, delete-orphan"
    )
    remediation_proposals: Mapped[list["RemediationProposal"]] = relationship(
        "RemediationProposal", back_populates="incident", cascade="all, delete-orphan"
    )
    approval_decisions: Mapped[list["ApprovalDecision"]] = relationship(
        "ApprovalDecision", back_populates="incident", cascade="all, delete-orphan"
    )
    action_executions: Mapped[list["ActionExecution"]] = relationship(
        "ActionExecution", back_populates="incident", cascade="all, delete-orphan"
    )
    verification_results: Mapped[list["VerificationResult"]] = relationship(
        "VerificationResult", back_populates="incident", cascade="all, delete-orphan"
    )
    report: Mapped["IncidentReport | None"] = relationship(
        "IncidentReport",
        back_populates="incident",
        uselist=False,
        cascade="all, delete-orphan",
    )
    audit_events: Mapped[list["AuditEvent"]] = relationship(
        "AuditEvent", back_populates="incident", cascade="all, delete-orphan"
    )


class Alert(Base):
    """Normalized incoming alert linked to an Incident with strict idempotency."""

    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_incident_id", "incident_id"),
        Index("ix_alerts_fingerprint", "alert_fingerprint"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid_str)
    incident_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    alert_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    service_id: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    starts_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    labels_json: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    annotations_json: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    received_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    incident: Mapped["Incident"] = relationship("Incident", back_populates="alerts")


class EvidenceRecord(Base):
    """Bounded telemetry observation persisted as verifiable evidence for an incident."""

    __tablename__ = "evidence_records"
    __table_args__ = (
        UniqueConstraint("incident_id", "fact_id", name="uq_evidence_incident_fact"),
        Index("ix_evidence_records_incident_id", "incident_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid_str)
    incident_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    fact_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    service_id: Mapped[str] = mapped_column(String(64), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    signal_name: Mapped[str] = mapped_column(String(128), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    numeric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    observed_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    incident: Mapped["Incident"] = relationship("Incident", back_populates="evidence_records")


class HypothesisRecord(Base):
    """Persisted candidate hypothesis evaluated during RCA investigation."""

    __tablename__ = "hypotheses"
    __table_args__ = (
        UniqueConstraint("incident_id", "hypothesis_id", name="uq_hypothesis_incident_hyp"),
        Index("ix_hypotheses_incident_id", "incident_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid_str)
    incident_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    hypothesis_id: Mapped[str] = mapped_column(String(128), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    target_service: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    supporting_fact_ids_json: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    contradicting_fact_ids_json: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )

    incident: Mapped["Incident"] = relationship("Incident", back_populates="hypotheses")


class DiagnosticRun(Base):
    """Persisted record of a bounded diagnostic tool call executed by the agent."""

    __tablename__ = "diagnostic_runs"
    __table_args__ = (
        UniqueConstraint("incident_id", "step_id", name="uq_diagnostic_incident_step"),
        Index("ix_diagnostic_runs_incident_id", "incident_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid_str)
    incident_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    step_id: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    target_service: Mapped[str] = mapped_column(String(64), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    incident: Mapped["Incident"] = relationship("Incident", back_populates="diagnostic_runs")


class RemediationProposal(Base):
    """Persisted remediation proposal awaiting independent policy and human approval."""

    __tablename__ = "remediation_proposals"
    __table_args__ = (Index("ix_remediation_proposals_incident_id", "incident_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid_str)
    incident_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_service: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    requires_human_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    preconditions_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    approval_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ApprovalStatus.PENDING_APPROVAL.value
    )
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    incident: Mapped["Incident"] = relationship(
        "Incident", back_populates="remediation_proposals"
    )


class ApprovalDecision(Base):
    """Human approval or rejection record separated from proposal and execution."""

    __tablename__ = "approval_decisions"
    __table_args__ = (
        Index("ix_approval_decisions_incident_id", "incident_id"),
        Index("ix_approval_decisions_proposal_id", "proposal_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid_str)
    incident_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    proposal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("remediation_proposals.id", ondelete="CASCADE"), nullable=False
    )
    approver_id: Mapped[str] = mapped_column(String(128), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    decided_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    expires_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    incident: Mapped["Incident"] = relationship("Incident", back_populates="approval_decisions")


class ActionExecution(Base):
    """Execution record of an authorized remediation action with idempotency protection."""

    __tablename__ = "action_executions"
    __table_args__ = (Index("ix_action_executions_incident_id", "incident_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid_str)
    incident_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    proposal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("remediation_proposals.id", ondelete="CASCADE"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_service: Mapped[str] = mapped_column(String(64), nullable=False)
    parameters_json: Mapped[dict[str, str | int | bool]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    execution_status: Mapped[str] = mapped_column(String(32), nullable=False)
    output_message: Mapped[str] = mapped_column(Text, nullable=False)
    rollback_plan: Mapped[str] = mapped_column(Text, nullable=False)
    executed_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    incident: Mapped["Incident"] = relationship("Incident", back_populates="action_executions")


class VerificationResult(Base):
    """Post-remediation recovery verification record grounded in fresh telemetry."""

    __tablename__ = "verification_results"
    __table_args__ = (Index("ix_verification_results_incident_id", "incident_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid_str)
    incident_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    execution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("action_executions.id", ondelete="CASCADE"), nullable=False
    )
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False)
    recovered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    observed_5xx_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    observed_pool_wait_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    verified_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    incident: Mapped["Incident"] = relationship(
        "Incident", back_populates="verification_results"
    )


class IncidentReport(Base):
    """Persisted structured RCA report separating facts, hypotheses, and unknowns."""

    __tablename__ = "incident_reports"
    __table_args__ = (Index("ix_incident_reports_incident_id", "incident_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid_str)
    incident_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    root_cause_summary: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    unknowns_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    bounded_next_diagnostic: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_payload_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    incident: Mapped["Incident"] = relationship("Incident", back_populates="report")


class AuditEvent(Base):
    """Append-only audit trail for incident state transitions and policy decisions."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_incident_id", "incident_id"),
        Index("ix_audit_events_event_type", "event_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid_str)
    incident_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    details_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    incident: Mapped["Incident"] = relationship("Incident", back_populates="audit_events")