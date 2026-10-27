"""Database tests for incident persistence, idempotency, correlation, and migrations."""

from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
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
from app.db.repository import IncidentRepository, NormalizedAlertInput

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    """Provide a disposable isolated database session with all ORM tables initialized."""
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def _sample_alert_input(
    idempotency_key: str = "alert-delivery-001",
    fingerprint: str = "fp-order-service-5xx-pool",
) -> NormalizedAlertInput:
    """Create a deterministic normalized alert payload for testing."""
    return NormalizedAlertInput(
        idempotency_key=idempotency_key,
        alert_fingerprint=fingerprint,
        service_id=ServiceId.ORDER_SERVICE,
        title="Elevated HTTP 5xx rate and DB connection pool saturation on order-service",
        severity=Severity.CRITICAL,
        starts_at_utc=datetime(2026, 10, 26, 10, 0, 0, tzinfo=UTC),
        labels={"alertname": "OrderServiceHigh5xxRate", "env": "production"},
        annotations={"summary": "5xx error rate exceeded 15% over 5m"},
    )


def test_ingest_alert_creates_incident_with_distinct_state_machines(
    db_session: Session,
) -> None:
    """Verify initial alert ingestion persists an incident with 5 distinct status fields."""
    repo = IncidentRepository(db_session)
    incident, alert, created_new = repo.ingest_alert(_sample_alert_input())

    assert created_new is True
    assert incident.service_id == "order-service"
    assert incident.incident_status == IncidentStatus.OPEN.value
    assert incident.investigation_status == InvestigationStatus.PENDING.value
    assert incident.approval_status == ApprovalStatus.NOT_REQUIRED.value
    assert incident.remediation_execution_status == RemediationExecutionStatus.NOT_STARTED.value
    assert incident.recovery_verification_status == RecoveryVerificationStatus.PENDING.value
    assert alert.incident_id == incident.id

    audit_events = list(
        db_session.scalars(
            select(AuditEvent).where(AuditEvent.incident_id == incident.id)
        ).all()
    )
    event_types = [ev.event_type for ev in audit_events]
    assert "incident.created" in event_types
    assert "alert.ingested" in event_types


def test_duplicate_alert_with_same_idempotency_key_does_not_duplicate_records(
    db_session: Session,
) -> None:
    """Verify re-delivering the exact same alert idempotency_key is strictly idempotent."""
    repo = IncidentRepository(db_session)
    payload = _sample_alert_input(idempotency_key="dup-key-123")

    inc_first, alert_first, created_first = repo.ingest_alert(payload)
    inc_second, alert_second, created_second = repo.ingest_alert(payload)

    assert created_first is True
    assert created_second is False
    assert inc_first.id == inc_second.id
    assert alert_first.id == alert_second.id

    total_incidents = len(list(db_session.scalars(select(Incident)).all()))
    total_alerts = len(list(db_session.scalars(select(Alert)).all()))
    assert total_incidents == 1
    assert total_alerts == 1


def test_repeated_firing_alert_correlates_into_existing_active_incident(
    db_session: Session,
) -> None:
    """Verify a repeated alert with the same fingerprint attaches to the active incident."""
    repo = IncidentRepository(db_session)
    first_payload = _sample_alert_input(
        idempotency_key="delivery-1", fingerprint="fp-postgres-pool"
    )
    second_payload = _sample_alert_input(
        idempotency_key="delivery-2", fingerprint="fp-postgres-pool"
    )

    inc_1, alert_1, created_1 = repo.ingest_alert(first_payload)
    inc_2, alert_2, created_2 = repo.ingest_alert(second_payload)

    assert created_1 is True
    assert created_2 is False
    assert inc_1.id == inc_2.id
    assert alert_1.id != alert_2.id

    fetched = repo.get_incident_by_id(inc_1.id)
    assert fetched is not None
    assert len(fetched.alerts) == 2


def test_alembic_migration_files_exist_and_define_core_tables() -> None:
    """Verify Alembic configuration and initial migration script are present."""
    alembic_ini = PROJECT_ROOT / "alembic.ini"
    migration_file = (
        PROJECT_ROOT / "alembic" / "versions" / "0001_initial_incident_alert_schema.py"
    )
    assert alembic_ini.exists(), "alembic.ini must exist in root"
    assert migration_file.exists(), "Initial Alembic migration file must exist"

    content = migration_file.read_text(encoding="utf-8")
    assert '"incidents"' in content
    assert '"alerts"' in content
    assert '"audit_events"' in content