"""Application, AI, XSS, and burst-idempotency security tests."""

from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import ActionExecution, Alert, Incident, ServiceId, Severity
from app.db.repository import NormalizedAlertInput
from app.db.session import get_db
from app.integrations.telemetry import MockTelemetryAdapter
from app.main import create_app
from app.observability.logging import build_structured_log_entry
from app.services.incident_service import IncidentService
from app.services.remediation_service import RemediationService


@pytest.fixture()
def app_security_db() -> Generator[Session, None, None]:
    """Provide an isolated in-memory database for application security tests."""
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


def test_structured_logger_redacts_secrets_and_connection_uris() -> None:
    """Verify structured logging scrubs DB passwords, tokens, and API keys."""
    entry = build_structured_log_entry(
        level="error",
        event="db.connection_failed",
        message=(
            "Failed connecting to postgresql+psycopg://admin:MySuperSecret99@db:5432/prod "
            "with token=abc123secret and Bearer eyJhbGciOiJIUzI1NiJ9"
        ),
        incident_id="inc-sec-001",
        service_id="order-service",
    )

    msg = str(entry["message"])
    assert "MySuperSecret99" not in msg
    assert "abc123secret" not in msg
    assert "eyJhbGciOiJIUzI1NiJ9" not in msg
    assert "[REDACTED_SECRET]" in msg


def test_html_ui_escapes_xss_payloads_in_incident_titles(
    app_security_db: Session,
) -> None:
    """Verify Incident HTML UI neutralizes malicious script tags against XSS."""
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        yield app_security_db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    xss_title = "<script>alert('xss-pwned')</script> High 5xx on order-service"
    ingest_resp = client.post(
        "/api/v1/incidents/ingest",
        json={
            "idempotency_key": "xss-delivery-001",
            "alert_fingerprint": "fp-xss-test",
            "service_id": "order-service",
            "title": xss_title,
            "severity": "CRITICAL",
            "starts_at_utc": "2026-10-31T10:00:00Z",
        },
    )
    assert ingest_resp.status_code == 201
    incident_id = ingest_resp.json()["id"]

    ui_resp = client.get(f"/api/v1/incidents/{incident_id}/ui")
    assert ui_resp.status_code == 200
    html_text = ui_resp.text

    assert "<script>alert('xss-pwned')</script>" not in html_text
    assert "&lt;script&gt;alert(&#x27;xss-pwned&#x27;)&lt;/script&gt;" in html_text


def test_burst_alert_and_execution_retries_preserve_strict_idempotency(
    app_security_db: Session,
) -> None:
    """Verify burst duplicate alerts and repeated execution calls never corrupt state."""
    inc_service = IncidentService(
        session=app_security_db,
        telemetry_adapter=MockTelemetryAdapter(fault_injected=True),
    )
    alert_payload = NormalizedAlertInput(
        idempotency_key="burst-key-001",
        alert_fingerprint="fp-burst-pool",
        service_id=ServiceId.ORDER_SERVICE,
        title="Burst alert idempotency stress test",
        severity=Severity.CRITICAL,
        starts_at_utc=datetime(2026, 10, 31, 12, 0, 0, tzinfo=UTC),
    )

    first_inc, first_created = inc_service.ingest_and_investigate(alert_payload)
    assert first_created is True

    for _ in range(9):
        inc_repeat, created_repeat = inc_service.ingest_and_investigate(alert_payload)
        assert created_repeat is False
        assert inc_repeat.id == first_inc.id

    assert len(list(app_security_db.scalars(select(Incident)).all())) == 1
    assert len(list(app_security_db.scalars(select(Alert)).all())) == 1

    proposal_id = first_inc.remediation_proposals[0].id
    rem_service = RemediationService(
        session=app_security_db,
        telemetry_adapter=MockTelemetryAdapter(fault_injected=False),
    )
    rem_service.record_approval_decision(
        proposal_id=proposal_id,
        approver_id="sre.rasool",
        decision="APPROVED",
        reason="Approved for burst idempotency test",
    )

    first_exec, _first_verif = rem_service.execute_and_verify_proposal(proposal_id)
    for _ in range(4):
        repeat_exec, _repeat_verif = rem_service.execute_and_verify_proposal(proposal_id)
        assert repeat_exec.id == first_exec.id

    assert len(list(app_security_db.scalars(select(ActionExecution)).all())) == 1