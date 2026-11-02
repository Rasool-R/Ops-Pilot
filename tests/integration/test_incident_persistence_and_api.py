"""Integration tests for incident persistence, API pagination, and safe workflow resume."""

from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import (
    DiagnosticRun,
    EvidenceRecord,
    HypothesisRecord,
    IncidentReport,
    InvestigationStatus,
    RemediationProposal,
    ServiceId,
    Severity,
)
from app.db.repository import NormalizedAlertInput
from app.db.session import get_db
from app.integrations.telemetry import MockTelemetryAdapter
from app.main import create_app
from app.services.incident_service import IncidentService


@pytest.fixture()
def integration_db() -> Generator[Session, None, None]:
    """Create a thread-safe in-memory SQLite database for API and service integration tests."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def api_client(integration_db: Session) -> TestClient:
    """Return a FastAPI TestClient wired to the disposable integration database."""
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        yield integration_db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_ingest_api_persists_full_rca_artifacts_and_supports_pagination(
    api_client: TestClient,
    integration_db: Session,
) -> None:
    """Verify /api/v1/incidents/ingest runs RCA, persists all entities, and paginates."""
    payload = {
        "idempotency_key": "api-delivery-001",
        "alert_fingerprint": "fp-order-pool-saturation",
        "service_id": "order-service",
        "title": "High 5xx and connection pool exhaustion on order-service",
        "severity": "CRITICAL",
        "starts_at_utc": "2026-10-28T10:00:00Z",
        "labels": {"alertname": "OrderServiceHigh5xxRate"},
        "annotations": {"summary": "5xx > 20%"},
    }

    resp = api_client.post("/api/v1/incidents/ingest", json=payload)
    assert resp.status_code == 201
    data = resp.json()

    incident_id = data["id"]
    assert data["investigation_status"] == "COMPLETED"
    assert data["approval_status"] == "PENDING_APPROVAL"
    assert data["evidence_count"] >= 5
    assert data["hypotheses_count"] == 2
    assert data["diagnostics_count"] == 3
    assert data["remediation_proposals_count"] == 1
    assert "connection-pool saturation" in data["root_cause_summary"]

    # Verify rows exist in relational tables (source of truth)
    assert len(list(integration_db.scalars(select(EvidenceRecord)).all())) >= 5
    assert len(list(integration_db.scalars(select(HypothesisRecord)).all())) == 2
    assert len(list(integration_db.scalars(select(DiagnosticRun)).all())) == 3
    assert len(list(integration_db.scalars(select(RemediationProposal)).all())) == 1
    assert len(list(integration_db.scalars(select(IncidentReport)).all())) == 1

    # Verify pagination and detail endpoints
    list_resp = api_client.get("/api/v1/incidents", params={"limit": 10, "offset": 0})
    assert list_resp.status_code == 200
    list_payload = list_resp.json()
    assert list_payload["count"] == 1
    assert list_payload["items"][0]["id"] == incident_id

    detail_resp = api_client.get(f"/api/v1/incidents/{incident_id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["id"] == incident_id


def test_interrupted_or_inconclusive_investigation_resumes_safely_without_duplication(
    integration_db: Session,
) -> None:
    """Verify resuming an INCONCLUSIVE investigation updates state without duplicating records."""
    alert_input = NormalizedAlertInput(
        idempotency_key="resume-test-001",
        alert_fingerprint="fp-resume-order-service",
        service_id=ServiceId.ORDER_SERVICE,
        title="Transient telemetry outage during order-service incident",
        severity=Severity.CRITICAL,
        starts_at_utc=datetime(2026, 10, 28, 11, 0, 0, tzinfo=UTC),
    )

    # First attempt: telemetry backend fails -> INCONCLUSIVE
    failing_service = IncidentService(
        session=integration_db,
        telemetry_adapter=MockTelemetryAdapter(fault_injected=True, simulate_failure=True),
    )
    inc_first, created = failing_service.ingest_and_investigate(alert_input)
    assert created is True
    assert inc_first.investigation_status == InvestigationStatus.INCONCLUSIVE.value
    assert len(inc_first.remediation_proposals) == 0

    # Second attempt (Resume): telemetry recovers -> COMPLETED
    healthy_service = IncidentService(
        session=integration_db,
        telemetry_adapter=MockTelemetryAdapter(fault_injected=True, simulate_failure=False),
    )
    inc_resumed = healthy_service.run_or_resume_investigation(inc_first.id)
    assert inc_resumed.investigation_status == InvestigationStatus.COMPLETED.value
    assert len(inc_resumed.remediation_proposals) == 1

    # Third attempt (Idempotent re-run): must not duplicate proposals or evidence
    inc_rerun = healthy_service.run_or_resume_investigation(
        inc_first.id, force_rerun=True
    )
    assert inc_rerun.investigation_status == InvestigationStatus.COMPLETED.value
    proposals = list(integration_db.scalars(select(RemediationProposal)).all())
    reports = list(integration_db.scalars(select(IncidentReport)).all())
    assert len(proposals) == 1
    assert len(reports) == 1