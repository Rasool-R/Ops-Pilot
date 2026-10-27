"""SQLAlchemy ORM models for incidents, alerts, and audit events."""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String
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