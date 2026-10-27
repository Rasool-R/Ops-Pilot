"""Application data-access repository with idempotent alert ingestion."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Alert,
    ApprovalStatus,
    AuditEvent,
    Incident,
    IncidentStatus,
    InvestigationStatus,
    RecoveryVerificationStatus,
    RemediationExecutionStatus,
    ServiceId,
    Severity,
)


class NormalizedAlertInput(BaseModel):
    """Validated, bounded input schema for alert ingestion."""

    idempotency_key: str = Field(min_length=4, max_length=128)
    alert_fingerprint: str = Field(min_length=4, max_length=128)
    service_id: ServiceId
    title: str = Field(min_length=3, max_length=255)
    severity: Severity
    starts_at_utc: datetime
    ends_at_utc: datetime | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)


class IncidentRepository:
    """Transactional repository managing Incident, Alert, and AuditEvent persistence."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def ingest_alert(self, alert_in: NormalizedAlertInput) -> tuple[Incident, Alert, bool]:
        """Ingest a normalized alert idempotently and correlate it with an active incident.

        Returns a tuple of (incident, alert, created_new_incident).
        """
        existing_alert = self._session.scalar(
            select(Alert).where(Alert.idempotency_key == alert_in.idempotency_key)
        )
        if existing_alert is not None:
            return existing_alert.incident, existing_alert, False

        active_statuses = (
            IncidentStatus.OPEN.value,
            IncidentStatus.INVESTIGATING.value,
            IncidentStatus.MITIGATING.value,
        )
        incident = self._session.scalar(
            select(Incident)
            .where(
                Incident.service_id == alert_in.service_id.value,
                Incident.alert_fingerprint == alert_in.alert_fingerprint,
                Incident.incident_status.in_(active_statuses),
            )
            .order_by(Incident.created_at_utc.desc())
        )

        created_new_incident = False
        if incident is None:
            created_new_incident = True
            incident = Incident(
                service_id=alert_in.service_id.value,
                alert_fingerprint=alert_in.alert_fingerprint,
                title=alert_in.title,
                severity=alert_in.severity.value,
                incident_status=IncidentStatus.OPEN.value,
                investigation_status=InvestigationStatus.PENDING.value,
                approval_status=ApprovalStatus.NOT_REQUIRED.value,
                remediation_execution_status=RemediationExecutionStatus.NOT_STARTED.value,
                recovery_verification_status=RecoveryVerificationStatus.PENDING.value,
            )
            self._session.add(incident)
            self._session.flush()

            self._session.add(
                AuditEvent(
                    incident_id=incident.id,
                    event_type="incident.created",
                    actor="system.alert_ingestor",
                    details_json={
                        "service_id": incident.service_id,
                        "alert_fingerprint": incident.alert_fingerprint,
                        "severity": incident.severity,
                    },
                )
            )
        else:
            incident.updated_at_utc = datetime.now(UTC)

        alert = Alert(
            incident_id=incident.id,
            idempotency_key=alert_in.idempotency_key,
            alert_fingerprint=alert_in.alert_fingerprint,
            service_id=alert_in.service_id.value,
            severity=alert_in.severity.value,
            starts_at_utc=alert_in.starts_at_utc,
            ends_at_utc=alert_in.ends_at_utc,
            labels_json=dict(alert_in.labels),
            annotations_json=dict(alert_in.annotations),
        )
        self._session.add(alert)
        self._session.flush()

        self._session.add(
            AuditEvent(
                incident_id=incident.id,
                event_type="alert.ingested",
                actor="system.alert_ingestor",
                details_json={
                    "alert_id": alert.id,
                    "idempotency_key": alert.idempotency_key,
                    "created_new_incident": created_new_incident,
                },
            )
        )

        self._session.commit()
        self._session.refresh(incident)
        self._session.refresh(alert)
        return incident, alert, created_new_incident

    def get_incident_by_id(self, incident_id: str) -> Incident | None:
        """Retrieve a single incident by its UUID string."""
        return self._session.scalar(select(Incident).where(Incident.id == incident_id))

    def list_incidents(self, limit: int = 20, offset: int = 0) -> list[Incident]:
        """List incidents ordered by newest first with bounded pagination."""
        bounded_limit = max(1, min(limit, 100))
        bounded_offset = max(0, offset)
        stmt = (
            select(Incident)
            .order_by(Incident.created_at_utc.desc())
            .limit(bounded_limit)
            .offset(bounded_offset)
        )
        return list(self._session.scalars(stmt).all())